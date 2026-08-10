"""Программное исполнение ноутбука по тегам.

Ноутбук остаётся источником правды: аналитик правит `main_2.ipynb`, а веб-сервис
исполняет ровно те же ячейки, минуя помеченные тегами `skip`/`dev` и неактивный
вариант источника данных.

Почему не nbclient/papermill: полноценное ядро Jupyter здесь ничего не даёт —
ноутбук не использует ни magic-команд, ни `input()`, ни виджетов (проверено), а
взамен ядро добавляет накладные расходы, отдельный процесс и лишний слой ошибок.
Мы исполняем ячейки через `exec` в одном общем namespace — ровно та же семантика,
что и «Run All», но с построчным логом и точкой отмены между ячейками.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import tags as tags_mod

#: chdir процессный, поэтому одновременный прогон двух ноутбуков запрещён.
_CHDIR_LOCK = threading.Lock()

EventCallback = Callable[[dict], None]


class NotebookCancelled(RuntimeError):
    """Прогон остановлен по запросу пользователя."""


class NotebookTimeout(RuntimeError):
    """Прогон превысил отведённое время."""


class NotebookCellError(RuntimeError):
    """Ячейка ноутбука упала. Несёт индекс ячейки и исходный traceback."""

    def __init__(self, cell_index: int, stage: str, original: BaseException, formatted: str):
        super().__init__(f"Ячейка #{cell_index} ({stage or 'без раздела'}): {original!r}")
        self.cell_index = cell_index
        self.stage = stage
        self.original = original
        self.formatted = formatted


@dataclass
class NotebookResult:
    """Итог прогона: namespace ноутбука и статистика."""

    namespace: dict[str, Any]
    executed: int
    skipped: int
    duration_sec: float
    stages: list[str] = field(default_factory=list)


class _StreamToEvents(io.TextIOBase):
    """Подменяет stdout/stderr ноутбука и превращает вывод в события построчно."""

    def __init__(self, emit: EventCallback, stream: str):
        self._emit = emit
        self._stream = stream
        self._buffer = ""

    def write(self, text: str) -> int:  # noqa: D102 - интерфейс TextIOBase
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._emit({"type": "output", "stream": self._stream, "text": line})
        return len(text)

    def flush(self) -> None:  # noqa: D102
        if self._buffer.strip():
            self._emit({"type": "output", "stream": self._stream, "text": self._buffer})
        self._buffer = ""


def load_notebook(path: str | Path) -> dict:
    """Читает .ipynb как обычный JSON — nbformat для этого не нужен."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _markdown_heading(cell: dict) -> str | None:
    """Достаёт заголовок из markdown-ячейки, чтобы показывать его как этап."""
    for raw_line in cell.get("source", []):
        line = raw_line.strip()
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                return title
    return None


def _build_stage_map(cells: list[dict]) -> dict[int, str]:
    """Сопоставляет каждой code-ячейке ближайший markdown-заголовок сверху.

    Это даёт человекочитаемый прогресс («Слайд 18 нижняя левая таблица») вместо
    безликого «ячейка 146 из 317».
    """
    stage_by_cell: dict[int, str] = {}
    current = ""
    for index, cell in enumerate(cells):
        if cell.get("cell_type") == "markdown":
            heading = _markdown_heading(cell)
            if heading:
                current = heading
        else:
            stage_by_cell[index] = current
    return stage_by_cell


def _make_namespace(emit: EventCallback) -> dict[str, Any]:
    """Namespace ноутбука с заглушками того, что даёт IPython."""

    def display(*objects: Any, **_kwargs: Any) -> None:
        """Заглушка IPython.display: в вебе рисовать нечего, пишем в лог."""
        for obj in objects:
            emit({"type": "output", "stream": "display", "text": _short_repr(obj)})

    return {
        "__name__": "__opercom_notebook__",
        "__builtins__": __builtins__,
        "display": display,
    }


def _short_repr(obj: Any, limit: int = 400) -> str:
    try:
        shape = getattr(obj, "shape", None)
        if shape is not None:
            return f"{type(obj).__name__} shape={shape}"
        text = repr(obj)
    except Exception:  # объект может ломаться на repr — лог важнее
        return f"<{type(obj).__name__}>"
    return text if len(text) <= limit else text[:limit] + "…"


