"""
Запросы к ClickHouse, база `mediascope_x5_big_v22`.

Прежние запросы к SQL Server лежат рядом, в app/sql_dict_connection_mssql.py,
и остаются рабочими: DB_ENGINE=mssql возвращает сборку на старую базу.

Написаны по схеме, снятой scripts/dump_schema.py (reports/clickhouse_schema.md).
База та же, что у чижика: проект X5, витрина одна.

ЧТО ИЗМЕНИЛОСЬ ПО СРАВНЕНИЮ С SQL SERVER
----------------------------------------
1. Справочники растворились в таблицах.
   Было: media_tv_costs + LEFT JOIN к adex_regions_dict, adex_company_dict_tv,
   adex_ad_dict_list_tv, adex_ad_type_dict_tv, tv_index_ad_type_dict,
   tv_index_region_dict.
   Стало: regionName, netName, companyName, adStandardDuration, adTypeName
   лежат прямо в таблице. JOIN-ов не осталось ни одного.

2. Четыре таблицы затрат стали одной.
   media_tv_costs / media_radio_costs / media_outdoor_costs /
   media_press_costs -> media_costs_union, медиа различается колонкой
   media_type (см. COST_MEDIA_TYPES).

3. Рейтинги лежат «вширь»: колонки prj_name нет, вместо неё колонка на
   каждую аудиторию. Прежний фильтр prj_name = 'ALL_18+' превратился
   в выбор колонок:

       nat_tv / big_tv          reg_tv
       RtgPer      -> `RtgPer_ALL_18+`      RtgPer_w    -> `RtgPer_w_ALL_18+`
       StandRtgPer -> `StandRtgPer_ALL_18+` RtgPer      -> `RtgPer_ALL_18+`
                                            StandRtgPer -> `StandRtgPer_ALL_18+`

   Взвешенный рейтинг есть только у reg_tv — как и раньше: прежний запрос
   брал RtgPer_w тоже только у регионального ТВ. Имя с плюсом обязательно
   в обратных кавычках.

4. nat_tv_simple / big_tv_simple / reg_tv_simple стали nat_tv / big_tv / reg_tv.

5. Появились колонки, которых не было в SQL Server: estat, cleaning_flag
   и media_key_id. Про первые две — у ESTAT_FILTER и CLEANING_FILTER,
   про третью — у KEY_COLUMN.

ЛОВУШКА РЕГИСТРА
----------------
В базе значения записаны прописными. В SQL Server сравнение регистр не
различало, здесь различает: `adTypeName = 'ролик'` вернёт ноль строк и не
упадёт. Поэтому везде lowerUTF8(...) — именно UTF-8-вариант, обычный LOWER
кириллицу не трогает.

Проверка, ничего не выгружая:
    python scripts/check_clickhouse.py --queries app.sql_dict_connection
    python scripts/verify_queries.py        # прогон на встроенном ClickHouse
"""

import os

from functions.db import load_env_file


def _env(name, default):
    """Значение из .env, если задано. Иначе — то, что в коде."""
    load_env_file()
    return (os.getenv(name) or "").strip() or default


# ---------------------------------------------------------------------------
# Таблицы
# ---------------------------------------------------------------------------

#: Затраты по всем медиа. Имя во множественном числе: media_cost*s*_union.
#:
#: ПРО ВЫБОР ВИТРИНЫ. Замерено в соседнем проекте на той же базе
#: (chizhik-compet, scripts/check_last_month.py, август 2026): затраты в v22
#: заканчиваются маем 2026-го — строк за июнь и дальше там просто нет,
#: а в v23 они есть. Рейтинги при этом брать из v23 нельзя: у reg_tv там
#: две колонки рейтингов вместо пятидесяти двух, и нужного
#: RtgPer_w_ALL_18+ нет вовсе.
#:
#: Поэтому база по умолчанию — v22 (оттуда рейтинги), а таблица затрат
#: указывается вместе со своей базой. Проверить, что где лежит:
#:     python scripts/dump_schema.py --list
COST_TABLE = _env("COST_TABLE", "mediascope_x5_big_v23.media_costs_union")

#: Национальное ТВ. Прежние nat_tv_simple и big_tv_simple.
NAT_TV_TABLE = _env("NAT_TV_TABLE", "nat_tv")
BIG_TV_TABLE = _env("BIG_TV_TABLE", "big_tv")

