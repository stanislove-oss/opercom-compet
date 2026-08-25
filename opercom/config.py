"""Конфигурация сервиса. Всё, что раньше было хардкодом в ноутбуке, — здесь.

Значения читаются из переменных окружения (см. `.env.example`). Умолчания
совпадают с тем, что было зашито в ноутбуке, чтобы поведение не изменилось при
пустом окружении.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_NOTEBOOK = PROJECT_ROOT / "main_2.ipynb"

TEMPLATES_DIR = PROJECT_ROOT / "templates_pptx"


def _default_template() -> Path:
    """Шаблон презентации: точное имя, иначе единственный *_named.pptx рядом.

    Имя файла начинается с буквы «Х», и она бывает как кириллической, так и
    латинской «X» — на вид не отличить, а путь при этом не совпадает. Чтобы
    сборка не падала из-за омоглифа, точное имя — лишь первая попытка.
    """
    exact = TEMPLATES_DIR / "Х5_Оперком_март_v3_fin_named.pptx"
    if exact.is_file():
        return exact

    candidates = sorted(
        path for path in TEMPLATES_DIR.glob("*_named.pptx")
        if not path.name.startswith("~$")
    )
    return candidates[0] if candidates else exact


DEFAULT_TEMPLATE = _default_template()

# Пути из ноутбука (ячейка 39). На Linux-хосте это должны быть точки монтирования
# той же самой сетевой шары.
DEFAULT_MMO_DATA_ROOT = r"Z:\clients\!market_data\data_bases"
DEFAULT_DIGITAL_DATA_ROOT = r"Z:\clients\retail\food_retail\x5\data_bases"

DEFAULT_FIVE_DICT_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRHjJj5hSOWJgEWCgjBLCKVaL"
    "wmjJqX9BKTDw-LrDCGcuwp4bKHfaCjjHYLCmac83UiZadPkDLCP0Lk/pub"
    "?gid=1375455515&single=true&output=csv"
)


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw) if raw else default


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Настройки одного развёртывания сервиса."""

    notebook_path: Path = field(default_factory=lambda: _env_path("OPERCOM_NOTEBOOK", DEFAULT_NOTEBOOK))
    template_pptx: Path = field(default_factory=lambda: _env_path("OPERCOM_TEMPLATE_PPTX", DEFAULT_TEMPLATE))
    runs_root: Path = field(default_factory=lambda: _env_path("OPERCOM_RUNS_ROOT", PROJECT_ROOT / "runs"))

    #: "db" — MySQL + Google Sheets, "csv" — снимки из dummy_df/.
    data_source: str = field(default_factory=lambda: os.getenv("OPERCOM_DATA_SOURCE", "db"))

    mmo_data_root: str = field(default_factory=lambda: os.getenv("OPERCOM_MMO_DATA_ROOT", DEFAULT_MMO_DATA_ROOT))
    digital_data_root: str = field(
        default_factory=lambda: os.getenv("OPERCOM_DIGITAL_DATA_ROOT", DEFAULT_DIGITAL_DATA_ROOT)
    )
    dummy_df_root: Path = field(default_factory=lambda: _env_path("OPERCOM_DUMMY_DF_ROOT", PROJECT_ROOT / "dummy_df"))
    five_dict_url: str = field(default_factory=lambda: os.getenv("OPERCOM_FIVE_DICT_URL", DEFAULT_FIVE_DICT_URL))

    run_dev_cells: bool = field(default_factory=lambda: _env_flag("OPERCOM_RUN_DEV_CELLS"))

    #: Жёсткий потолок на один прогон, секунды. 0 — без ограничения.
    run_timeout_sec: int = field(default_factory=lambda: int(os.getenv("OPERCOM_RUN_TIMEOUT_SEC", "3600")))

    #: Сколько последних прогонов держать на диске. 0 — не чистить.
    keep_runs: int = field(default_factory=lambda: int(os.getenv("OPERCOM_KEEP_RUNS", "20")))

    def notebook_parameters(self, output_pptx: Path) -> dict[str, object]:
        """Значения, которые рантайм подставляет в ячейку с тегом `parameters`.

        Имена совпадают с именами переменных в этой ячейке ноутбука. Пути
        передаются как `Path` — ноутбук вызывает у них `.exists()`.
        """
        return {
            "TEMPLATE_PPTX": Path(self.template_pptx),
            "OUTPUT_PPTX": Path(output_pptx),
            # Корни сетевых шар остаются строками: find_data_file сам делает Path(),
            # а на Windows-хосте здесь лежит r"Z:\..." в исходном виде.
            "MMO_DATA_ROOT": self.mmo_data_root,
            "DIGITAL_DATA_ROOT": self.digital_data_root,
            "DUMMY_DF_ROOT": Path(self.dummy_df_root),
            "FIVE_DICT": self.five_dict_url,
        }


def load_settings() -> Settings:
    """Читает `.env` (если есть) и собирает настройки."""
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        # python-dotenv не обязателен: переменные могут прийти из окружения.
        pass
    return Settings()
