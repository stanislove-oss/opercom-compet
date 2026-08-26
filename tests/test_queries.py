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


def test_both_query_sets_cover_the_same_names():
    """Переключение движка не должно терять запрос: имена обязаны совпадать."""
    assert _names(ch) == _names(ms) == EXPECTED_QUERIES


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


def test_no_filters_beyond_what_the_old_queries_had():
    """Переезд не должен менять цифры сам по себе: лишних фильтров нет."""
    assert ch.ESTAT_FILTER == ""
    assert ch.CLEANING_FILTER == ""
    for name in EXPECTED_QUERIES:
        text = getattr(ch, name)
        assert "estat" not in text, f"{name}: фильтр estat включён по умолчанию"
        assert "cleaning_flag" not in text, f"{name}: фильтр cleaning_flag включён"


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
