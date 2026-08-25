#!/usr/bin/env python3
"""
Прогон запросов проекта на настоящем движке ClickHouse — без сервера.

Схема берётся из reports/clickhouse_schema.md — это дамп настоящей базы,
снятый scripts/dump_schema.py. Имена и типы колонок в нём настоящие, так что
проверяется не только синтаксис, но и то, что колонки действительно есть и
называются именно так. Регистр имён ClickHouse различает, и adID против adId
здесь поймается ровно так же, как на сервере.

    pip install chdb
    python scripts/verify_queries.py

Чего проверка НЕ заменяет: данных. Строки-примеры выдуманы, поэтому «ноль
строк в ответе» здесь ничего не значит — фильтры проверяются на сервере.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import chdb.session
except ImportError:
    sys.exit("Нужен chdb: pip install chdb")

from app import sql_dict_connection as clickhouse_queries  # noqa: E402
from functions.sql_compat import (  # noqa: E402
    SEVERITY_ERROR,
    check_queries,
    collect_queries,
    format_report,
)

SCHEMA_DUMP = ROOT / "reports" / "clickhouse_schema.md"
DATABASE = "media"

#: Одна строка-заглушка на таблицу — чтобы запросы отрабатывали на непустых
#: данных. Значения подобраны так, чтобы проходить фильтры запросов.
SAMPLE_VALUES = {
    "researchDate": "'2025-05-01'",
    "adDistributionType": "'N'",
    "adTypeName": "'РОЛИК'",
    "tv_type_ooh_reg": "'РОЛИК'",
    "media_type": "'TV'",
    "media_type_long": "'TV'",
    "media_type_detail": "'TV_NAT'",
    "media_key_id": "'TV_1633629'",
    "estat": "'R'",
    "brand_main": "'ПЯТЕРОЧКА'",
    "advertiser_main": "'X5 GROUP'",
    "advertiser_type": "'PRODUCER'",
    "category_4": "'YES'",
    "category_5": "'ОФФЛАЙН'",
    "category_7": "'ЦЕНОВОЕ ПРОМО'",
    "netName": "'ПЕРВЫЙ КАНАЛ'",
    "companyName": "'ПЕРВЫЙ КАНАЛ (СЕТЕВОЕ ВЕЩАНИЕ)'",
    "regionName": "'СЕТЕВОЕ ВЕЩАНИЕ'",
}


def parse_schema(path):
    """
    Достаёт таблицы и колонки из дампа scripts/dump_schema.py.

    Формат дампа: заголовок '## имя_таблицы', затем таблица markdown
    '| `колонка` | `тип` | описание |'.
    """
    text = Path(path).read_text(encoding="utf-8")
    tables = {}

    for block in text.split("\n## ")[1:]:
        name = block.split("\n", 1)[0].strip()
        if name == "Таблицы" or not re.fullmatch(r"\w+", name):
            continue

        # Только шапка с колонками — до блока «Примеры значений».
        head = block.split("**Примеры значений**")[0]
        columns = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \|", head, re.M)
        if columns:
            tables[name] = columns

    return tables


def schema_database(path):
    """Имя базы из заголовка дампа: «# Структура базы ClickHouse `имя`»."""
    first_line = Path(path).read_text(encoding="utf-8").split("\n", 1)[0]
    found = re.search(r"`([^`]+)`", first_line)
    return found.group(1) if found else DATABASE


def create_schema(session, database, tables):
    """Создаёт базу под её настоящим именем — так работают имена с точкой.

    Данные проекта лежат в нескольких базах, и одна и та же таблица в них
    может быть разной: у reg_tv в v22 пятьдесят две колонки рейтингов,
    в v23 — две. Поэтому каждая база создаётся отдельно, а запрос вида
    `FROM mediascope_x5_big_v23.media_costs_union` попадает ровно туда,
    куда попадёт и на сервере.
    """
    session.query(f"CREATE DATABASE IF NOT EXISTS `{database}`")

    for name, columns in tables.items():
        body = ", ".join(f"`{column}` {type_}" for column, type_ in columns)
        session.query(f"CREATE TABLE `{database}`.`{name}` ({body}) ENGINE = Memory")

        values = []
        for column, type_ in columns:
            if column in SAMPLE_VALUES:
                values.append(SAMPLE_VALUES[column])
            elif type_.startswith(("Int", "UInt", "Float")):
                values.append("1")
            elif type_ == "Date":
                values.append("'2025-05-01'")
            else:
                values.append("''")
        session.query(
            f"INSERT INTO `{database}`.`{name}` VALUES ({', '.join(values)})")


