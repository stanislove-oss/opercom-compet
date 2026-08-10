"""Реестр фоновых прогонов.

Сборка идёт минуты, HTTP-запрос столько ждать не должен. Поэтому нажатие кнопки
только ставит задачу в очередь и сразу отдаёт `run_id`; интерфейс опрашивает
статус.

Прогоны выполняются строго по одному: раннер делает `chdir`, а сама сборка
упирается в память и в сетевую шару — параллелить нечего.

Хранилище — в памяти процесса. Для одного воркера этого достаточно; если появится
несколько процессов (gunicorn -w N), состояние нужно вынести в Redis/БД, а очередь
— в Celery/RQ. Интерфейс `JobManager` под такую замену и написан.
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from .config import Settings
from .pipeline import build_presentation, describe_error, new_run_id

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]

#: Сколько строк лога держим на прогон. Хватает, чтобы увидеть весь ход сборки.
LOG_LIMIT = 4000


@dataclass
class Job:
    """Один прогон сборки презентации."""

    id: str
    status: JobStatus = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    stage: str = ""
    executed: int = 0
    total: int = 0

    output_path: Path | None = None
    output_size: int | None = None
    error: dict[str, Any] | None = None
    preflight: list[dict] | None = None

    log: deque[dict] = field(default_factory=lambda: deque(maxlen=LOG_LIMIT))
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def progress(self) -> float:
        """Доля выполненного, 0..1."""
        return round(self.executed / self.total, 4) if self.total else 0.0

    @property
    def is_terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")

    def as_dict(self, *, log_offset: int = 0) -> dict[str, Any]:
        """Представление для API. `log_offset` — сколько строк лога уже у клиента."""
        log_items = list(self.log)
        return {
            "id": self.id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "stage": self.stage,
            "executed": self.executed,
            "total": self.total,
            "progress": self.progress,
            "download_available": self.status == "succeeded" and self.output_path is not None,
            "output_size": self.output_size,
            "error": self.error,
            "preflight": self.preflight,
            "log": log_items[log_offset:],
            "log_total": len(log_items),
        }


class JobManager:
    """Очередь на один воркер + реестр прогонов."""

    def __init__(self, settings: Settings, *, max_jobs: int = 50) -> None:
        self._settings = settings
        self._jobs: dict[str, Job] = {}
        self._order: deque[str] = deque()
        self._max_jobs = max_jobs
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(target=self._run_forever, name="opercom-worker", daemon=True)
        self._worker.start()

    # --- публичный интерфейс -------------------------------------------------

    def submit(self) -> Job:
        """Ставит новый прогон в очередь и возвращает его."""
        job = Job(id=new_run_id())
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._evict_locked()
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """Прогоны от новых к старым."""
        with self._lock:
            return [self._jobs[i] for i in reversed(self._order) if i in self._jobs]

    def active(self) -> Job | None:
        """Прогон, который сейчас выполняется или ждёт очереди."""
        with self._lock:
            for job_id in reversed(self._order):
                job = self._jobs.get(job_id)
                if job and not job.is_terminal:
                    return job
        return None

    def cancel(self, job_id: str) -> bool:
        """Просит прогон остановиться. Реально он встанет на границе ячейки."""
        job = self.get(job_id)
        if job is None or job.is_terminal:
            return False
        job.cancel_event.set()
        job.log.append(_log_entry("info", "Запрошена отмена прогона"))
        return True

    # --- воркер --------------------------------------------------------------

    def _run_forever(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.get(job_id)
            if job is None:
                continue
            if job.cancel_event.is_set():
                self._finish(job, "cancelled", error={"kind": "cancelled", "message": "Отменён до старта"})
                continue
            self._execute(job)

    def _execute(self, job: Job) -> None:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.log.append(_log_entry("info", "Прогон запущен"))

        try:
            result = build_presentation(
                self._settings,
                run_id=job.id,
                on_event=lambda event: self._on_event(job, event),
                cancel_event=job.cancel_event,
            )
        except BaseException as exc:  # noqa: BLE001 - воркер не должен умирать
            info = describe_error(exc)
            status: JobStatus = "cancelled" if info["kind"] == "cancelled" else "failed"
            job.log.append(_log_entry("error", f"{info['message']}: {info.get('detail', '')}".strip(": ")))
            if info.get("checks"):
                job.preflight = info["checks"]
            self._finish(job, status, error=info)
            return

        job.output_path = result.output_path
        job.output_size = result.output_path.stat().st_size
        job.log.append(
            _log_entry(
                "info",
                f"Готово за {result.duration_sec:.1f} с: "
                f"{result.executed_cells} ячеек, {result.dataframes_total} датафреймов",
            )
        )
        self._finish(job, "succeeded")

    def _finish(self, job: Job, status: JobStatus, *, error: dict | None = None) -> None:
        job.status = status
        job.error = error
        job.finished_at = datetime.now(timezone.utc)

    def _on_event(self, job: Job, event: dict) -> None:
        """Переводит событие раннера в строку лога и обновляет прогресс."""
        kind = event.get("type")

        if kind == "plan":
            job.total = event["to_run"]
            job.log.append(
                _log_entry(
                    "info",
                    f"План: {event['to_run']} ячеек к исполнению из {event['code_cells']} "
                    f"(источник данных: {event['data_source']})",
                )
            )
        elif kind == "preflight":
            job.preflight = event["checks"]
        elif kind == "cell_start":
            if event.get("stage") and event["stage"] != job.stage:
                job.stage = event["stage"]
                job.log.append(_log_entry("stage", event["stage"]))
        elif kind == "cell_done":
            job.executed = event["executed"]
            if event["duration_sec"] >= 5:
                job.log.append(
                    _log_entry("info", f"Ячейка #{event['cell']} — {event['duration_sec']:.1f} с")
                )
        elif kind == "output":
            job.log.append(_log_entry(event.get("stream", "stdout"), event["text"]))
        elif kind == "error":
            job.log.append(_log_entry("error", f"Ячейка #{event['cell']}: {event['message']}"))
        elif kind == "parameters":
            job.log.append(_log_entry("info", "Параметры прогона подставлены"))

    # --- служебное -----------------------------------------------------------

    def _evict_locked(self) -> None:
        """Выбрасывает из памяти самые старые завершённые прогоны."""
        while len(self._order) > self._max_jobs:
            oldest = self._order.popleft()
            job = self._jobs.get(oldest)
            if job is not None and not job.is_terminal:
                # Незавершённый прогон не выбрасываем — возвращаем в начало.
                self._order.appendleft(oldest)
                return
            self._jobs.pop(oldest, None)


def _log_entry(level: str, text: str) -> dict[str, str]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": level,
        "text": text,
    }


def iter_recent(jobs: Iterable[Job], limit: int = 10) -> list[dict]:
    """Короткая сводка по последним прогонам для списка в интерфейсе."""
    summary = []
    for job in list(jobs)[:limit]:
        summary.append(
            {
                "id": job.id,
                "status": job.status,
                "created_at": job.created_at.isoformat(),
                "progress": job.progress,
                "download_available": job.status == "succeeded",
            }
        )
    return summary
