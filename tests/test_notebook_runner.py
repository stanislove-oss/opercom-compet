"""Тесты механики тегов и раннера.

Настоящий ноутбук здесь не запускается: он требует пакета `app`, MySQL и сетевой
шары. Поэтому механику проверяем на синтетических ноутбуках, а на настоящем —
только разметку (test_real_notebook_*).

    python -m pytest tests/ -q
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opercom import tags as T  # noqa: E402
from opercom.notebook_runner import (  # noqa: E402
    NotebookCancelled,
    NotebookCellError,
    describe_plan,
    run_notebook,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_NOTEBOOK = REPO_ROOT / "main_2.ipynb"


def make_notebook(cells: list[tuple[str, str]], path: Path) -> Path:
    """Собирает .ipynb из пар (тег, исходник). Тег 'md' — markdown-ячейка."""
    nb_cells = []
    for tag, source in cells:
        if tag == "md":
            nb_cells.append({"cell_type": "markdown", "metadata": {}, "source": source.splitlines(True)})
        else:
            nb_cells.append(
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {"tags": [tag]},
                    "outputs": [],
                    "source": source.splitlines(True),
                }
            )
    path.write_text(
        json.dumps({"cells": nb_cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}),
        encoding="utf-8",
    )
    return path


# --- отбор ячеек ------------------------------------------------------------


def test_skip_cells_are_not_executed(tmp_path):
    notebook = make_notebook(
        [
            (T.PARAMETERS, "VALUE = 'default'"),
            (T.RUN, "executed = ['run']"),
            (T.SKIP, "raise AssertionError('skip-ячейка не должна выполняться')"),
            (T.RUN, "executed.append('run2')"),
        ],
        tmp_path / "nb.ipynb",
    )

    result = run_notebook(notebook, parameters={"VALUE": "injected"})

    assert result.namespace["executed"] == ["run", "run2"]
    assert result.executed == 3
    assert result.skipped == 1


def test_parameters_override_defaults(tmp_path):
    notebook = make_notebook(
        [
            (T.PARAMETERS, "OUTPUT = 'from-notebook'"),
            (T.RUN, "seen = OUTPUT"),
        ],
        tmp_path / "nb.ipynb",
    )

    result = run_notebook(notebook, parameters={"OUTPUT": "from-web"})

    # Ячейка параметров отработала, но её значение перекрыто рантаймом.
    assert result.namespace["seen"] == "from-web"


def test_data_source_selects_one_variant(tmp_path):
    notebook = make_notebook(
        [
            (T.PARAMETERS, "pass"),
            (T.SOURCE_DB, "source = 'db'"),
            (T.SOURCE_CSV, "source = 'csv'"),
        ],
        tmp_path / "nb.ipynb",
    )

    assert run_notebook(notebook, data_source="db").namespace["source"] == "db"
    assert run_notebook(notebook, data_source="csv").namespace["source"] == "csv"


def test_dev_cells_are_opt_in(tmp_path):
    notebook = make_notebook(
        [
            (T.PARAMETERS, "pass"),
            (T.DEV, "dumped = True"),
        ],
        tmp_path / "nb.ipynb",
    )

    assert "dumped" not in run_notebook(notebook).namespace
    assert run_notebook(notebook, run_dev_cells=True).namespace["dumped"] is True


def test_untagged_code_cell_is_rejected(tmp_path):
    path = tmp_path / "nb.ipynb"
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "metadata": {}, "source": ["x = 1"], "outputs": []}
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="нет тега"):
        run_notebook(path)


def test_unknown_data_source_is_rejected(tmp_path):
    notebook = make_notebook([(T.PARAMETERS, "pass")], tmp_path / "nb.ipynb")

    with pytest.raises(ValueError, match="Неизвестный data_source"):
        run_notebook(notebook, data_source="postgres")


# --- ошибки, отмена, события ------------------------------------------------


def test_cell_error_carries_index_and_stage(tmp_path):
    notebook = make_notebook(
        [
            (T.PARAMETERS, "pass"),
            ("md", "## Слайд 18 нижняя левая таблица"),
            (T.RUN, "1 / 0"),
        ],
        tmp_path / "nb.ipynb",
    )

    with pytest.raises(NotebookCellError) as excinfo:
        run_notebook(notebook)

    error = excinfo.value
    assert error.cell_index == 2
    assert error.stage == "Слайд 18 нижняя левая таблица"
    assert isinstance(error.original, ZeroDivisionError)
    assert "ZeroDivisionError" in error.formatted


def test_cancel_stops_between_cells(tmp_path):
    notebook = make_notebook(
        [
            (T.PARAMETERS, "pass"),
            (T.RUN, "first = True"),
            (T.RUN, "second = True"),
        ],
        tmp_path / "nb.ipynb",
    )

    cancel = threading.Event()
    events = []

    def on_event(event):
        events.append(event)
        # Отменяем сразу после первой боевой ячейки.
        if event["type"] == "cell_done" and event["cell"] == 1:
            cancel.set()

    with pytest.raises(NotebookCancelled):
        run_notebook(notebook, on_event=on_event, cancel_event=cancel)

    assert any(e["type"] == "cell_done" and e["cell"] == 1 for e in events)
    assert not any(e["type"] == "cell_done" and e["cell"] == 2 for e in events)


def test_stdout_becomes_events(tmp_path):
    notebook = make_notebook(
        [
            (T.PARAMETERS, "pass"),
            (T.RUN, "print('Нет CHART_SPECS для dataframe: nat_tv_summary')"),
        ],
        tmp_path / "nb.ipynb",
    )

    events = []
    run_notebook(notebook, on_event=events.append)

    outputs = [e["text"] for e in events if e["type"] == "output"]
    assert "Нет CHART_SPECS для dataframe: nat_tv_summary" in outputs


def test_stage_follows_markdown_headings(tmp_path):
    notebook = make_notebook(
        [
            (T.PARAMETERS, "pass"),
            ("md", "# Фуд Ритейл"),
            (T.RUN, "a = 1"),
            ("md", "## Слайд 12 левая таблица"),
            (T.RUN, "b = 2"),
        ],
        tmp_path / "nb.ipynb",
    )

    result = run_notebook(notebook)

    assert result.stages == ["Фуд Ритейл", "Слайд 12 левая таблица"]


def test_display_stub_does_not_crash(tmp_path):
    """Ноутбук вызывает display() — вне Jupyter его нет, раннер даёт заглушку."""
    notebook = make_notebook(
        [
            (T.PARAMETERS, "pass"),
            (T.RUN, "display({'meta': 1})"),
        ],
        tmp_path / "nb.ipynb",
    )

    events = []
    run_notebook(notebook, on_event=events.append)

    assert any(e["type"] == "output" and e.get("stream") == "display" for e in events)


# --- настоящий ноутбук: только разметка -------------------------------------


@pytest.mark.skipif(not REAL_NOTEBOOK.exists(), reason="main_2.ipynb отсутствует")
@pytest.mark.parametrize("data_source", ["db", "csv"])
def test_real_notebook_plan_is_valid(data_source):
    plan = list(describe_plan(REAL_NOTEBOOK, data_source=data_source))

    assert plan, "план пуст"
    assert sum(1 for item in plan if item.should_run) > 100
    # Ровно один вариант источника данных активен.
    active_sources = [i for i in plan if i.tag in T.SOURCE_TAGS.values() and i.should_run]
    assert active_sources, "не выбран ни один источник данных"
    assert {i.tag for i in active_sources} == {T.SOURCE_TAGS[data_source]}


@pytest.mark.skipif(not REAL_NOTEBOOK.exists(), reason="main_2.ipynb отсутствует")
def test_real_notebook_has_exactly_one_parameters_cell():
    plan = list(describe_plan(REAL_NOTEBOOK))
    assert sum(1 for item in plan if item.tag == T.PARAMETERS) == 1


@pytest.mark.skipif(not REAL_NOTEBOOK.exists(), reason="main_2.ipynb отсутствует")
def test_real_notebook_parameters_cell_is_first():
    plan = list(describe_plan(REAL_NOTEBOOK))
    assert plan[0].tag == T.PARAMETERS, "ячейка параметров должна идти первой"


# --- колбэк прогресса не должен попадать в собственный перехват вывода -------


def test_printing_callback_does_not_recurse(tmp_path, capsys):
    """Ровно тот случай, на котором падал CLI.

    Пока идёт ячейка, sys.stdout подменён на перехватчик. Колбэк CLI печатает
    каждую строку вывода — и без ограждения печать уходила обратно в
    перехватчик: write -> колбэк -> print -> write -> ... RecursionError
    на первой же строке, которую напечатала ячейка.
    """
    notebook = make_notebook(
        [
            (T.PARAMETERS, "pass"),
            (T.RUN, "print('База: clickhouse')\nprint('  tv: строк 1216404')"),
        ],
        tmp_path / "nb.ipynb",
    )

    seen = []

    def on_event(event):
        if event["type"] == "output":
            seen.append(event["text"])
            print(f"      {event['text']}")      # как в scripts/build_presentation.py

    result = run_notebook(notebook, on_event=on_event)

    assert result.executed == 2
    assert seen == ["База: clickhouse", "  tv: строк 1216404"]

    printed = capsys.readouterr().out
    assert "База: clickhouse" in printed
    assert "тв: строк" not in printed  # ничего не задвоилось


def test_callback_output_does_not_leak_back_as_events(tmp_path):
    """То, что печатает сам колбэк, не должно возвращаться новым событием."""
    notebook = make_notebook(
        [(T.PARAMETERS, "pass"), (T.RUN, "print('одна строка')")],
        tmp_path / "nb.ipynb",
    )

    outputs = []

    def on_event(event):
        if event["type"] == "output":
            outputs.append(event["text"])
            print("эхо от колбэка")

    run_notebook(notebook, on_event=on_event)

    assert outputs == ["одна строка"]


def test_streams_are_restored_after_the_run(tmp_path):
    """Ограждение подменяет потоки временно и обязано вернуть их на место."""
    notebook = make_notebook(
        [(T.PARAMETERS, "pass"), (T.RUN, "print('привет')")],
        tmp_path / "nb.ipynb",
    )

    before_out, before_err = sys.stdout, sys.stderr
    run_notebook(notebook, on_event=lambda event: print("."))

    assert sys.stdout is before_out
    assert sys.stderr is before_err


def test_callback_failure_still_restores_streams(tmp_path):
    """Даже если колбэк упал, подменённые потоки не должны остаться навсегда."""
    notebook = make_notebook(
        [(T.PARAMETERS, "pass"), (T.RUN, "print('привет')")],
        tmp_path / "nb.ipynb",
    )

    before_out, before_err = sys.stdout, sys.stderr

    def broken(event):
        raise RuntimeError("колбэк сломан")

    with pytest.raises(Exception):
        run_notebook(notebook, on_event=broken)

    assert sys.stdout is before_out
    assert sys.stderr is before_err