#: Региональное ТВ. Прежняя reg_tv_simple.
REG_TV_TABLE = _env("REG_TV_TABLE", "reg_tv")

#: Коды медиа в media_costs_union.media_type. Проверено в соседнем проекте
#: на этой же базе: TV, OD, RA, PR — других значений в таблице нет.
COST_MEDIA_TYPES = {"tv": "TV", "radio": "RA", "outdoor": "OD", "press": "PR"}

#: Аудитория отчёта — прежний фильтр prj_name = 'ALL_18+'.
#: Плюс в имени обязывает брать колонку в обратные кавычки.
AUDIENCE = "ALL_18+"

#: С какой даты выгружаем — как в прежних запросах.
PERIOD_FROM = "2024-01-01"

#: Национальное ТВ до конца 2024-го лежит в nat_tv, с 2025-го — в big_tv.
#: Границы взяты из прежнего запроса и намеренно не сдвинуты.
NAT_TV_PERIOD = ("2024-01-01", "2024-12-31")
BIG_TV_FROM = "2025-01-01"


# ---------------------------------------------------------------------------
# Классификация: из базы, а не из Google-таблицы
# ---------------------------------------------------------------------------
# Раньше поля классификации приходили только из справочника, и выгрузка
# мёржилась с ним по ключу. Теперь они есть в самих таблицах, и справочник
# не нужен: DICTIONARY_SOURCE=clickhouse (по умолчанию) берёт их из базы.
#
# Часть полей лежит под осмысленными именами, часть — под category_N.
# Осмысленных имён у вторых в таблицах нет, но есть в представлениях
# (reg_tv_weekly_view и подобные): там те же колонки уже переименованы,
# и соответствие читается из определения представления, а не угадывается:
#
#     python scripts/check_categories.py
#     python scripts/check_categories.py --values     # ещё и значения колонок
KEY_COLUMN = "media_key_id"

DICTIONARY_SOURCE = _env("DICTIONARY_SOURCE", "clickhouse").strip().lower()
DICTIONARY_FROM_DB = DICTIONARY_SOURCE != "sheet"

#: Поля справочника, которые в таблицах лежат под своими именами.
NAMED_DICTIONARY_COLUMNS = (
    ("brand_main", "brand_main"),
    ("lowerUTF8(advertiser_main)", "advertiser_main"),
    ("lowerUTF8(advertiser_type)", "advertiser_type"),
)

#: Поля справочника, лежащие под category_N. Соответствие снято с определений
#: представлений в соседнем проекте на этой же базе и подтверждено значениями:
#:     category_4 -> YES / NO                    (retail_category)
#:     category_7 -> ЦЕНОВОЕ ПРОМО / СТМ / …     (message_type)
#:     category_5 -> ОФФЛАЙН / ДОСТАВКА / …      (delivery)
#:
#: competitor так не проверялся: в чижике это поле не использовалось. Номер
#: колонки задаётся настройкой, чтобы подставить его без правки кода:
#:     COMPETITOR_COLUMN=category_3
#: Найти номер:  python scripts/check_categories.py
#:
#: lowerUTF8 обязателен: в базе значения прописными, а отчёт сравнивает
#: со строчными — иначе не найдётся ни одной строки, и отчёт получится
#: пустым, не упав.
CATEGORY_COLUMNS = {
    "retail_category": _env("RETAIL_CATEGORY_COLUMN", "category_4"),
    "message_type": _env("MESSAGE_TYPE_COLUMN", "category_7"),
    "delivery": _env("DELIVERY_COLUMN", "category_5"),
    "competitor": _env("COMPETITOR_COLUMN", ""),
}

#: Чего в базе нет вовсе — ни колонкой, ни в представлениях: include_exclude.
#: В отчёте по нему стоял фильтр `== 'include'` — ручные исключения из
#: Google-таблицы. Заменить его нечем, кроме чистки на стороне базы:
#:     INCLUDE_EXCLUDE_VIA=cleaning_flag   строки с cleaning_flag = 1 считаем include
#:     INCLUDE_EXCLUDE_VIA=               (по умолчанию) фильтра нет вовсе
#:
#: Без фильтра суммы станут больше прежних — ровно на те строки, которые
#: раньше вычёркивали руками. Насколько именно, покажет сверка:
#:     python scripts/compare_engines.py --queries TV_SQL
INCLUDE_EXCLUDE_VIA = _env("INCLUDE_EXCLUDE_VIA", "").strip().lower()


