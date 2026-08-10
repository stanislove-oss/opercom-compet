#!/usr/bin/env python3
"""Проставляет теги ячейкам main_2.ipynb и внедряет ячейку параметров.

Скрипт идемпотентный: повторный запуск ничего не ломает. Правила привязаны не к
голым индексам, а к паре «индекс + отпечаток исходника», поэтому если ноутбук
изменился, скрипт честно ругнётся, а не проставит теги мимо.

    python scripts/tag_notebook.py            # проставить теги
    python scripts/tag_notebook.py --dry-run  # показать, что изменится
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opercom import tags as T  # noqa: E402

NOTEBOOK = Path(__file__).resolve().parent.parent / "main_2.ipynb"

PARAMETERS_CELL_SOURCE = '''\
# Ячейка параметров. Значения ниже — умолчания для ручного прогона в Jupyter.
# При запуске из веб-сервиса opercom.notebook_runner подставляет сюда фактические
# пути прогона (см. opercom/config.py :: Settings.notebook_parameters).
from pathlib import Path

PROJECT_ROOT = Path.cwd()

# Шаблон презентации и файл результата.
TEMPLATE_PPTX = PROJECT_ROOT / "templates_pptx" / "Х5_Оперком_март_v3_fin_named.pptx"
OUTPUT_PPTX = PROJECT_ROOT / "main_2_filled.pptx"

# Корни сетевых шар с исходными Excel-файлами.
MMO_DATA_ROOT = r"Z:\\clients\\!market_data\\data_bases"
DIGITAL_DATA_ROOT = r"Z:\\clients\\retail\\food_retail\\x5\\data_bases"

# Локальные снимки данных (используются только вариантом source:csv).
DUMMY_DF_ROOT = PROJECT_ROOT / "dummy_df"

# Google-таблица со словарём чистки.
FIVE_DICT = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRHjJj5hSOWJgEWCgjBLCKVaL"
    "wmjJqX9BKTDw-LrDCGcuwp4bKHfaCjjHYLCmac83UiZadPkDLCP0Lk/pub"
    "?gid=1375455515&single=true&output=csv"
)
'''

# (индекс в ИСХОДНОМ ноутбуке, фрагмент-отпечаток, тег, комментарий «почему»)
# Индексы указаны до внедрения ячейки параметров; скрипт учитывает сдвиг сам.
RULES: list[tuple[int, str, str, str]] = [
    (0, "from app.sql_oop import MySQL", T.RUN, "импорты"),
    (1, "load_dotenv", T.RUN, "credentials"),
    (2, "CONSIDER_BRANDS", T.RUN, "константы брендов"),
    (3, "message_type_ls", T.RUN, "маппинг типов сообщения"),
    (4, "OPERCOM_BRANDS", T.RUN, "константы брендов"),
    (5, "sorted(tv_norm.brand_main", T.SKIP, "обращается к tv_norm до его создания — упадёт"),
    (6, "sorted(ooh_norm.brand_main", T.SKIP, "то же самое для ooh_norm"),
    (7, "db = MySQL(", T.SOURCE_DB, "боевой источник: MySQL + Google Sheets"),
    (8, "tv_adex.to_csv(", T.DEV, "дамп снимков данных на диск"),
    (9, "X5_automatization_dictionary_upd", T.SOURCE_CSV, "словарь из локального CSV"),
    (10, "tv_adex = pd.read_csv", T.SOURCE_CSV, "данные из локальных CSV"),
    (11, "tv_adex", T.SKIP, "просмотр датафрейма"),
    (13, "tv_nat_rate['media_type']", T.RUN, "приведение колонок рейтингов"),
    (15, "select_dtypes(['str', 'object'])", T.RUN, "нижний регистр"),
    (16, "tv_adex", T.SKIP, "просмотр"),
    (17, "tv_nat_rate", T.SKIP, "просмотр"),
    (18, "tv_reg_rate", T.SKIP, "просмотр"),
    (19, "link_dict", T.SKIP, "просмотр"),
    (20, "from functions.clean_brand_names", T.RUN, "импорт"),
    (21, "def normalizer", T.RUN, "нормализация"),
    (22, "tv_norm = normalizer", T.RUN, "нормализация всех источников"),
    (23, "ooh_norm['media_type_detail']", T.RUN, "проставление media_type_detail"),
    (24, "tv_rate_nat_norm.rename", T.RUN, "подготовка рейтингов"),
    (25, "set(tv_rate_nat_norm.brand_main", T.SKIP, "просмотр множества брендов"),
    (26, "tv_rate_nat_norm.head", T.SKIP, "просмотр"),
    (27, "tv_norm.head", T.SKIP, "просмотр"),
    (28, "tv_norm[(tv_norm['date'] == '2026-04-01')]", T.SKIP, "разовая выборка топ-10"),
    (30, "tv_norm[(tv_norm['date'] == '2026-04-01')]", T.SKIP, "разовая выборка топ-5"),
    (32, "define_cur_year", T.RUN, "определение отчётных периодов"),
    (33, "last_year_adex, cur_year_adex, cur_month_adex", T.SKIP, "просмотр"),
    (34, "cur_month_adex -= 1", T.RUN, "ручная поправка периода adex — часть пайплайна"),
    (35, "last_year_rate, cur_year_rate, cur_month_rate", T.SKIP, "просмотр"),
    (38, "import functions.read_digital_adv", T.RUN, "импорт"),
    (39, "TOP_ADVERTISER_PATTERN", T.RUN, "пути и маски файлов"),
    (40, "top_adveriser_investment_ytd, meta", T.RUN, "чтение top advertisers YTD"),
    (42, "top_adveriser_investment_month, meta", T.RUN, "чтение top advertisers month"),
    (43, "top_adveriser_investment_ytd_for_merge", T.RUN, "нижний регистр + копии"),
    (45, "offline_adex_df = pd.read_excel", T.RUN, "чтение offline adex"),
    (46, "tv_norm.head", T.SKIP, "просмотр"),
    (47, "offline_adex_df.rename", T.RUN, "нормализация offline adex"),
    (48, "offline_adex_df", T.SKIP, "просмотр"),
    (50, "tvr_brands_df = pd.read_excel", T.RUN, "чтение рейтингов по брендам"),
    (52, "digital_adex = pd.read_excel", T.RUN, "чтение digital-затрат"),
    (53, "digital_adex", T.SKIP, "просмотр"),
    (55, "cur_month_adex_mmo", T.RUN, "определение месяца по данным MMO"),
    (56, "cur_month_rate_mmo", T.RUN, "определение месяца по рейтингам MMO"),
    (58, "from functions.build_tables import *", T.RUN, "импорт"),
    (60, "dataframes = {}", T.RUN, "инициализация словаря результатов"),
    (61, "df_ytd_slide", T.RUN, "подготовка витрин топ-рекламодателей"),
    (96, "all_brands_order", T.RUN, "общий порядок брендов"),
    (120, "tv_rate_reg_norm.head", T.SKIP, "просмотр"),
    (123, "test_df", T.SKIP, "разбор правки на 14 слайде"),
    (125, "dataframes['reg_duration_table']", T.SKIP, "повторный просмотр"),
    (128, "build_table(", T.SKIP, "черновой прогон build_table без присваивания"),
    (141, "offline_brands_order", T.RUN, "общий порядок брендов (offline)"),
    (157, "nat_tv_20", T.RUN, "слайд 20, подготовка"),
    (186, "delivery_brands_order", T.RUN, "общий порядок брендов (delivery)"),
    (201, "nat_tv_29", T.RUN, "слайд 29, подготовка"),
    (270, "STACKED_VALUE_AS_PERCENT_LABELS", T.RUN, "настройки подписей"),
    (271, "DURATION_CHART_KEYS", T.RUN, "настройки графиков длительности"),
    (272, "DURATION_TABLE_KEYS", T.RUN, "настройки таблиц длительности"),
    (276, "n = len(dataframes)", T.RUN, "счётчик датафреймов, используется ниже"),
    (277, "lower_case_idx_col", T.RUN, "исключения регистра"),
    (278, "CHART_SPECS", T.RUN, "карта датафрейм -> график"),
    (279, "no_round_tables", T.RUN, "какие таблицы не округлять"),
    (280, "def _is_month_period_label", T.RUN, "общая нормализация всех датафреймов"),
    (284, "import functions.build_presentations", T.RUN, "импорт"),
    (285, "from functions.build_presentations import *", T.RUN, "импорт pptx"),
    (287, "_BRAND_HEX", T.RUN, "цвета брендов"),
    (288, "color_dict.update", T.RUN, "цвета медиа-микса и длительностей"),
    (290, "TABLE_TEXT_SIZE", T.RUN, "размеры шрифтов подписей"),
    (291, "Y_AXIS_MARGIN_RULES", T.RUN, "отступы оси Y"),
    (292, "xl_types_dict", T.RUN, "типы графиков"),
    (293, "prs = pptx.Presentation", T.RUN, "открытие шаблона"),
    (294, "TRP_AXIS_GROUP_SLIDES", T.RUN, "общая ось Y для TRP-слайдов"),
    (296, "def is_complex_chart", T.RUN, "детектор сложных графиков"),
    (297, "update_chart_data_by_shape_name", T.RUN, "главный цикл заливки графиков"),
    (298, "prs.save", T.RUN, "промежуточное сохранение"),
    (300, "fill_duration_table_from_view_v2", T.RUN, "нативные таблицы 13, 14, 23, 25, 31"),
    (302, "def fill_tables_by_specs", T.RUN, "хелперы нативных таблиц"),
    (304, "filled_delta_tables", T.RUN, "таблицы дельт"),
    (306, "MINI_TABLE_SPECS_6_7", T.RUN, "мини-таблицы слайдов 6-7"),
    (307, "TABLE_SPECS_33_42", T.RUN, "карта таблиц 33-42"),
    (308, "filled_tables_33_42", T.RUN, "заливка таблиц 33-42"),
    (311, "def calc_delta", T.RUN, "расчёт дельт для тегов"),
    (312, "TAG_VALUES", T.RUN, "подстановка текстовых тегов"),
    (313, "prs.save", T.RUN, "финальное сохранение"),
    (314, "baseline_dataframes.pkl", T.DEV, "сверка с эталонным прогоном"),
    (315, "len(baseline)", T.DEV, "сверка с эталонным прогоном"),
]

# Точечные правки исходников ячеек: хардкод -> переменные ячейки параметров.
# (индекс, что заменить, на что заменить, обязательна ли замена)
SOURCE_PATCHES: list[tuple[int, str, str, bool]] = [
    (
        7,
        "FIVE_DICT = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRHjJj5hSOWJgEWCgjBLCKVaLwmjJqX9BKTDw-LrDCGcuwp4bKHfaCjjHYLCmac83UiZadPkDLCP0Lk/pub?gid=1375455515&single=true&output=csv'\n",
        "# FIVE_DICT приходит из ячейки параметров.\n",
        True,
    ),
    (
        9,
        'link_dict = pd.read_csv(r"dummy_df\\X5_automatization_dictionary_upd - filter_id (2).csv", low_memory = False)',
        'link_dict = pd.read_csv(DUMMY_DF_ROOT / "X5_automatization_dictionary_upd - filter_id (2).csv", low_memory = False)',
        True,
    ),
    (
        8,
        """tv_adex.to_csv('dummy_df/tv_adex.csv', index=False)
