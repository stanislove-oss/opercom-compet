"""Один прогон сборки презентации: от нажатия кнопки до готового .pptx.

Это единственное место, которое знает, что «собрать презентацию» = «исполнить
ноутбук по тегам и забрать OUTPUT_PPTX». Веб-слой сюда не заглядывает — он
дёргает `build_presentation` и показывает события.
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .notebook_runner import (
    EventCallback,
    NotebookCancelled,
    NotebookCellError,
    NotebookTimeout,
    run_notebook,
)
from .preflight import is_ready, run_checks

OUTPUT_FILENAME = "main_2_filled.pptx"


class PreflightFailed(RuntimeError):
    """Окружение не готово — прогон даже не начинался."""

    def __init__(self, checks: list) -> None:
        failed = [c for c in checks if c.blocking and not c.ok]
        super().__init__("; ".join(f"{c.name}: {c.detail}" for c in failed))
        self.checks = checks


@dataclass
class BuildResult:
    """Итог прогона."""

    output_path: Path
    executed_cells: int
    skipped_cells: int
    duration_sec: float
    stages: list[str] = field(default_factory=list)
    #: Датафреймы, для которых в CHART_SPECS не нашлось графика (диагностика).
    dataframes_total: int = 0


def _run_dir(settings: Settings, run_id: str) -> Path:
    return settings.runs_root / run_id


def new_run_id() -> str:
    """Идентификатор прогона: сортируемый и читаемый в имени папки."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")[:-3]


def build_presentation(
    settings: Settings,
    *,
    run_id: str | None = None,
    on_event: EventCallback | None = None,
    cancel_event: threading.Event | None = None,
    skip_preflight: bool = False,
) -> BuildResult:
    """Собирает презентацию и возвращает путь к готовому файлу.

    Args:
        settings: конфигурация развёртывания.
        run_id: идентификатор прогона; по умолчанию генерируется.
        on_event: колбэк прогресса (события из notebook_runner + свои).
        cancel_event: флаг отмены, проверяется между ячейками.
        skip_preflight: пропустить проверку готовности окружения.

    Raises:
        PreflightFailed: окружение не готово.
        NotebookCellError / NotebookCancelled / NotebookTimeout: см. notebook_runner.
        FileNotFoundError: ноутбук отработал, но файла результата нет.
    """
    emit: EventCallback = on_event or (lambda event: None)
    run_id = run_id or new_run_id()

    if not skip_preflight:
        checks = run_checks(settings)
        emit({"type": "preflight", "checks": [c.as_dict() for c in checks]})
        if not is_ready(checks):
            raise PreflightFailed(checks)

    run_dir = _run_dir(settings, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = run_dir / OUTPUT_FILENAME

    emit({"type": "started", "run_id": run_id, "output": str(output_path)})

    result = run_notebook(
        settings.notebook_path,
        parameters=settings.notebook_parameters(output_path),
        data_source=settings.data_source,
        run_dev_cells=settings.run_dev_cells,
        workdir=settings.notebook_path.parent,
        on_event=emit,
        cancel_event=cancel_event,
        timeout_sec=settings.run_timeout_sec,
    )

    if not output_path.exists():
        raise FileNotFoundError(
            f"Ноутбук отработал ({result.executed} ячеек), но файл {output_path} не появился. "
            "Проверь, что финальная ячейка сохраняет презентацию в OUTPUT_PPTX."
        )

    dataframes = result.namespace.get("dataframes") or {}
    build = BuildResult(
        output_path=output_path,
        executed_cells=result.executed,
        skipped_cells=result.skipped,
        duration_sec=result.duration_sec,
        stages=result.stages,
        dataframes_total=len(dataframes),
    )

    emit(
        {
            "type": "finished",
            "run_id": run_id,
            "output": str(output_path),
            "size_bytes": output_path.stat().st_size,
            "executed_cells": build.executed_cells,
            "skipped_cells": build.skipped_cells,
            "dataframes": build.dataframes_total,
            "duration_sec": build.duration_sec,
        }
    )

    _cleanup_old_runs(settings, keep=settings.keep_runs)
    return build


def _cleanup_old_runs(settings: Settings, *, keep: int) -> None:
    """Удаляет старые папки прогонов, оставляя `keep` последних."""
    if keep <= 0 or not settings.runs_root.exists():
        return
    run_dirs = sorted((p for p in settings.runs_root.iterdir() if p.is_dir()), reverse=True)
    for stale in run_dirs[keep:]:
        shutil.rmtree(stale, ignore_errors=True)


def describe_error(exc: BaseException) -> dict[str, Any]:
    """Приводит исключение прогона к виду, пригодному для показа в интерфейсе."""
    if isinstance(exc, PreflightFailed):
        return {
            "kind": "preflight",
            "message": "Окружение не готово к запуску",
            "detail": str(exc),
            "checks": [c.as_dict() for c in exc.checks],
        }
    if isinstance(exc, NotebookCellError):
        return {
            "kind": "cell",
            "message": f"Ошибка в ячейке #{exc.cell_index}",
            "detail": f"{exc.stage or 'без раздела'}: {exc.original!r}",
            "traceback": exc.formatted,
            "cell": exc.cell_index,
        }
    if isinstance(exc, NotebookCancelled):
        return {"kind": "cancelled", "message": "Прогон отменён", "detail": str(exc)}
    if isinstance(exc, NotebookTimeout):
        return {"kind": "timeout", "message": "Превышено время прогона", "detail": str(exc)}
    return {"kind": "error", "message": type(exc).__name__, "detail": str(exc)}


#: Тип колбэка, чтобы веб-слой не импортировал notebook_runner напрямую.
ProgressCallback = Callable[[dict], None]