def dictionary_columns():
    """Пары (выражение, имя) с полями классификации — то, что раньше давал мёрж.

    Список одинаков для затрат и для рейтингов: и brand_main, и category_N
    лежат во всех четырёх таблицах.
    """
    if not DICTIONARY_FROM_DB:
        return ()

    columns = list(NAMED_DICTIONARY_COLUMNS)
    for alias, column in CATEGORY_COLUMNS.items():
        if column:
            columns.append((f"lowerUTF8({column})", alias))

    if INCLUDE_EXCLUDE_VIA == "cleaning_flag":
        # Приводим к тем же значениям, которые отчёт ждёт от справочника,
        # чтобы фильтр в ноутбуке остался прежним.
        columns.append(("if(cleaning_flag = 1, 'include', '!exclude')", "include_exclude"))

    return tuple(columns)


#: Поля, по которым отчёт отбирает строки (normalizer). Если поля нет в
#: выгрузке, соответствующий фильтр не применяется, и в отчёт попадает лишнее.
REPORT_FILTERS = ("include_exclude", "competitor", "advertiser_type", "retail_category")


def unresolved_filters():
    """Фильтры отбора, для которых в выгрузке не будет колонки.

    Пусто — отбор полностью соответствует прежнему. Непусто — суммы станут
    больше прежних ровно на те строки, которые эти фильтры отсекали.
    """
    if not DICTIONARY_FROM_DB:
        return ()

    available = {alias for _, alias in dictionary_columns()}
    return tuple(name for name in REPORT_FILTERS if name not in available)


def describe_classification():
    """Человекочитаемая сводка: откуда берётся классификация и чего не хватает."""
    if not DICTIONARY_FROM_DB:
        return "Классификация: из Google-таблицы (DICTIONARY_SOURCE=sheet)."

    lines = ["Классификация: из базы."]
    for alias, column in CATEGORY_COLUMNS.items():
        lines.append(f"  {alias:<16} -> {column or 'НЕ ЗАДАНО'}")

    missing = unresolved_filters()
    if missing:
        lines.append("")
        lines.append(f"  ФИЛЬТРЫ БЕЗ КОЛОНКИ: {', '.join(missing)}")
        lines.append("  Эти фильтры не применятся, и суммы станут больше прежних.")
        if "competitor" in missing:
            lines.append("  competitor лежит под category_N — найти номер:")
            lines.append("      python scripts/check_categories.py")
            lines.append("  и прописать:  COMPETITOR_COLUMN=category_N")
        if "include_exclude" in missing:
            lines.append("  include_exclude в базе нет вовсе. Ближайшее — чистка")
            lines.append("  на стороне базы:  INCLUDE_EXCLUDE_VIA=cleaning_flag")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Фильтры, которых не было в SQL Server
# ---------------------------------------------------------------------------
# ОБА ВЫКЛЮЧЕНЫ ПО УМОЛЧАНИЮ, и это принципиально: в прежних запросах к
# SQL Server таких фильтров не было, а переезд не должен менять цифры сам
# по себе. Сначала выгрузки должны сойтись, и только потом имеет смысл
# обсуждать, надо ли что-то отфильтровывать.
#
# ИСТОРИЯ. Сначала estat = 'R' был включён — по замеру из соседнего проекта
# (chizhik-compet, август 2026), где под него попадало 100% строк и 100%
# суммы, то есть фильтр был пустой операцией. На выборке оперкома это
# не подтвердилось: сверка со старой базой показала по наружке минус 65%
# затрат при минус 25% строк — расхождение слишком большое, чтобы объяснять
# его чем-то ещё. Чужой замер на свою выборку не переносится.
#
# Что каждый из них значит:
#   estat = 'R'       отбрасывает виртуальную рекламу, правило агентства
#                     «всегда ставить R». Колонка есть только в
#                     media_costs_union; в nat_tv, big_tv и reg_tv её нет,
#                     поэтому к рейтингам фильтр не применяется в принципе;
#   cleaning_flag = 1 чистка на стороне базы. Здесь её делает справочник
#                     (include_exclude, competitor), и включённый фильтр
#                     срезал бы строки ещё до справочника — понять, что
#                     пропало, было бы негде.
#
# Сколько каждый из них режет именно на нашей выборке:
#     python scripts/check_filters.py
#
# Включается одной строкой в .env, без правки кода:
#     ESTAT_FILTER=estat = 'R'
ESTAT_FILTER = _env("ESTAT_FILTER", "")
CLEANING_FILTER = _env("CLEANING_FILTER", "")


