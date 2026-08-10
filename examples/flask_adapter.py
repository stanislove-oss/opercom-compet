"""ПРИМЕР HTTP-адаптера. Не часть продукта — справочник по контракту.

Веб-интерфейс пишется отдельно. Этот файл показывает, сколько кода нужно, чтобы
подключить `opercom` к произвольному фреймворку: вся предметная логика уже в
пакете, здесь только маршруты. Под Django/DRF переписывается один в один.

Контракт, который нужно реализовать на своей стороне:

    POST /api/runs                  нажатие кнопки -> 202 {"id": ...}
    GET  /api/runs/<id>             статус + прогресс + хвост лога
    POST /api/runs/<id>/cancel      попросить прогон остановиться
    GET  /api/runs/<id>/download    готовый .pptx
    GET  /api/status                готовность окружения (можно гасить кнопку)

Запуск примера:  python -m flask --app examples/flask_adapter run --port 8000
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from opercom.config import load_settings
from opercom.jobs import JobManager, iter_recent
from opercom.pipeline import OUTPUT_FILENAME
from opercom.preflight import is_ready, run_checks

#: run_id генерируется сервисом, но из URL приходит от клиента — сверяем формат,
#: чтобы никакой `../` не доехал до файловой системы.
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-\d{3}$")

PPTX_MIMETYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def create_app(settings=None) -> Flask:
    app = Flask(__name__)
    app.config["SETTINGS"] = settings or load_settings()
    # Один JobManager на процесс: он держит очередь и реестр прогонов в памяти.
    app.config["JOBS"] = JobManager(app.config["SETTINGS"])

    @app.get("/api/status")
    def api_status():
        settings = app.config["SETTINGS"]
        checks = run_checks(settings)
        active = app.config["JOBS"].active()
        return jsonify(
            {
                "ready": is_ready(checks),
                "checks": [check.as_dict() for check in checks],
                "data_source": settings.data_source,
                "template": str(settings.template_pptx),
                "active_run": active.id if active else None,
            }
        )

    @app.post("/api/runs")
    def api_create_run():
        """Собственно «нажатие кнопки»: ставит прогон в очередь и сразу отвечает."""
        jobs: JobManager = app.config["JOBS"]

        active = jobs.active()
        if active is not None:
            # Одновременный прогон только один — сообщаем явно, а не копим очередь.
            return jsonify({"error": "already_running", "id": active.id}), 409

        checks = run_checks(app.config["SETTINGS"])
        if not is_ready(checks):
            failed = [c.as_dict() for c in checks if c.blocking and not c.ok]
            return jsonify({"error": "preflight_failed", "checks": failed}), 422

        job = jobs.submit()
        return jsonify({"id": job.id, "status": job.status}), 202

    @app.get("/api/runs")
    def api_list_runs():
        return jsonify({"runs": iter_recent(app.config["JOBS"].list())})

    @app.get("/api/runs/<run_id>")
    def api_get_run(run_id: str):
        """Статус прогона. `log_offset` — сколько строк лога уже есть у клиента."""
        job = _lookup(app, run_id)
        if job is None:
            return jsonify({"error": "not_found"}), 404
        try:
            log_offset = max(0, int(request.args.get("log_offset", 0)))
        except ValueError:
            log_offset = 0
        return jsonify(job.as_dict(log_offset=log_offset))

    @app.post("/api/runs/<run_id>/cancel")
    def api_cancel_run(run_id: str):
        job = _lookup(app, run_id)
        if job is None:
            return jsonify({"error": "not_found"}), 404
        if not app.config["JOBS"].cancel(run_id):
            return jsonify({"error": "not_cancellable"}), 409
        return jsonify({"id": run_id, "status": "cancelling"}), 202

    @app.get("/api/runs/<run_id>/download")
    def api_download(run_id: str):
        job = _lookup(app, run_id)
        if job is None or job.output_path is None or not Path(job.output_path).exists():
            return jsonify({"error": "not_found"}), 404
        stamp = (job.finished_at or datetime.now()).strftime("%Y-%m-%d")
        return send_file(
            job.output_path,
            as_attachment=True,
            download_name=f"opercom_{stamp}_{OUTPUT_FILENAME}",
            mimetype=PPTX_MIMETYPE,
        )

    return app


def _lookup(app: Flask, run_id: str):
    if not RUN_ID_RE.match(run_id):
        return None
    return app.config["JOBS"].get(run_id)


app = create_app()
