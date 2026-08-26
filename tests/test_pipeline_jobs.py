"""Тесты пути «нажали кнопку -> получили файл» на синтетическом ноутбуке."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opercom import pipeline as pipeline_mod  # noqa: E402
from opercom import tags as T  # noqa: E402
from opercom.config import Settings  # noqa: E402
from opercom.jobs import JobManager  # noqa: E402
from opercom.pipeline import PreflightFailed, build_presentation  # noqa: E402
from tests.test_notebook_runner import make_notebook  # noqa: E402

#: Ноутбук-пустышка: читает подставленные пути и сохраняет «презентацию».
FAKE_NOTEBOOK_CELLS = [
    (T.PARAMETERS, "TEMPLATE_PPTX = 'template-по-умолчанию'\nOUTPUT_PPTX = 'output-по-умолчанию'"),
    ("md", "# Сборка"),
    (T.SOURCE_DB, "rows = 100"),
    (T.SOURCE_CSV, "rows = 1"),
    (T.SKIP, "raise AssertionError('не должно выполняться')"),
    (T.RUN, "dataframes = {f'df_{i}': i for i in range(90)}"),
    (
        T.RUN,
        "from pathlib import Path\n"
        "Path(OUTPUT_PPTX).write_bytes(b'PK' + bytes(rows))",
    ),
]


@pytest.fixture
def settings(tmp_path) -> Settings:
    notebook = make_notebook(FAKE_NOTEBOOK_CELLS, tmp_path / "fake.ipynb")
    return Settings(
        notebook_path=notebook,
        template_pptx=tmp_path / "template.pptx",
        runs_root=tmp_path / "runs",
        data_source="db",
        run_timeout_sec=30,
    )


@pytest.fixture
def green_preflight(monkeypatch):
    """Считаем окружение готовым: настоящие БД и шара тесту недоступны."""
    monkeypatch.setattr(pipeline_mod, "run_checks", lambda _settings: [])
    monkeypatch.setattr(pipeline_mod, "is_ready", lambda _checks: True)


def test_build_produces_file_and_stats(settings):
    result = build_presentation(settings, skip_preflight=True)

    assert result.output_path.exists()
    assert result.output_path.read_bytes().startswith(b"PK")
    assert result.dataframes_total == 90
    assert result.stages == ["Сборка"]
    # Ячейка с тегом skip не выполнялась и не уронила прогон.
    assert result.skipped_cells >= 1


def test_output_lands_in_per_run_directory(settings):
    first = build_presentation(settings, run_id="20260101-000000-001", skip_preflight=True)
    second = build_presentation(settings, run_id="20260101-000000-002", skip_preflight=True)

    assert first.output_path != second.output_path
    assert first.output_path.parent.name == "20260101-000000-001"
    assert first.output_path.exists() and second.output_path.exists()


def test_data_source_reaches_the_notebook(settings):
    settings.data_source = "csv"
    result = build_presentation(settings, skip_preflight=True)

    # csv-вариант выставляет rows = 1, db-вариант — 100.
    assert len(result.output_path.read_bytes()) == len(b"PK") + 1


def test_preflight_blocks_the_run(settings, monkeypatch):
    class FailedCheck:
        name, ok, blocking, detail = "Пакет app", False, True, "не найден"

        def as_dict(self):
            return {"name": self.name, "ok": self.ok, "blocking": self.blocking, "detail": self.detail}

    monkeypatch.setattr(pipeline_mod, "run_checks", lambda _s: [FailedCheck()])
    monkeypatch.setattr(pipeline_mod, "is_ready", lambda _c: False)

    with pytest.raises(PreflightFailed, match="Пакет app"):
        build_presentation(settings)

    assert not settings.runs_root.exists(), "папка прогона не должна создаваться"


def test_missing_output_is_reported(settings, tmp_path):
    settings.notebook_path = make_notebook(
        [(T.PARAMETERS, "OUTPUT_PPTX = 'x'"), (T.RUN, "pass")],
        tmp_path / "silent.ipynb",
    )

    with pytest.raises(FileNotFoundError, match="не появился"):
        build_presentation(settings, skip_preflight=True)


def test_cleanup_keeps_only_recent_runs(settings):
    settings.keep_runs = 2
    for i in range(4):
        build_presentation(settings, run_id=f"20260101-00000{i}-000", skip_preflight=True)

    assert sorted(p.name for p in settings.runs_root.iterdir()) == [
        "20260101-000002-000",
        "20260101-000003-000",
    ]


# --- очередь прогонов -------------------------------------------------------


def _wait_for(job, *, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job.is_terminal:
            return job
        time.sleep(0.02)
    raise AssertionError(f"прогон {job.id} не завершился за {timeout} с (статус {job.status})")


def test_job_runs_and_exposes_progress(settings, green_preflight):
    jobs = JobManager(settings)
    job = jobs.submit()

    assert job.status == "queued"
    _wait_for(job)

    assert job.status == "succeeded"
    assert job.output_path.exists()
    assert job.progress == 1.0
    assert job.executed == job.total
    payload = job.as_dict()
    assert payload["download_available"] is True
    assert any("Готово за" in entry["text"] for entry in payload["log"])


def test_job_reports_cell_failure(settings, green_preflight, tmp_path):
    settings.notebook_path = make_notebook(
        [(T.PARAMETERS, "pass"), ("md", "## Слайд 20 левая таблица"), (T.RUN, "1 / 0")],
        tmp_path / "broken.ipynb",
    )
    jobs = JobManager(settings)
    job = _wait_for(jobs.submit())

    assert job.status == "failed"
    assert job.error["kind"] == "cell"
    assert "Слайд 20 левая таблица" in job.error["detail"]
    assert "ZeroDivisionError" in job.error["traceback"]
    assert job.as_dict()["download_available"] is False


def test_only_one_run_is_active(settings, green_preflight):
    jobs = JobManager(settings)
    first = jobs.submit()

    active = jobs.active()
    assert active is not None and active.id == first.id

    _wait_for(first)
    assert jobs.active() is None


def test_log_offset_returns_only_the_tail(settings, green_preflight):
    jobs = JobManager(settings)
    job = _wait_for(jobs.submit())

    full = job.as_dict()
    tail = job.as_dict(log_offset=full["log_total"] - 1)

    assert len(tail["log"]) == 1
    assert tail["log"][0] == full["log"][-1]


# --- проверка готовности: требуем только то, что действительно нужно --------


def test_digital_share_is_not_required_when_digital_comes_from_the_database(monkeypatch):
    """Шара нужна только запасному пути. Блокировать из-за неё — не пускать зря."""
    from opercom import preflight

    monkeypatch.delenv("DIGITAL_XLSX", raising=False)
    settings = Settings(digital_data_root=Path("/нет/такой/шары"))

    check = preflight._check_digital_source(settings)

    assert check.ok is True
    assert "из базы" in check.detail


def test_digital_share_is_required_when_the_workbook_path_is_used(monkeypatch, tmp_path):
    from opercom import preflight

    missing = tmp_path / "нет-файла.xlsx"
    monkeypatch.setenv("DIGITAL_XLSX", str(missing))

    check = preflight._check_digital_source(Settings())

    assert check.ok is False
    assert check.blocking is True