# ---------------------------------------------------------------------------
# Дубли
# ---------------------------------------------------------------------------
# Отчёт суммирует строки как есть. Если одна и та же строка лежит в таблице
# дважды, деньги удвоятся молча: ошибки не будет, цифры просто станут больше
# правды.
#
# Одинаковые бывают двух сортов, и путать их нельзя:
#
#   1. Настоящий дубль — совпадает и ключ, и цифры. Одна запись загружена
#      дважды. Такое схлопывать надо.
#   2. Один ключ, разные цифры — два разных размещения, которые таблица не
#      различает отдельной колонкой. Схлопывать их значит терять деньги.
#
# Отсюда три режима, DEDUPE в .env:
#
#   off (по умолчанию) — суммировать все строки подряд. Так же считает ручная
#       версия отчёта, с которой сверяются коллеги;
#   identical — убрать строки, совпадающие целиком, по ВСЕМ колонкам таблицы.
#       Замерено на этой базе: 0.3% строк и 0.08% денег, все в наружке;
#   key — оставлять одну строку на ключ, даже если цифры разные. Это минус
#       1.95% всех затрат и около 15% наружки: включать только убедившись,
#       что эти строки — мусор.
DEDUPE = _env("DEDUPE", "off").strip().lower()

#: Что считается одной и той же строкой затрат.
DEDUPE_COST_KEY = (
    "media_key_id",
    "cid",
    "netId",
    "regionId",
    "researchDate",
    "adDistributionType",
)

#: Цифры строки затрат. При DEDUPE=identical входят в ключ схлопывания.
DEDUPE_COST_MEASURES = ("Quantity", "vol", "ConsolidatedCostRUB", "ConsolidatedCostRUB_disc")

DEDUPE_RATE_KEY = (
    "media_key_id",
    "tvCompanyId",
    "regionId",
    "researchDate",
    "adDistributionType",
)

DEDUPE_RATE_MEASURES = (
    "Quantity",
    f"`RtgPer_{AUDIENCE}`",
    f"`StandRtgPer_{AUDIENCE}`",
)


# ---------------------------------------------------------------------------
# Сборка запросов
# ---------------------------------------------------------------------------

def _and(*conditions):
    """Собирает WHERE из условий, пропуская пустые."""
    return "\n  AND ".join(condition for condition in conditions if condition)


def _named(pairs, indent):
    """`выражение AS имя` через запятую; если имя совпало с выражением — без AS."""
    separator = ",\n" + " " * indent
    return separator.join(
        expression if expression == alias else f"{expression} AS {alias}"
        for expression, alias in pairs
    )


def _listed(names, indent):
    separator = ",\n" + " " * indent
    return separator.join(names)