def run_notebook(
    notebook_path: str | Path,
    *,
    parameters: dict[str, Any] | None = None,
    data_source: str = "db",
    run_dev_cells: bool = False,
    workdir: str | Path | None = None,
    on_event: EventCallback | None = None,
    cancel_event: threading.Event | None = None,
    timeout_sec: int = 0,
) -> NotebookResult:
    """Исполняет ноутбук по плану тегов и возвращает его namespace.

    Args:
        notebook_path: путь к .ipynb.
        parameters: значения, подставляемые поверх ячейки с тегом `parameters`.
        data_source: какой вариант загрузки данных активен ("db" | "csv").
        run_dev_cells: выполнять ли ячейки с тегом `dev`.
        workdir: рабочая директория прогона. Ноутбук использует относительные пути
            (`.env`), поэтому по умолчанию берётся папка ноутбука.
        on_event: колбэк прогресса. Получает словари с полем `type`:
            `plan`, `cell_start`, `cell_done`, `cell_skipped`, `output`, `error`.
        cancel_event: выставленный флаг останавливает прогон между ячейками.
        timeout_sec: потолок на прогон; 0 — без ограничения.

    Raises:
        NotebookCellError: ячейка упала.
        NotebookCancelled: прогон отменён.
        NotebookTimeout: превышено время.
    """
    notebook_path = Path(notebook_path)
    emit: EventCallback = on_event or (lambda event: None)

    notebook = load_notebook(notebook_path)
    cells = notebook["cells"]
    plan = tags_mod.select_cells(cells, data_source=data_source, run_dev_cells=run_dev_cells)
    stage_by_cell = _build_stage_map(cells)

    to_run = [item for item in plan if item.should_run]
    emit(
        {
            "type": "plan",
            "total_cells": len(cells),
            "code_cells": len(plan),
            "to_run": len(to_run),
            "data_source": data_source,
        }
    )

    namespace = _make_namespace(emit)
    workdir = Path(workdir) if workdir else notebook_path.parent
    started = time.monotonic()
    executed = 0
    skipped = 0
    stages: list[str] = []
    parameters = parameters or {}
    parameters_applied = not parameters  # нечего применять — считаем применённым

    previous_cwd = Path.cwd()
    with _CHDIR_LOCK:
        os.chdir(workdir)
        # sys.path нужен, чтобы `import functions...` и `import app...` резолвились
        # так же, как при запуске Jupyter из корня проекта.
        injected_path = str(workdir.resolve())
        path_was_injected = injected_path not in sys.path
        if path_was_injected:
            sys.path.insert(0, injected_path)
        try:
            for item in plan:
                cell = cells[item.index]
                stage = stage_by_cell.get(item.index, "")

                if not item.should_run:
                    skipped += 1
                    emit(
                        {
                            "type": "cell_skipped",
                            "cell": item.index,
                            "tag": item.tag,
                            "stage": stage,
                            "reason": item.reason,
                        }
                    )
                    continue

                if cancel_event is not None and cancel_event.is_set():
                    raise NotebookCancelled(f"Прогон отменён перед ячейкой #{item.index}")

                elapsed = time.monotonic() - started
                if timeout_sec and elapsed > timeout_sec:
                    raise NotebookTimeout(
                        f"Прогон превысил {timeout_sec} с (остановлен перед ячейкой #{item.index})"
                    )

                if stage and (not stages or stages[-1] != stage):
                    stages.append(stage)

                source = "".join(cell.get("source", []))
                emit(
                    {
                        "type": "cell_start",
                        "cell": item.index,
                        "tag": item.tag,
                        "stage": stage,
                        "executed": executed,
                        "total": len(to_run),
                    }
                )

                cell_started = time.monotonic()
                stdout_proxy = _StreamToEvents(emit, "stdout")
                stderr_proxy = _StreamToEvents(emit, "stderr")
                try:
                    with redirect_stdout(stdout_proxy), redirect_stderr(stderr_proxy):
                        exec(compile(source, f"<notebook cell {item.index}>", "exec"), namespace)
                        stdout_proxy.flush()
                        stderr_proxy.flush()
                except BaseException as exc:  # noqa: BLE001 - пробрасываем c контекстом
                    stdout_proxy.flush()
                    stderr_proxy.flush()
                    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                    emit(
                        {
                            "type": "error",
                            "cell": item.index,
                            "stage": stage,
                            "message": f"{type(exc).__name__}: {exc}",
                            "traceback": formatted,
                        }
                    )
                    raise NotebookCellError(item.index, stage, exc, formatted) from exc

                executed += 1

                # Параметры подставляются сразу после ячейки `parameters`, чтобы
                # переопределить её значения до того, как их кто-то прочитает.
                if item.tag == tags_mod.PARAMETERS and not parameters_applied:
                    namespace.update(parameters)
                    parameters_applied = True
                    emit({"type": "parameters", "values": {k: str(v) for k, v in parameters.items()}})

                emit(
                    {
                        "type": "cell_done",
                        "cell": item.index,
                        "stage": stage,
                        "duration_sec": round(time.monotonic() - cell_started, 3),
                        "executed": executed,
                        "total": len(to_run),
                    }
                )
        finally:
            if path_was_injected:
                try:
                    sys.path.remove(injected_path)
                except ValueError:
                    pass
            os.chdir(previous_cwd)

    if not parameters_applied:
        raise RuntimeError(
            "В ноутбуке нет ячейки с тегом 'parameters', подставить пути некуда. "
            "Запусти scripts/tag_notebook.py."
        )

    return NotebookResult(
        namespace=namespace,
        executed=executed,
        skipped=skipped,
        duration_sec=round(time.monotonic() - started, 3),
        stages=stages,
    )


def describe_plan(
    notebook_path: str | Path,
    *,
    data_source: str = "db",
    run_dev_cells: bool = False,
) -> Iterable[tags_mod.CellSelection]:
    """План прогона без исполнения — для проверок и для отладочного эндпоинта."""
    notebook = load_notebook(notebook_path)
    return tags_mod.select_cells(
        notebook["cells"], data_source=data_source, run_dev_cells=run_dev_cells
    )
