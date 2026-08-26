"""Тесты диагностики подключения.

Повод: пользователь получил вот такое, и по нему понять нечего —

    mediascope_x5_big_v22: Запрос к ClickHouse не выполнился.
      default: Запрос к ClickHouse не выполнился.
      system: Запрос к ClickHouse не выполнился.

Настоящая причина терялась дважды: `_explain` клал её на третью строку,
а `connect_for_discovery` брал только первую. Плюс отказ подключения
заворачивался в «запрос не выполнился» — то есть причина подменялась
следствием, и три одинаковые строки предлагали искать не там.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from functions import db as db_mod  # noqa: E402
from functions.db import (  # noqa: E402
    ClickHouseDatabase,
    ConnectionFailed,
    DatabaseError,
    connect_for_discovery,
    one_line,
)

#: То, что реально отдаёт драйвер, когда сервера нет.
DRIVER_ERROR = (
    "HTTPDriver for http://ch.example.ru:8123 received ConnectionError\n"
    "Max retries exceeded with url: / (Caused by NewConnectionError(\n"
    "'<urllib3.connection.HTTPConnection object>: Failed to establish a new "
    "connection: [Errno 111] Connection refused'))"
)


class _RefusingClient:
    """Клиент, который падает на любом запросе — сервер отвечает, но запрос плох."""

    def __init__(self, message="Code: 81. DB::Exception: Database x does not exist."):
        self.message = message

    def command(self, *args, **kwargs):
        raise RuntimeError(self.message)

    query = query_df = command

    def close(self):
        pass


@pytest.fixture
def unreachable(monkeypatch):
    """clickhouse_connect.get_client падает так же, как при недоступном сервере."""
    module = type(sys)("clickhouse_connect")
    module.get_client = lambda **kwargs: (_ for _ in ()).throw(Exception(DRIVER_ERROR))
    monkeypatch.setitem(sys.modules, "clickhouse_connect", module)


# --- причина не должна теряться --------------------------------------------


def test_connection_failure_is_not_disguised_as_a_query_failure(unreachable):
    """Отказ подключения — это ConnectionFailed, а не «запрос не выполнился»."""
    database = ClickHouseDatabase("ch.example.ru", "reporting", port=8123)

    with pytest.raises(ConnectionFailed) as excinfo:
        database.execute("SELECT 1")

    message = str(excinfo.value)
    assert "Запрос к ClickHouse не выполнился" not in message
    assert "Не удалось подключиться" in message
    assert "Connection refused" in message


@pytest.mark.parametrize("call", ["execute", "fetch_all", "fetch_df"])
def test_every_entry_point_keeps_the_connection_error(unreachable, call):
    database = ClickHouseDatabase("ch.example.ru", "reporting", port=8123)

    with pytest.raises(ConnectionFailed):
        getattr(database, call)("SELECT 1")


def test_query_failure_puts_the_reason_on_the_first_line():
    """Вызывающий код часто показывает только первую строку — там и причина."""
    database = ClickHouseDatabase(
        "ch", "u", client=_RefusingClient("Code: 47. Unknown identifier: adID"))

    with pytest.raises(DatabaseError) as excinfo:
        database.fetch_all("SELECT adID FROM nat_tv")

    first_line = str(excinfo.value).splitlines()[0]
    assert "Unknown identifier: adID" in first_line, first_line


def test_one_line_collapses_multiline_driver_output():
    collapsed = one_line(DRIVER_ERROR)
    assert "\n" not in collapsed
    assert "Connection refused" in collapsed


# --- разведка баз -----------------------------------------------------------


def test_discovery_does_not_blame_the_database_name(monkeypatch, unreachable):
    """Именно этот случай и дал три бессмысленные строки."""
    monkeypatch.setenv("CLICKHOUSE_HOST", "ch.example.ru")
    monkeypatch.setenv("CLICKHOUSE_DATABASE", "mediascope_x5_big_v22")
    monkeypatch.setattr(db_mod, "_ENV_FILE_LOADED", False, raising=False)

    with pytest.raises(ConnectionFailed) as excinfo:
        connect_for_discovery("clickhouse")

    message = str(excinfo.value)
    assert "Connection refused" in message
    assert "не дошёл ни один запрос" in message
    # Три одинаковые строки про три базы — ровно то, что чинили.
    assert message.count("Не удалось подключиться") == 1


def test_discovery_still_tries_other_names_when_server_answers(monkeypatch):
    """Сервер отвечает, но база не та — вот тогда имена перебирать осмысленно."""
    attempted = []

    def fake_create(engine=None, profile=None, **overrides):
        name = overrides["database"]
        attempted.append(name)
        return ClickHouseDatabase("ch", "u", database=name, client=_RefusingClient())

    monkeypatch.setattr(db_mod, "create_database", fake_create)
    monkeypatch.setenv("CLICKHOUSE_DATABASE", "wrong_name")
    monkeypatch.setattr(db_mod, "_ENV_FILE_LOADED", False, raising=False)

    with pytest.raises(DatabaseError) as excinfo:
        connect_for_discovery("clickhouse")

    assert attempted == ["wrong_name", "default", "system"]
    assert "Сервер отвечает" in str(excinfo.value)


# --- подсказки по тексту ошибки ---------------------------------------------


@pytest.mark.parametrize(
    "driver_error, expected",
    [
        ("certificate verify failed: unable to get local issuer", "truststore"),
        ("Read timed out after 15 seconds", "не ответил"),
        ("[Errno 111] Connection refused", "8123"),
        ("Code: 516. Authentication failed: password is incorrect", "CLICKHOUSE_PASSWORD"),
    ],
)
def test_hint_matches_the_driver_message(monkeypatch, driver_error, expected):
    module = type(sys)("clickhouse_connect")
    module.get_client = lambda **kwargs: (_ for _ in ()).throw(Exception(driver_error))
    monkeypatch.setitem(sys.modules, "clickhouse_connect", module)

    database = ClickHouseDatabase("ch.example.ru", "reporting", port=8123)

    with pytest.raises(ConnectionFailed) as excinfo:
        database.execute("SELECT 1")

    assert expected in str(excinfo.value)


def test_missing_driver_says_what_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "clickhouse_connect", None)
    monkeypatch.delitem(sys.modules, "clickhouse_connect")

    def no_module(name, *args, **kwargs):
        if name == "clickhouse_connect":
            raise ImportError(name)
        return original(name, *args, **kwargs)

    import builtins

    original = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", no_module)

    with pytest.raises(DatabaseError, match="pip install clickhouse-connect"):
        ClickHouseDatabase("ch", "u").client