def _aggregate_query(columns, metrics, table, alias, where, key, measures):
    """Запрос «разрезы плюс суммы», при необходимости через снятие дублей.

    columns — пары (выражение, имя) разрезов, metrics — пары (выражение, имя)
    того, что суммируется. При DEDUPE=off получается ровно тот же запрос, что
    и раньше: одна группировка без подзапроса.
    """
    dimensions = [name for _, name in columns]

    if DEDUPE == "off":
        sums = _listed([f"SUM({expression}) AS {name}" for expression, name in metrics], 4)
        return (
            f"SELECT\n    {_named(columns, 4)},\n    {sums}\n"
            f"FROM {table} AS {alias}\n"
            f"WHERE {where}\n"
            f"GROUP BY\n    {_listed(dimensions, 4)}"
        )

    if DEDUPE == "key":
        # Одна строка на ключ: цифры берутся у любой из совпавших строк.
        keys = [f"{alias}.{column}" for column in key]
        inner_metrics = _listed(
            [f"any({expression}) AS {name}" for expression, name in metrics], 8)
        inner = (
            f"    SELECT\n        {_named(columns, 8)},\n"
            f"        {_listed(keys, 8)},\n"
            f"        {inner_metrics}\n"
            f"    FROM {table} AS {alias}\n"
            f"    WHERE {where}\n"
            f"    GROUP BY\n        {_listed(dimensions + keys, 8)}"
        )
        sums = _listed([f"SUM({name}) AS {name}" for _, name in metrics], 4)
        return (
            f"SELECT\n    {_listed(dimensions, 4)},\n    {sums}\n"
            f"FROM (\n{inner}\n)\n"
            f"GROUP BY\n    {_listed(dimensions, 4)}"
        )

    # DEDUPE=identical: DISTINCT * — по всем колонкам таблицы, а не по тем,
    # что читает отчёт. Так «копия» значит копия и ничего больше: если строки
    # различаются хоть одной колонкой, пусть даже отчёту не нужной, обе
    # останутся. Перечислять колонки руками нельзя: пропущенная колонка молча
    # склеила бы разные строки.
    inner = (
        f"    SELECT DISTINCT *\n"
        f"    FROM {table} AS {alias}\n"
        f"    WHERE {where}"
    )
    sums = _listed([f"SUM({expression}) AS {name}" for expression, name in metrics], 4)
    return (
        f"SELECT\n    {_named(columns, 4)},\n    {sums}\n"
        f"FROM (\n{inner}\n)\n"
        f"GROUP BY\n    {_listed(dimensions, 4)}"
    )


# ---------------------------------------------------------------------------
# Затраты
# ---------------------------------------------------------------------------
# Колонки в WHERE обязательно через псевдоним таблицы (mc.): в ClickHouse
# псевдонимы из SELECT видны в WHERE, и `media_type = 'TV'` сравнивалось бы
# не с колонкой, а с lowerUTF8(media_type_long) — то есть 'tv' с 'TV'.
# Запрос не падает, а молча возвращает ноль строк.

def _cost_query(media_type, extra_columns=(), type_name="adTypeName"):
    """
    Запрос затрат одного медиа.

    extra_columns — пары (выражение, имя в ответе): то, что есть только
    у этого медиа. Имя из пары идёт и в SELECT, и в GROUP BY, поэтому
    разъехаться они не могут.
    """
    columns = [
        *extra_columns,
        *dictionary_columns(),
        (f"lowerUTF8({KEY_COLUMN})", KEY_COLUMN),
        ("adId", "ad_id"),
        ("lowerUTF8(media_type_long)", "media_type"),
        ("lowerUTF8(media_type_detail)", "media_type_detail"),
        (f"lowerUTF8({type_name})", "type_name"),
        ("lowerUTF8(adDistributionType)", "placement_name"),
        ("researchDate", "date"),
    ]

    where = _and(
        f"mc.media_type = '{COST_MEDIA_TYPES[media_type]}'",
        f"mc.researchDate >= '{PERIOD_FROM}'",
        ESTAT_FILTER and f"mc.{ESTAT_FILTER}",
        CLEANING_FILTER and f"mc.{CLEANING_FILTER}",
    )

    return _aggregate_query(
        columns,
        [("ConsolidatedCostRUB_disc", "cost_rub_disc")],
        COST_TABLE, "mc", where,
        DEDUPE_COST_KEY, DEDUPE_COST_MEASURES,
    )


# В прежнем запросе тип ролика для ТВ брался из tv_type_ooh_reg, а не из
# справочника типов — расхождение с остальными медиа сохранено намеренно.
TV_SQL = _cost_query(
    "tv",
    type_name="tv_type_ooh_reg",
    extra_columns=(
        ("regionName", "region_tv"),
        ("adStandardDuration", "tv_duration"),
        ("lowerUTF8(netName)", "tv_comapny"),
    ),
)


RADIO_SQL = _cost_query(
    "radio",
    extra_columns=(
        ("adStandardDuration", "ra_duration"),
        ("lowerUTF8(companyName)", "ra_comapny"),
        ("lowerUTF8(netName)", "ra_net"),
    ),
)