radio_adex.to_csv('dummy_df/radio_adex.csv', index=False)
ooh_adex.to_csv('dummy_df/ooh_adex.csv', index=False)
press_adex.to_csv('dummy_df/press_adex.csv', index=False)
tv_nat_rate.to_csv('dummy_df/tv_nat_rate.csv', index=False)
tv_reg_rate.to_csv('dummy_df/tv_reg_rate.csv', index=False)""",
        """DUMMY_DF_ROOT.mkdir(parents=True, exist_ok=True)

tv_adex.to_csv(DUMMY_DF_ROOT / 'tv_adex.csv', index=False)
radio_adex.to_csv(DUMMY_DF_ROOT / 'radio_adex.csv', index=False)
ooh_adex.to_csv(DUMMY_DF_ROOT / 'ooh_adex.csv', index=False)
press_adex.to_csv(DUMMY_DF_ROOT / 'press_adex.csv', index=False)
tv_nat_rate.to_csv(DUMMY_DF_ROOT / 'tv_nat_rate.csv', index=False)
tv_reg_rate.to_csv(DUMMY_DF_ROOT / 'tv_reg_rate.csv', index=False)""",
        True,
    ),
    (
        10,
        """tv_adex = pd.read_csv(r'dummy_df/tv_adex.csv')
