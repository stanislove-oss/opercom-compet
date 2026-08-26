"""Проверка готовности окружения до запуска прогона.

Смысл — не дать кнопке запустить сорокаминутный прогон, который упадёт на
последнем шаге из-за отсутствующего шаблона или недоступной сетевой шары.
Веб-интерфейс показывает результат этих проверок рядом с кнопкой и блокирует её,
если есть блокирующая проблема.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

from .config import Settings
from .notebook_runner import describe_plan

MIN_PYTHON = (3, 12)

#: Пакеты, без которых ноутбук не стартует.
REQUIRED_PACKAGES = ["pandas", "pptx", "lxml", "openpyxl", "numpy", "dotenv"]

#: Клиент под каждый движок базы. Ставится только нужный.
DB_CLIENT_PACKAGES = {"clickhouse": "clickhouse_connect", "mssql": "pyodbc"}


@dataclass
class Check:
    """Результат одной проверки."""

    name: str
    ok: bool
    #: Блокирующая проблема запрещает запуск; неблокирующая — только предупреждает.
    blocking: bool
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


def _check_python() -> Check:
    ok = sys.version_info >= MIN_PYTHON
    return Check(
        name="Версия Python",
        ok=ok,
        blocking=True,
        detail=(
            f"{sys.version.split()[0]}"
            if ok
            else f"нужен >= {'.'.join(map(str, MIN_PYTHON))}, запущен {sys.version.split()[0]}: "
            f"ноутбук использует вложенные кавычки в f-строках (PEP 701)"
        ),
    )


def _check_packages() -> list[Check]:
    checks = []
    for package in REQUIRED_PACKAGES:
        found = importlib.util.find_spec(package) is not None
        checks.append(
            Check(
                name=f"Пакет {package}",
                ok=found,
                blocking=True,
                detail="установлен" if found else "не установлен (см. requirements.txt)",
            )
        )
    return checks


def _db_engine() -> str:
    """Какой движок базы выбран. Читается тем же кодом, что и подключение."""
    from functions.db import _env, load_env_file

    load_env_file()
    engine = (_env("DB_ENGINE", default="clickhouse") or "clickhouse").strip().lower()
    return "mssql" if engine in ("mssql", "sqlserver", "mysql") else "clickhouse"


def _check_db_client(engine: str) -> Check:
    """Драйвер под выбранный движок."""
    package = DB_CLIENT_PACKAGES[engine]
    found = importlib.util.find_spec(package) is not None
    hint = (
        "pip install clickhouse-connect" if engine == "clickhouse" else "pip install pyodbc"
    )
    return Check(
        name=f"Драйвер базы ({package})",
        ok=found,
        blocking=True,
        detail="установлен" if found else f"не установлен: {hint}",
    )


def _check_db_settings(engine: str) -> list[Check]:
    """Что видно в окружении для подключения — без паролей."""
    from functions.db import describe_environment

    if engine == "mssql":
        from functions.db import _env

        missing = [
            name
            for name, value in (
                ("host", _env("MSSQL_HOST", "SQL_SERVER", "HOST")),
                ("user", _env("MSSQL_USER", "SQL_USERNAME", "DB_USER", "USER")),
                ("database", _env("MSSQL_DATABASE", "SQL_DATABASE", "DB_NAME")),
            )
            if not value
        ]
        return [
            Check(
                name="Настройки SQL Server",
                ok=not missing,
                blocking=True,
                detail="заданы" if not missing else f"не заданы в .env: {', '.join(missing)}",
            )
        ]

    report = describe_environment()
    host = report.get("CLICKHOUSE_HOST")
    checks = [
        Check(
            name="Адрес ClickHouse",
            ok=bool(host),
            blocking=True,
            detail=(
                f"{host}:{report.get('CLICKHOUSE_PORT')}, база {report.get('CLICKHOUSE_DATABASE')}"
                if host
                else "не задан CLICKHOUSE_HOST — заполни .env (cp .env.example .env)"
            ),
        ),
        Check(
            name="Пароль ClickHouse",
            ok=bool(report.get("пароль задан")),
            blocking=False,
            detail="задан" if report.get("пароль задан") else "не задан — если база без пароля, это нормально",
        ),
    ]

    for warning in report.get("предупреждения", []):
        checks.append(Check(name="Окружение базы", ok=False, blocking=False, detail=warning))

    return checks


def _check_classification() -> Check:
    """Все ли фильтры отбора получат свою колонку.

    Блокирующая проверка намеренно. Пропущенный фильтр не роняет сборку — он
    молча пропускает в отчёт лишние строки, и цифры просто становятся больше
    правды. В Jupyter это видно по выводу normalizer, а кнопку в вебе никто
    не читает, поэтому здесь нужен запрет, а не предупреждение.
    """
    try:
        from app.sql_dict_connection import describe_classification, unresolved_filters
    except ImportError as error:  # pragma: no cover — набор запросов всегда на месте
        return Check("Классификация", False, True, f"не читается: {error}")

    missing = unresolved_filters()
    if not missing:
        return Check("Классификация", True, True, "все фильтры отбора получат колонку")

    return Check(
        name="Классификация",
        ok=False,
        blocking=True,
        detail=(
            f"фильтры без колонки: {', '.join(missing)} — они не применятся, "
            f"и суммы станут больше прежних.\n" + describe_classification()
        ),
    )


def _check_path(name: str, path: str | Path, *, blocking: bool, must_be_dir: bool) -> Check:
    candidate = Path(path)
    exists = candidate.is_dir() if must_be_dir else candidate.is_file()
    return Check(
        name=name,
        ok=exists,
        blocking=blocking,
        detail=str(candidate) if exists else f"не найден: {candidate}",
    )


def _check_notebook_plan(settings: Settings) -> Check:
    try:
        plan = list(describe_plan(settings.notebook_path, data_source=settings.data_source))
    except FileNotFoundError:
        return Check("Разметка ноутбука", False, True, f"ноутбук не найден: {settings.notebook_path}")
    except ValueError as exc:
        return Check("Разметка ноутбука", False, True, str(exc))

    to_run = sum(1 for item in plan if item.should_run)
    return Check(
        name="Разметка ноутбука",
        ok=to_run > 0,
        blocking=True,
        detail=(
            f"{to_run} ячеек к исполнению, {len(plan) - to_run} пропускается"
            if to_run
            else "не выбрано ни одной ячейки — проверь теги"
        ),
    )


def run_checks(settings: Settings) -> list[Check]:
    """Полный список проверок для текущей конфигурации."""
    checks: list[Check] = [_check_python()]
    checks.extend(_check_packages())
    checks.append(_check_notebook_plan(settings))
    checks.append(
        _check_path("Шаблон презентации", settings.template_pptx, blocking=True, must_be_dir=False)
    )

    if settings.data_source == "db":
        engine = _db_engine()
        checks.append(
            Check(
                name="Движок базы (DB_ENGINE)",
                ok=True,
                blocking=False,
                detail=f"{engine}" + (" — прежняя база, для сверки и отката" if engine == "mssql" else ""),
            )
        )
        checks.append(_check_db_client(engine))
        checks.extend(_check_db_settings(engine))
        checks.append(_check_classification())
    else:
        checks.append(
            _check_path("Снимки данных (dummy_df)", settings.dummy_df_root, blocking=True, must_be_dir=True)
        )

    # Excel с сетевой шары нужен при любом источнике: top_advertisers и
    # top_brands_nattv в базу не переезжали.
    checks.append(
        _check_path("Шара MMO (top advertisers, рейтинги)", settings.mmo_data_root,
                    blocking=True, must_be_dir=True)
    )
    checks.append(_check_digital_source(settings))

    return checks


def _digital_from_database() -> bool:
    """Придёт ли диджитал из базы. Решает то же, что и ноутбук.

    Ноутбук смотрит на набор запросов, а не на DB_ENGINE, — здесь так же,
    иначе проверка и прогон разошлись бы в понимании того, что нужно.
    """
    if os.getenv("DIGITAL_XLSX", "").strip():
        return False
    try:
        from app.queries import queries_for

        return "DIGITAL_SQL" in queries_for(_db_engine()).names
    except Exception:  # noqa: BLE001 - набор запросов не обязан быть импортируемым
        return False


def _check_digital_source(settings: Settings) -> Check:
    """Диджитал: из базы или из Excel — и требовать надо только то, что нужно.

    Раньше шара проверялась всегда и блокировала запуск. После переезда
    диджитала в ClickHouse она нужна только для запасного пути, и блокировать
    прогон из-за недоступной шары, к которой никто не пойдёт, — значит
    не пускать на ровном месте.
    """
    if _digital_from_database():
        return Check("Диджитал", True, True, "из базы (other_media_x5_v1)")

    explicit = os.getenv("DIGITAL_XLSX", "").strip()
    if explicit:
        return _check_path("Диджитал (файл)", explicit, blocking=True, must_be_dir=False)

    return _check_path("Диджитал (шара X5_DigitalInvestments)", settings.digital_data_root,
                       blocking=True, must_be_dir=True)


def is_ready(checks: list[Check]) -> bool:
    """True, если ни одна блокирующая проверка не провалена."""
    return all(check.ok for check in checks if check.blocking)