#: Имя таблицы после FROM — с базой через точку или без неё.
TABLE_IN_QUERY = re.compile(r"\bFROM\s+`?([\w.]+)`?", re.I)


def stand_in_databases(session, queries, tables, dumped_databases):
    """
    Создаёт заместителей для баз, которые запросы называют, а дампа нет.

    Зачем: отчёт берёт затраты из соседней витрины (COST_TABLE с именем базы),
    а снят дамп только основной. Без заместителя четыре запроса затрат
    не проверяются вовсе — движок падает на «Database does not exist»
    ещё до разбора SQL.

    Заместитель — это ТА ЖЕ таблица из снятой базы под другим именем базы.
    Так проверяется текст запроса: имена колонок, кавычки, регистр, GROUP BY.
    Так НЕ проверяется, что в настоящей соседней базе эта таблица устроена
    так же — про это скрипт говорит отдельной строкой, а окончательный ответ
    даёт только сервер:
        python scripts/check_clickhouse.py --queries app.sql_dict_connection

    Возвращает список пар (какая база, чем заместили).
    """
    referenced = set()
    for sql in queries.values():
        referenced.update(TABLE_IN_QUERY.findall(sql))

    created = []
    for full_name in sorted(referenced):
        if "." not in full_name:
            continue
        database, _, table = full_name.partition(".")
        if database in dumped_databases or full_name in tables:
            continue
        columns = tables.get(table)
        if not columns:
            continue

        create_schema(session, database, {table: columns})
        tables[full_name] = columns
        created.append((full_name, table))

    return created


def table_names(sql):
    """Имена таблиц из запроса, без имени базы: other_media.digital -> digital."""
    return {match.split(".")[-1] for match in TABLE_IN_QUERY.findall(sql)}


def missing_tables(queries, known):
    """Таблицы, на которые ссылаются запросы, но которых в дампах нет.

    known — имена и с базой (`v23.media_costs_union`), и без неё: запрос
    может ссылаться на таблицу любым из двух способов.
    """
    referenced = set()
    for sql in queries.values():
        referenced.update(TABLE_IN_QUERY.findall(sql))
    return sorted(name for name in referenced
                  if name not in known and name.split(".")[-1] not in known)


def run(session, sql):
    try:
        return None, str(session.query(sql, "CSV")).strip()
    except Exception as error:
        return str(error).split("\n")[0][:160], None


def schema_dumps():
    """Все снятые схемы из reports/.

    Данные проекта лежат в двух базах — своей и соседней с диджиталом, —
    поэтому дампов бывает несколько. Берём все: таблицы из них просто
    складываются, и запрос к любой базе есть чем проверить.
    """
    found = sorted(path for path in (ROOT / "reports").glob("*schema*.md"))
    return found or ([SCHEMA_DUMP] if SCHEMA_DUMP.exists() else [])


