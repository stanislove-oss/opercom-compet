#!/usr/bin/env python3
"""
Проверка слоя доступа к базе и правил переезда на ClickHouse.

Правила в functions/sql_compat.py не выдуманы: каждое здесь подтверждается
запросом к настоящему движку ClickHouse. Для этого используется chdb —
тот же ClickHouse, только встроенный в процесс, без сервера.

    pip install chdb
    python scripts/db_test.py

Если chdb не установлен, проверки движка пропускаются, а слой доступа и
линтер всё равно тестируются.
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from functions.db import (  # noqa: E402
    ClickHouseDatabase,
    DatabaseError,
    MSSQLDatabase,
    create_database,
    describe_environment,
)
from functions.sql_compat import (  # noqa: E402
    SEVERITY_ERROR,
    SEVERITY_SILENT,
    check_queries,
    check_sql,
    format_report,
    summarize,
)

try:
    import chdb
except ImportError:
    chdb = None


# ---------------------------------------------------------------------------
# Поведение ClickHouse, на котором стоят правила
# ---------------------------------------------------------------------------

#: (описание, запрос «как в SQL Server», запрос «как надо в ClickHouse»,
#:  ожидание для первого: 'падает' или конкретный результат)
ENGINE_CASES = [
    ("DATEDIFF с двумя аргументами",
     "SELECT DATEDIFF(toDate('2026-03-01'), toDate('2026-01-01'))",
     "SELECT dateDiff('day', toDate('2026-01-01'), toDate('2026-03-01'))",
     "падает"),

    ("UNION без ALL",
     "SELECT 1 UNION SELECT 2",
     "SELECT 1 UNION ALL SELECT 2",
     "падает"),

    ("арифметика со строкой",
     "SELECT '5' + 1",
     "SELECT toInt32('5') + 1",
     "падает"),

    # Значение параметра здесь задаётся через SET — так его понимает движок
    # напрямую. В коде это делает драйвер: db.fetch_df(SQL, {'value': 7}).
    ("плейсхолдер pymysql",
     "SELECT %s",
     "SET param_value = 7; SELECT {value:Int32}",
     "падает"),

    ("LOWER на кириллице",
     "SELECT lower('БАНК')",
     "SELECT lowerUTF8('БАНК')",
     "БАНК"),

    ("LIKE различает регистр",
     "SELECT 'Банк' LIKE '%банк%'",
     "SELECT 'Банк' ILIKE '%банк%'",
     "0"),

    ("LEFT JOIN подставляет 0 вместо NULL",
     "SELECT b.y FROM (SELECT 1 x) a LEFT JOIN (SELECT 2 x, 3 y) b ON a.x = b.x",
     "SELECT b.y FROM (SELECT 1 x) a LEFT JOIN (SELECT 2 x, 3 y) b ON a.x = b.x "
     "SETTINGS join_use_nulls = 1",
     "0"),

    ("сумма пустого набора — 0, а не NULL",
     "SELECT sum(x) FROM (SELECT 1 x WHERE 0)",
     "SELECT if(count() = 0, NULL, sum(x)) FROM (SELECT 1 x WHERE 0)",
     "0"),

    ("деление на ноль даёт inf",
     "SELECT 1 / 0",
     "SELECT if(0 = 0, 0, 1 / 0)",
     "inf"),
]


def run(sql, parameters=None):
    try:
        return "ok", str(chdb.query(sql, "CSV")).strip().strip('"')
    except Exception as error:
        return "падает", str(error).split("\n")[0][:80]


def check_engine_behaviour():
    print("=== поведение ClickHouse (движок chdb) ===\n")

    if chdb is None:
        print("  chdb не установлен — пропускаем (pip install chdb)\n")
        return

    print(f"  версия ядра: {run('SELECT version()')[1]}\n")

    failures = []
    for title, source_sql, clickhouse_sql, expected in ENGINE_CASES:
        status, value = run(source_sql)
        fixed_status, fixed_value = run(clickhouse_sql)

        if expected == "падает":
            ok = status == "падает"
            was = "падает" if ok else f"неожиданно сработало: {value}"
        else:
            ok = status == "ok" and value == expected
            was = f"вернуло {value!r}" + ("" if ok else f", ждали {expected!r}")

        fixed_ok = fixed_status == "ok"

        mark = "  " if (ok and fixed_ok) else "! "
        print(f"{mark}{title}")
        print(f"      как в SQL Server: {was}")
        print(f"      как надо:        {'работает: ' + fixed_value if fixed_ok else fixed_value}")

        if not (ok and fixed_ok):
            failures.append(title)

    print()
    assert not failures, f"поведение движка разошлось с правилами: {failures}"
    print(f"  все {len(ENGINE_CASES)} правил подтверждены движком\n")


# ---------------------------------------------------------------------------
# Линтер
# ---------------------------------------------------------------------------

SAMPLE_QUERIES = {
    "TV_SQL": """
        SELECT t.ad_id, t.date, t.cost_rub_disc, d.brand_main
        FROM tv_adex t
        LEFT JOIN dict d ON d.ad_id = t.ad_id
        WHERE t.date >= %s
          AND LOWER(d.brand_main) LIKE '%%банк%%'
          AND DATEDIFF(t.date, t.first_issue_date) < 30
        UNION
        SELECT ad_id, date, cost_rub_disc, brand_main FROM tv_adex_archive
    """,
    "CLEAN_SQL": """
        SELECT toStartOfMonth(date) AS month, sum(cost_rub_disc) AS cost
        FROM tv_adex
        WHERE date >= {start:Date}
        GROUP BY month
    """,
}


def check_linter():
    print("=== линтер запросов ===\n")

    report = check_queries(SAMPLE_QUERIES)
    print(format_report(report))

    counts = summarize(report)
    print(f"  итого: падает — {counts[SEVERITY_ERROR]}, "
          f"тихо меняет результат — {counts[SEVERITY_SILENT]}\n")

    codes = {item["code"] for item in report["TV_SQL"]}
    for expected in ("datediff", "union_all", "placeholder",
                     "lower_cyrillic", "like_case", "left_join_nulls"):
        assert expected in codes, f"линтер не нашёл {expected}"

    assert not [i for i in report["CLEAN_SQL"] if i["severity"] == SEVERITY_ERROR], \
        "на чистом запросе линтер ругается зря"

    print("  линтер ловит всё, что должен, и не шумит на чистом запросе\n")


# ---------------------------------------------------------------------------
# Слой доступа
# ---------------------------------------------------------------------------

class FakeResult:
    def __init__(self, columns, rows):
        self.column_names = columns
        self.result_rows = rows


class FakeClient:
    """Подменяет clickhouse-connect: проверяем обвязку, а не сеть."""

    def __init__(self):
        self.calls = []

    def query(self, query, parameters=None, settings=None):
        self.calls.append(("query", query, parameters, settings))
        return FakeResult(["brand", "cost"], [("сбер", 10), ("втб", 20)])

    def query_df(self, query, parameters=None, settings=None):
        self.calls.append(("query_df", query, parameters, settings))
        return pd.DataFrame({"brand": ["сбер", "втб"], "cost": [10, 20]})

    def command(self, query, parameters=None):
        self.calls.append(("command", query, parameters))
        return "26.7.1"

    def close(self):
        self.calls.append(("close",))


def check_database_layer():
    print("=== слой доступа ===\n")

    fake = FakeClient()
    db = ClickHouseDatabase(host="ch", user="u", database="media", client=fake)

    rows = db.fetch_all("SELECT 1")
    assert rows == [{"brand": "сбер", "cost": 10}, {"brand": "втб", "cost": 20}]
    print("  fetch_all отдаёт список словарей — pd.DataFrame(db.fetch_all(SQL)) как раньше")

    frame = db.fetch_df("SELECT 1")
    assert list(frame.columns) == ["brand", "cost"] and len(frame) == 2
    print("  fetch_df отдаёт DataFrame сразу, с типами из ClickHouse")

    db.fetch_df("SELECT {x:Int32}", {"x": 1})
    assert fake.calls[-1][2] == {"x": 1}
    print("  параметры уходят в драйвер, а не склеиваются в текст запроса")

    # Порт и защищённость выводятся из настроек.
    assert ClickHouseDatabase("h", "u").port == 8443
    assert ClickHouseDatabase("h", "u").secure is True
    assert ClickHouseDatabase("h", "u", port=8123).secure is False
    print("  порт 8443 -> HTTPS, 8123 -> HTTP, без ручной настройки")

    assert db.settings["join_use_nulls"] == 1
    print("  join_use_nulls=1 включён: внешние JOIN'ы ведут себя как в MySQL")

    # Ошибки понятные, а не трейсбек драйвера.
    class Broken(FakeClient):
        def query_df(self, *a, **k):
            raise ValueError("Code: 47. Unknown identifier: brnd")

    try:
        ClickHouseDatabase("h", "u", client=Broken()).fetch_df("SELECT brnd FROM t")
    except DatabaseError as error:
        assert "Unknown identifier" in str(error) and "SQL:" in str(error)
        print("  ошибка запроса приходит с текстом SQL, а не голым трейсбеком")
    else:
        raise AssertionError("ошибка запроса не поднялась")

    # Фабрика.
    import os
    os.environ.update({
        "DB_ENGINE": "clickhouse", "CLICKHOUSE_HOST": "ch.example.ru",
        "CLICKHOUSE_USER": "reporting", "CLICKHOUSE_DATABASE": "media",
        "CLICKHOUSE_PORT": "8123", "CLICKHOUSE_SECURE": "false",
    })
    made = create_database()
    assert isinstance(made, ClickHouseDatabase) and made.port == 8123
    assert made.secure is False and made.database == "media"
    print("  create_database() собирается из .env")

    os.environ["DB_ENGINE"] = "mssql"
    os.environ.update({"HOST": "mysql.example.ru", "DB_NAME": "media"})
    assert isinstance(create_database(), MSSQLDatabase)
    print("  DB_ENGINE=mssql возвращает старую базу — откат на одну строку")

    os.environ["DB_ENGINE"] = "clickhouse"
    del os.environ["CLICKHOUSE_HOST"]
    try:
        create_database(host=None)
    except DatabaseError as error:
        assert "CLICKHOUSE_HOST" in str(error)
        print("  без адреса — понятное сообщение, что дописать в .env")

    os.environ["CLICKHOUSE_HOST"] = "ch.example.ru"
    print()


def check_environment_report():
    print("=== разбор окружения ===\n")
    report = describe_environment()
    for key, value in report.items():
        if key != "предупреждения":
            print(f"  {key}: {value}")
    for warning in report["предупреждения"]:
        print(f"  ВНИМАНИЕ: {warning}")
    print()


def main():
    check_engine_behaviour()
    check_linter()
    check_database_layer()
    check_environment_report()
    print("OK")


if __name__ == "__main__":
    main()