OOH_SQL = _cost_query(
    "outdoor",
    extra_columns=(("regionName", "region_ooh"),),
)


PRESS_SQL = _cost_query(
    "press",
    extra_columns=(("lowerUTF8(netName)", "pr_net"),),
)


# ---------------------------------------------------------------------------
# Рейтинги ТВ
# ---------------------------------------------------------------------------

def _rate_query(table, alias, where, metrics):
    """Общая часть запросов рейтингов: разрезы у нац и рег одинаковые."""
    columns = [
        *dictionary_columns(),
        (f"lowerUTF8({KEY_COLUMN})", KEY_COLUMN),
        ("adId", "id"),
        ("researchDate", "date"),
        ("adDistributionType", "ad_placement_id"),
        ("lowerUTF8(adTypeName)", "ad_type_name"),
        ("adStandardDuration", "duration"),
        ("regionName", "regionName"),
        # media_type_detail НЕ приводится к нижнему регистру намеренно:
        # прежние запросы рейтингов его не приводили (в отличие от запросов
        # затрат, где LOWER стоял). Ноутбук всё равно опускает регистр после
        # мёржа, но при сверке выгрузок лишнее расхождение только мешает.
        ("media_type_detail", "media_type_detail"),
    ]
    return _aggregate_query(
        columns, metrics, table, alias, where,
        DEDUPE_RATE_KEY, DEDUPE_RATE_MEASURES,
    )


#: У nat_tv и big_tv взвешенного рейтинга нет — как не было его и в прежнем
#: запросе к nat_tv_simple / big_tv_simple.
_NAT_METRICS = [
    (f"`RtgPer_{AUDIENCE}`", "tvr_18"),
    (f"`StandRtgPer_{AUDIENCE}`", "st_tvr"),
]


def _build_nat_rate():
    """
    Национальное ТВ: nat_tv до конца 2024-го, big_tv с 2025-го.

    UNION ALL, а не UNION: в ClickHouse UNION требует явного DISTINCT или ALL.
    На смысл это не влияет — периоды у веток не пересекаются, схлопывать
    нечего, а UNION вдобавок молча убрал бы одинаковые строки внутри ветки.

    Расхождение из прежнего запроса сохранено намеренно: ветка за 2024 год
    фильтрует тип ролика, ветка с 2025-го — нет. Так было в исходном запросе;
    переезд не должен менять смысл данных. Выглядит несогласованностью
    и стоит обсудить отдельно.
    """
    nat = _rate_query(
        NAT_TV_TABLE, "nt",
        _and(
            f"nt.researchDate >= '{NAT_TV_PERIOD[0]}'",
            f"nt.researchDate <= '{NAT_TV_PERIOD[1]}'",
            "nt.adDistributionType IN ('N', 'O')",
            # lowerUTF8, а не голое сравнение: в базе тип записан прописными.
            "lowerUTF8(nt.adTypeName) = 'ролик'",
            CLEANING_FILTER and f"nt.{CLEANING_FILTER}",
        ),
        _NAT_METRICS,
    )
    big = _rate_query(
        BIG_TV_TABLE, "bt",
        _and(
            f"bt.researchDate >= '{BIG_TV_FROM}'",
            "bt.adDistributionType IN ('N', 'O')",
            CLEANING_FILTER and f"bt.{CLEANING_FILTER}",
        ),
        _NAT_METRICS,
    )
    return f"{nat}\n\nUNION ALL\n\n{big}"


OPERCOM_TV_RATE_NAT = _build_nat_rate()


#: Региональное ТВ. Взвешенный рейтинг здесь есть, и именно он идёт в tvr_18 —
#: как в прежнем запросе. Невзвешенный лежит рядом, под своим именем.
OPERCOM_TV_RATE_REG = _rate_query(
    REG_TV_TABLE, "rt",
    _and(
        f"rt.researchDate >= '{PERIOD_FROM}'",
        CLEANING_FILTER and f"rt.{CLEANING_FILTER}",
    ),
    [
        (f"`RtgPer_w_{AUDIENCE}`", "tvr_18"),
        (f"`RtgPer_{AUDIENCE}`", "tvr_18_not_weighted"),
        (f"`StandRtgPer_{AUDIENCE}`", "st_tvr"),
    ],
)