def main():
    dumps = schema_dumps()
    if not dumps:
        sys.exit(
            f"Нет дампа схемы: {SCHEMA_DUMP}\n"
            f"Сними его с боевой базы:  python scripts/dump_schema.py"
        )

    session = chdb.session.Session()
    tables, default_database = {}, None
    for dump in dumps:
        database = schema_database(dump)
        parsed = parse_schema(dump)
        create_schema(session, database, parsed)
        default_database = default_database or database

        for name, columns in parsed.items():
            tables[f"{database}.{name}"] = columns
            # Имя без базы — для запросов, которые её не указывают. Первый
            # дамп выигрывает: это база из .env, к ней и идут такие запросы.
            tables.setdefault(name, columns)

    print("Схема из " + ", ".join(str(dump.relative_to(ROOT)) for dump in dumps) + ":")
    for dump in dumps:
        database = schema_database(dump)
        count = len([key for key in tables if key.startswith(f"{database}.")])
        print(f"  {database}: таблиц {count}"
              + ("  (база по умолчанию)" if database == default_database else ""))
    print()

    # Запросы без имени базы должны попадать туда же, куда на сервере.
    session.query(f"USE `{default_database}`")

    queries = collect_queries(clickhouse_queries)
    print(f"Запросов в app/sql_dict_connection.py: {len(queries)}\n")

    dumped = {schema_database(dump) for dump in dumps}
    stand_ins = stand_in_databases(session, queries, tables, dumped)
    if stand_ins:
        print("=" * 70)
        print("ЗАМЕСТИТЕЛИ: базы нет в дампе, взята одноимённая таблица из снятой")
        print("=" * 70)
        for full_name, table in stand_ins:
            print(f"  {full_name}  <-  {default_database}.{table}")
        print("  Проверяется текст запроса, а не устройство настоящей базы.")
        print("  Снять её схему:   python scripts/dump_schema.py --database <имя>")
        print("  Проверить на сервере:")
        print("      python scripts/check_clickhouse.py --queries app.sql_dict_connection\n")

    absent = missing_tables(queries, tables)
    if absent:
        print("=" * 70)
        print("ТАБЛИЦ НЕТ В ДАМПЕ — проверить нечем")
        print("=" * 70)
        for name in absent:
            print(f"  {name}")
        print("  Их запросы ниже будут пропущены. Найти таблицу по всем базам:")
        print("      python scripts/dump_schema.py --find <часть имени>\n")

    print("=" * 70)
    print("ЛИНТЕР")
    print("=" * 70)
    report = check_queries(queries)
    errors = sum(1 for items in report.values()
                 for i in items if i["severity"] == SEVERITY_ERROR)
    print(format_report(report))
    assert errors == 0, f"в запросах осталось критичное: {errors}"

    print("=" * 70)
    print("ВЫПОЛНЕНИЕ НА ДВИЖКЕ")
    print("=" * 70)

    failures, skipped = [], []
    for name, sql in queries.items():
        if table_names(sql) & set(absent):
            skipped.append(name)
            print(f"  пропуск {name}  (таблицы нет в дампе)")
            continue

        error, result = run(session, sql)
        if error:
            failures.append((name, error))
            print(f"  ОШИБКА {name}\n         {error}")
        else:
            rows = len([r for r in result.splitlines() if r.strip()])
            print(f"  ok     {name}  (строк в ответе: {rows})")
    print()

    print("=" * 70)
    print("ЛОВУШКА РЕГИСТРА: adTypeName в базе прописными")
    print("=" * 70)
    for label, condition in (
        ("adTypeName = 'ролик' (как в SQL Server)", "adTypeName = 'ролик'"),
        ("lowerUTF8(adTypeName) = 'ролик' (как надо)", "lowerUTF8(adTypeName) = 'ролик'"),
    ):
        _, value = run(session, f"SELECT count() FROM nat_tv WHERE {condition}")
        print(f"  {label:44s} -> строк: {value}")
    print("  Запрос не падает — просто возвращает ноль строк.\n")

    print("=" * 70)
    print("LOWER ПРОТИВ lowerUTF8 НА КИРИЛЛИЦЕ")
    print("=" * 70)
    for label, expression in (("LOWER (как в SQL Server)", "LOWER(netName)"),
                              ("lowerUTF8 (как надо)", "lowerUTF8(netName)")):
        _, value = run(session, f"SELECT {expression} FROM nat_tv LIMIT 1")
        print(f"  {label:26s} -> {value}")
    print()

    assert not failures, f"запросы не выполнились: {failures}"

    print("Все проверенные запросы выполняются на движке ClickHouse.")
    if skipped:
        print(f"Не проверено (нет таблицы в дампе): {', '.join(skipped)}")
    print("\nОсталось проверить на боевом сервере — там настоящие данные:")
    print("  python scripts/check_clickhouse.py --queries app.sql_dict_connection\n")
    print("OK")


if __name__ == "__main__":
    main()