radio_adex = pd.read_csv(r'dummy_df/radio_adex.csv')
ooh_adex = pd.read_csv(r'dummy_df/ooh_adex.csv')
press_adex = pd.read_csv(r'dummy_df/press_adex.csv')
tv_nat_rate = pd.read_csv(r'dummy_df/tv_nat_rate.csv')
tv_reg_rate = pd.read_csv(r'dummy_df/tv_reg_rate.csv')""",
        """tv_adex = pd.read_csv(DUMMY_DF_ROOT / 'tv_adex.csv')
radio_adex = pd.read_csv(DUMMY_DF_ROOT / 'radio_adex.csv')
ooh_adex = pd.read_csv(DUMMY_DF_ROOT / 'ooh_adex.csv')
press_adex = pd.read_csv(DUMMY_DF_ROOT / 'press_adex.csv')
tv_nat_rate = pd.read_csv(DUMMY_DF_ROOT / 'tv_nat_rate.csv')
tv_reg_rate = pd.read_csv(DUMMY_DF_ROOT / 'tv_reg_rate.csv')""",
        True,
    ),
    (
        39,
        'MMO_DATA_ROOT = r"Z:\\clients\\!market_data\\data_bases"\nDIGITAL_DATA_ROOT = r"Z:\\clients\\retail\\food_retail\\x5\\data_bases"\n',
        "# MMO_DATA_ROOT и DIGITAL_DATA_ROOT приходят из ячейки параметров.\n",
        True,
    ),
    (
        293,
        "prs = pptx.Presentation(r'Х5_Оперком_март_v3_fin_named.pptx')",
        "prs = pptx.Presentation(str(TEMPLATE_PPTX))",
        True,
    ),
    (298, "prs.save(r'main_2_filled.pptx')", "prs.save(str(OUTPUT_PPTX))", True),
    (300, "prs.save('main_2_filled.pptx')", "prs.save(str(OUTPUT_PPTX))", True),
    (313, "prs.save(r'main_2_filled.pptx')", "prs.save(str(OUTPUT_PPTX))", True),
]

# В ячейках 304/306/308 повторяется один и тот же блок «подними prs, если его нет».
# Он переопределял OUTPUT_PPTX своим хардкодом — убираем переопределение и
# ссылаемся на шаблон из параметров.
PRS_FALLBACK_OLD = """OUTPUT_PPTX = Path('main_2_filled.pptx')

