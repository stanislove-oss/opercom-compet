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

#: Переменные окружения для подключения к оффлайн-базе (ячейка 1 ноутбука).
DB_ENV_VARS = ["HOST", "USER", "PASSWORD", "DB_NAME"]


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


def _check_app_package() -> Check:
    """Пакет `app` с подключением к БД и SQL-запросами.

    Его нет в репозитории намеренно: он содержит внутренние SQL-запросы и живёт
    в отдельном пакете компании. Без него вариант источника "db" не поедет.
    """
    found = importlib.util.find_spec("app") is not None
    return Check(
        name="Пакет app (MySQL + SQL-запросы)",
        ok=found,
        blocking=True,
        detail=(
            "доступен"
            if found
            else "не найден: ноутбук импортирует app.sql_oop.MySQL и app.sql_dict_connection. "
            "Положи пакет рядом с проектом или установи его в окружение"
        ),
    )


def _check_db_env() -> Check:
    missing = [name for name in DB_ENV_VARS if not os.getenv(name)]
    return Check(
        name="Credentials оффлайн-базы",
        ok=not missing,
        blocking=True,
        detail="заданы" if not missing else f"не заданы в .env: {', '.join(missing)}",
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
        checks.append(_check_app_package())
        checks.append(_check_db_env())
    else:
        checks.append(
            _check_path("Снимки данных (dummy_df)", settings.dummy_df_root, blocking=True, must_be_dir=True)
        )

    # Excel-файлы с сетевой шары читаются при любом источнике: это отдельная
    # ветка пайплайна (top advertisers, top brands nattv, X5 digital).
    checks.append(
        _check_path("Шара MMO (top advertisers, рейтинги)", settings.mmo_data_root, blocking=True, must_be_dir=True)
    )
    checks.append(
        _check_path("Шара digital (X5 DigitalInvestments)", settings.digital_data_root, blocking=True, must_be_dir=True)
    )

    return checks


def is_ready(checks: list[Check]) -> bool:
    """True, если ни одна блокирующая проверка не провалена."""
    return all(check.ok for check in checks if check.blocking)
