"""Тесты слоя доступа к базе: наборы запросов и выбор подключения.

Сервер здесь не нужен — проверяется текст запросов и логика выбора. Прогон
запросов на настоящем движке ClickHouse делает scripts/verify_queries.py.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import queries as queries_mod  # noqa: E402
from app import sql_dict_connection as ch  # noqa: E402
from app import sql_dict_connection_mssql as ms  # noqa: E402
from functions.db import (  # noqa: E402
    CLICKHOUSE_MARKERS,
    MSSQL_MARKERS,
    ClickHouseDatabase,
    DatabaseError,
    _check_dialect,
    create_database,
)

#: Запросы, которые вызывает ноутбук.
EXPECTED_QUERIES = {
    "TV_SQL",
    "RADIO_SQL",
    "OOH_SQL",
    "PRESS_SQL",
    "OPERCOM_TV_RATE_NAT",
    "OPERCOM_TV_RATE_REG",
}


def _names(module):
    return set(queries_mod.query_names(module))


# --- наборы запросов --------------------------------------------------------


def test_both_query_sets_cover_the_core_queries():
    """Переключение движка не должно терять запрос, который есть в обоих."""
    assert EXPECTED_QUERIES <= _names(ch)
    assert EXPECTED_QUERIES <= _names(ms)


def test_digital_exists_only_for_clickhouse():
    """Диджитал переехал в базу; в SQL Server его не было — он приходил Excel'ем.

    Ноутбук проверяет наличие запроса по Q.names и на mssql уходит в Excel,
    поэтому лишний запрос в одном наборе ничего не ломает.
    """
    assert "DIGITAL_SQL" in _names(ch)
    assert "DIGITAL_SQL" not in _names(ms)


def test_queries_for_picks_the_matching_module():
    assert queries_mod.queries_for("clickhouse").source.endswith("sql_dict_connection.py")
    assert queries_mod.queries_for("mssql").source.endswith("sql_dict_connection_mssql.py")
    # Пустой движок — на всякий случай clickhouse, а не падение.
    assert queries_mod.queries_for(None).engine == "clickhouse"


@pytest.mark.parametrize("name", sorted(EXPECTED_QUERIES))
def test_clickhouse_queries_carry_no_mssql_dialect(name):
    """Обратное направление ловушки: в ClickHouse-наборе не должно быть T-SQL."""
    text = getattr(ch, name).lower()
    for marker in MSSQL_MARKERS:
        assert marker.lower() not in text, f"{name}: остался {marker!r} из T-SQL"


@pytest.mark.parametrize("name", sorted(EXPECTED_QUERIES))
def test_mssql_queries_carry_no_clickhouse_dialect(name):
    text = getattr(ms, name)
    for marker in CLICKHOUSE_MARKERS:
        assert marker not in text, f"{name}: {marker!r} есть только в ClickHouse"


def test_dialect_guard_explains_the_mixup():
    """Запрос не для той базы должен упасть понятным текстом, а не в драйвере."""
    with pytest.raises(DatabaseError, match="ClickHouse"):
        _check_dialect(ch.TV_SQL, "mssql")

    with pytest.raises(DatabaseError, match="SQL Server"):
        _check_dialect("SELECT TOP 10 * FROM t", "clickhouse")


# --- ClickHouse: что именно спрашиваем --------------------------------------


def test_cyrillic_values_are_lowered_with_utf8_aware_function():
    """Обычный LOWER кириллицу не трогает — в базе значения прописными."""
    for name in EXPECTED_QUERIES:
        text = getattr(ch, name)
        assert "lowerUTF8(" in text, f"{name}: нет lowerUTF8"


def test_audience_became_a_column_choice():
    """Колонки prj_name в базе нет: аудитория выбирается именем колонки."""
    assert "prj_name" not in ch.OPERCOM_TV_RATE_NAT
    assert "prj_name" not in ch.OPERCOM_TV_RATE_REG

    assert f"`RtgPer_{ch.AUDIENCE}`" in ch.OPERCOM_TV_RATE_NAT
    assert f"`StandRtgPer_{ch.AUDIENCE}`" in ch.OPERCOM_TV_RATE_NAT


def test_weighted_rating_only_where_it_exists():
    """RtgPer_w есть у reg_tv и нет у nat_tv/big_tv — как и в прежних запросах."""
    assert f"`RtgPer_w_{ch.AUDIENCE}`" in ch.OPERCOM_TV_RATE_REG
    assert f"`RtgPer_w_{ch.AUDIENCE}`" not in ch.OPERCOM_TV_RATE_NAT

    # Взвешенный идёт в tvr_18, невзвешенный лежит рядом под своим именем.
    assert f"`RtgPer_w_{ch.AUDIENCE}`) AS tvr_18" in ch.OPERCOM_TV_RATE_REG
    assert "tvr_18_not_weighted" in ch.OPERCOM_TV_RATE_REG


def test_national_tv_is_glued_from_two_tables_without_dedup():
    """UNION в ClickHouse требует явного ALL, и UNION молча схлопнул бы строки."""
    assert "UNION ALL" in ch.OPERCOM_TV_RATE_NAT
    assert ch.NAT_TV_TABLE in ch.OPERCOM_TV_RATE_NAT
    assert ch.BIG_TV_TABLE in ch.OPERCOM_TV_RATE_NAT

    # Асимметрия из прежнего запроса сохранена: тип ролика фильтрует
    # только ветка за 2024 год.
    assert ch.OPERCOM_TV_RATE_NAT.count("= 'ролик'") == 1


def test_costs_come_from_one_table_split_by_media_type():
    """Четыре таблицы затрат стали одной, медиа различается колонкой."""
    for name, code in (("TV_SQL", "TV"), ("RADIO_SQL", "RA"),
                       ("OOH_SQL", "OD"), ("PRESS_SQL", "PR")):
        text = getattr(ch, name)
        assert ch.COST_TABLE in text, f"{name}: не та таблица затрат"
        assert f"mc.media_type = '{code}'" in text, f"{name}: не тот код медиа"


def test_media_type_filter_is_qualified_by_table_alias():
    """Без псевдонима mc. фильтр сравнивал бы 'tv' с 'TV' и молча давал ноль строк."""
    assert "media_type = 'TV'" in ch.TV_SQL
    assert "mc.media_type = 'TV'" in ch.TV_SQL


def test_join_key_comes_from_the_database():
    """media_key_id есть и в базе, и в справочнике — собирать ключ руками незачем."""
    for name in EXPECTED_QUERIES:
        assert ch.KEY_COLUMN in getattr(ch, name), f"{name}: нет {ch.KEY_COLUMN}"


def test_no_where_filters_beyond_what_the_old_queries_had():
    """Переезд не должен менять цифры сам по себе: лишних фильтров в WHERE нет.

    cleaning_flag при этом может встречаться в SELECT — там он не отсекает
    строки, а восстанавливает include_exclude, то есть воспроизводит фильтр,
    который был и раньше. Отбор по нему делает уже ноутбук.
    """
    assert ch.ESTAT_FILTER == ""
    assert ch.CLEANING_FILTER == ""
    for name in EXPECTED_QUERIES:
        where = getattr(ch, name).split("WHERE", 1)[-1].split("GROUP BY", 1)[0]
        assert "estat" not in where, f"{name}: фильтр estat в WHERE"
        assert "cleaning_flag" not in where, f"{name}: фильтр cleaning_flag в WHERE"


def test_estat_filter_only_reaches_the_table_that_has_the_column(monkeypatch):
    """Когда фильтр включают, он идёт только в затраты: в таблицах ТВ колонки нет."""
    monkeypatch.setenv("ESTAT_FILTER", "estat = 'R'")
    module = importlib.reload(ch)
    try:
        assert "mc.estat = 'R'" in module.TV_SQL
        assert "estat" not in module.OPERCOM_TV_RATE_NAT
        assert "estat" not in module.OPERCOM_TV_RATE_REG
    finally:
        monkeypatch.delenv("ESTAT_FILTER", raising=False)
        importlib.reload(ch)


def test_rate_queries_keep_media_type_detail_as_is():
    """Прежние запросы рейтингов регистр этой колонки не трогали."""
    for name in ("OPERCOM_TV_RATE_NAT", "OPERCOM_TV_RATE_REG"):
        text = getattr(ch, name)
        assert "lowerUTF8(media_type_detail)" not in text, name
        assert "media_type_detail" in text, name

    # А запросы затрат — приводили, и это тоже надо сохранить.
    assert "lowerUTF8(media_type_detail)" in ch.TV_SQL


@pytest.mark.parametrize("mode", ["off", "identical", "key"])
def test_every_dedupe_mode_builds_valid_sql(monkeypatch, mode):
    """Все три режима должны собираться и оставаться разными запросами."""
    monkeypatch.setenv("DEDUPE", mode)
    module = importlib.reload(ch)
    try:
        assert module.DEDUPE == mode
        for name in EXPECTED_QUERIES:
            text = getattr(module, name)
            assert text.strip().startswith("SELECT")
            assert "GROUP BY" in text
            if mode == "identical":
                assert "SELECT DISTINCT *" in text
            if mode == "key":
                assert "any(" in text
    finally:
        monkeypatch.delenv("DEDUPE", raising=False)
        importlib.reload(ch)


# --- подключение ------------------------------------------------------------


def test_missing_host_says_where_it_looked(monkeypatch):
    for name in ("CLICKHOUSE_HOST", "CH_HOST", "HOST", "ENV_FILE", "DOTENV_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("functions.db.find_env_file", lambda start=None: None)
    monkeypatch.setattr("functions.db._ENV_FILE_LOADED", False, raising=False)

    with pytest.raises(DatabaseError, match="CLICKHOUSE_HOST"):
        create_database("clickhouse")


def test_unfilled_placeholder_is_rejected(monkeypatch):
    monkeypatch.setenv("CLICKHOUSE_HOST", "<хост>")

    with pytest.raises(DatabaseError, match="заготовки"):
        create_database("clickhouse")


def test_unknown_engine_is_rejected():
    with pytest.raises(DatabaseError, match="Неизвестный движок"):
        create_database("postgres")


def test_https_port_implies_secure():
    """secure выводится из порта: 8443 — HTTPS, 8123 — HTTP."""
    assert ClickHouseDatabase("h", "u", port=8443).secure is True
    assert ClickHouseDatabase("h", "u", port=8123).secure is False


def test_outer_joins_keep_null_semantics():
    """Без join_use_nulls внешние JOIN отдают 0 вместо NULL, и суммы уезжают."""
    assert ClickHouseDatabase("h", "u").settings["join_use_nulls"] == 1


# --- классификация из базы вместо справочника -------------------------------


def test_classification_comes_from_the_database_by_default():
    """Справочника нет: brand_main и прочее приходят колонками выгрузки."""
    assert ch.DICTIONARY_FROM_DB is True

    for name in EXPECTED_QUERIES:
        text = getattr(ch, name)
        for _, alias in ch.dictionary_columns():
            assert alias in text, f"{name}: нет поля классификации {alias}"


def test_category_columns_are_lowered():
    """В базе значения прописными, отчёт сравнивает со строчными."""
    for _, column in ch.CATEGORY_COLUMNS.items():
        if not column:
            continue
        assert f"lowerUTF8({column})" in ch.TV_SQL


def test_sheet_mode_puts_no_classification_in_the_query(monkeypatch):
    """Откат на Google-таблицу — одна строка в .env, без правки кода."""
    monkeypatch.setenv("DICTIONARY_SOURCE", "sheet")
    module = importlib.reload(ch)
    try:
        assert module.DICTIONARY_FROM_DB is False
        assert module.dictionary_columns() == ()
        assert "brand_main" not in module.TV_SQL
        # В режиме справочника нехватки фильтров нет: их приносит мёрж.
        assert module.unresolved_filters() == ()
    finally:
        monkeypatch.delenv("DICTIONARY_SOURCE", raising=False)
        importlib.reload(ch)


def test_competitor_is_resolved_from_the_view_definition():
    """category_1 прочитан из текста big_tv_weekly_view, а не угадан по значениям.

    Угадать было нельзя: competitor и retail_category оба принимают только
    YES/NO, и по набору значений они неразличимы.
    """
    assert ch.CATEGORY_COLUMNS["competitor"] == "category_1"
    assert "lowerUTF8(category_1) AS competitor" in ch.TV_SQL
    assert "competitor" not in ch.unresolved_filters()


def test_missing_filter_is_reported_not_silently_skipped(monkeypatch):
    """Непримененный фильтр не роняет прогон — он молча завышает суммы."""
    monkeypatch.setenv("INCLUDE_EXCLUDE_VIA", "none")
    module = importlib.reload(ch)
    try:
        assert module.unresolved_filters() == ("include_exclude",)
        report = module.describe_classification()
        assert "ФИЛЬТРЫ БЕЗ КОЛОНКИ" in report
        assert "суммы станут больше" in report
    finally:
        monkeypatch.delenv("INCLUDE_EXCLUDE_VIA", raising=False)
        importlib.reload(ch)


def test_resolving_the_columns_clears_the_warning(monkeypatch):
    monkeypatch.setenv("COMPETITOR_COLUMN", "category_6")
    monkeypatch.setenv("INCLUDE_EXCLUDE_VIA", "cleaning_flag")
    module = importlib.reload(ch)
    try:
        assert module.unresolved_filters() == ()
        assert "lowerUTF8(category_6) AS competitor" in module.TV_SQL
        # include_exclude приводится к тем же значениям, что ждёт ноутбук.
        assert "'include'" in module.TV_SQL and "'!exclude'" in module.TV_SQL
    finally:
        monkeypatch.delenv("COMPETITOR_COLUMN", raising=False)
        monkeypatch.delenv("INCLUDE_EXCLUDE_VIA", raising=False)
        importlib.reload(ch)


def test_include_exclude_reaches_costs_and_ratings_alike():
    """Отбор одинаков для всех источников — иначе слайды считались бы по-разному."""
    for name in EXPECTED_QUERIES:
        assert "include_exclude" in getattr(ch, name), name


# --- include_exclude: заменитель вместо настоящей колонки -------------------


def test_include_exclude_uses_cleaning_flag_by_default():
    """Колонки нет в наших таблицах, поэтому её заменяет чистка на стороне базы."""
    assert ch.INCLUDE_EXCLUDE_VIA == "cleaning_flag"
    assert ch.unresolved_filters() == ()

    # Значения те же, что ждёт фильтр в ноутбуке: `== 'include'`.
    assert f"if({ch.CLEANING_FLAG_INCLUDE}, 'include', '!exclude') AS include_exclude" in ch.TV_SQL


def test_the_guess_is_visible_not_silent():
    """Заменитель — это догадка, и она не должна выглядеть решённым вопросом."""
    report = ch.describe_classification()
    assert "ДОГАДКА" in report
    assert "не двоичный" in report
    # Подсказка, где искать настоящую колонку.
    assert "dump_schema.py --database mediascope_x5_big_v23" in report


def test_cleaning_flag_condition_is_configurable(monkeypatch):
    """Флаг не 0/1: в radio_dss_x5_v1 встречается 2, поэтому условие — настройка."""
    monkeypatch.setenv("CLEANING_FLAG_INCLUDE", "cleaning_flag IN (1, 2)")
    module = importlib.reload(ch)
    try:
        assert "if(cleaning_flag IN (1, 2), 'include', '!exclude')" in module.TV_SQL
    finally:
        monkeypatch.delenv("CLEANING_FLAG_INCLUDE", raising=False)
        importlib.reload(ch)


def test_real_column_is_passed_through_without_invented_mapping(monkeypatch):
    """Если колонка найдётся: только нижний регистр, никаких своих отображений.

    В базе пишут EXCLUDE, в справочнике писали !exclude — фильтр `== 'include'`
    отсекает оба одинаково. Придумывать перевод значений значило бы молча
    поменять отбор.
    """
    monkeypatch.setenv("INCLUDE_EXCLUDE_VIA", "column")
    module = importlib.reload(ch)
    try:
        assert "lowerUTF8(ifNull(include_exclude, '')) AS include_exclude" in module.TV_SQL
        assert "'!exclude'" not in module.TV_SQL
    finally:
        monkeypatch.delenv("INCLUDE_EXCLUDE_VIA", raising=False)
        importlib.reload(ch)


def test_filter_can_still_be_turned_off_entirely(monkeypatch):
    monkeypatch.setenv("INCLUDE_EXCLUDE_VIA", "")
    module = importlib.reload(ch)
    try:
        # Пустое значение подхватывает умолчание, поэтому выключаем явным словом.
        monkeypatch.setenv("INCLUDE_EXCLUDE_VIA", "none")
        module = importlib.reload(ch)
        assert "include_exclude" not in module.TV_SQL
        assert module.unresolved_filters() == ("include_exclude",)
    finally:
        monkeypatch.delenv("INCLUDE_EXCLUDE_VIA", raising=False)
        importlib.reload(ch)


# --- диджитал ---------------------------------------------------------------


def test_digital_asks_only_for_what_the_report_reads():
    """Каждая лишняя колонка — лишний шанс не совпасть с названием в базе."""
    for alias in ("brand_main", "advertiser_main", "delivery", "year", "month",
                  "cost_rub_disc"):
        assert alias in ch.DIGITAL_SQL, alias

    # Этого отчёт не читает, и тащить их незачем.
    for unused in ("site", "marketing_channel", "quarter", "coef", "brand_segment"):
        assert unused not in ch.DIGITAL_SQL, unused


def test_digital_delivery_never_comes_back_null():
    """groupby в pandas выбрасывает строки с NaN в ключе — часть данных пропала бы."""
    assert "ifNull(d.delivery, '')" in ch.DIGITAL_SQL


def test_digital_takes_the_usable_cost_column():
    """Колонок затрат две; вторая называется cost_NOT_FOR_USE."""
    assert "SUM(d.cost_estimated) AS cost_rub_disc" in ch.DIGITAL_SQL
    assert "cost_NOT_FOR_USE" not in ch.DIGITAL_SQL