if 'prs' not in globals():
    if OUTPUT_PPTX.exists():
        prs = pptx.Presentation(str(OUTPUT_PPTX))
    else:
        template_candidates = [p for p in Path('.').glob('*_named.pptx') if not p.name.startswith('~$')]
        if not template_candidates:
            raise FileNotFoundError('No existing main_2_filled.pptx or *_named.pptx template found')
        prs = pptx.Presentation(str(template_candidates[0]))"""

PRS_FALLBACK_NEW = """# OUTPUT_PPTX и TEMPLATE_PPTX приходят из ячейки параметров.
if 'prs' not in globals():
    prs = pptx.Presentation(str(OUTPUT_PPTX if Path(OUTPUT_PPTX).exists() else TEMPLATE_PPTX))"""

PRS_FALLBACK_CELLS = (304, 306, 308)


def _source_text(cell: dict) -> str:
    return "".join(cell.get("source", []))


def _set_source(cell: dict, text: str) -> None:
    lines = text.splitlines(keepends=True)
    cell["source"] = lines


def _set_tag(cell: dict, tag: str) -> bool:
    """Ставит управляющий тег, снимая ранее проставленные. True если изменилось."""
    metadata = cell.setdefault("metadata", {})
    existing = [t for t in metadata.get("tags", []) or [] if t not in T.KNOWN_TAGS]
    new_tags = [tag, *existing]
    if metadata.get("tags") == new_tags:
        return False
    metadata["tags"] = new_tags
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    notebook = json.loads(args.notebook.read_text(encoding="utf-8"))
    cells = notebook["cells"]

    has_parameters = any(T.PARAMETERS in (c.get("metadata", {}).get("tags") or []) for c in cells)
    offset = 1 if has_parameters else 0

    changes: list[str] = []
    problems: list[str] = []

    # 1. Точечные правки исходников.
    for index, old, new, required in SOURCE_PATCHES:
        cell = cells[index + offset]
        text = _source_text(cell)
        if old in text:
            _set_source(cell, text.replace(old, new))
            changes.append(f"ячейка {index}: правка исходника ({old.strip().splitlines()[0][:50]}…)")
        elif required and new.strip() not in text:
            problems.append(f"ячейка {index}: не найден фрагмент для замены: {old.strip()[:70]!r}")

    for index in PRS_FALLBACK_CELLS:
        cell = cells[index + offset]
        text = _source_text(cell)
        if PRS_FALLBACK_OLD in text:
            _set_source(cell, text.replace(PRS_FALLBACK_OLD, PRS_FALLBACK_NEW))
            changes.append(f"ячейка {index}: убрано переопределение OUTPUT_PPTX")
        elif PRS_FALLBACK_NEW not in text:
            problems.append(f"ячейка {index}: не найден блок fallback-инициализации prs")

    # 2. Теги.
    for index, fingerprint, tag, why in RULES:
        cell = cells[index + offset]
        if cell.get("cell_type") != "code":
            problems.append(f"ячейка {index}: ожидалась code-ячейка, найдена {cell.get('cell_type')}")
            continue
        text = _source_text(cell)
        if fingerprint not in text:
            problems.append(
                f"ячейка {index}: отпечаток {fingerprint!r} не найден — "
                f"ноутбук изменился, правило устарело"
            )
            continue
        if _set_tag(cell, tag):
            changes.append(f"ячейка {index}: тег {tag} ({why})")

    # 3. Все остальные code-ячейки без тега — это `dataframes[...] = ...` из
    #    основной части. Они боевые, помечаем RUN, а «голые» просмотры (ячейка,
    #    состоящая только из выражения) — SKIP.
    for index, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue
        if T.cell_tag(cell) is not None:
            continue
        text = _source_text(cell)
        if not text.strip():
            continue
        tag = T.RUN if ("=" in text or "import " in text) else T.SKIP
        if _set_tag(cell, tag):
            changes.append(f"ячейка {index - offset}: тег {tag} (по умолчанию)")

    # 4. Ячейка параметров — самой первой.
    if not has_parameters:
        parameters_cell = {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {"tags": [T.PARAMETERS]},
            "outputs": [],
            "source": PARAMETERS_CELL_SOURCE.splitlines(keepends=True),
        }
        cells.insert(0, parameters_cell)
        changes.append("добавлена ячейка параметров в начало ноутбука")

    if problems:
        print("Проблемы (ничего не записано):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if not changes:
        print("Изменений нет — ноутбук уже размечен.")
        return 0

    for change in changes:
        print(f"  + {change}")

    if args.dry_run:
        print(f"\n--dry-run: {len(changes)} изменений не записано.")
        return 0

    args.notebook.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nЗаписано {len(changes)} изменений в {args.notebook}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
