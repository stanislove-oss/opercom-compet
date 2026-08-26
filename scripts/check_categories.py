#!/usr/bin/env python3
"""
Где в ClickHouse лежат поля справочника: retail_category, message_type и прочие.

Отбор отчёта держится на полях Google-таблицы: advertiser_type,
retail_category, include_exclude, message_type, delivery, competitor. Чтобы
отказаться от таблицы, надо знать, какие колонки базы им соответствуют.

В самих таблицах (media_costs_union, reg_tv) осмысленных имён нет — есть
`category_1` … `category_25`. Зато в базе лежат представления
(reg_tv_weekly_view и подобные), где те же колонки уже переименованы. Значит
соответствие не надо угадывать: оно записано в определении представления,
и скрипт его оттуда читает.

    python scripts/check_categories.py
    python scripts/check_categories.py --values          # ещё и значения колонок
    python scripts/check_categories.py --database mediascope_x5_big_v23

Что делать с результатом: подставить найденные имена в запросы вместо мёржа
со справочником. Пока соответствие не подтверждено значениями, менять запросы
не стоит — `--values` показывает, что реально лежит в колонке.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sql_dict_connection import COST_TABLE, PERIOD_FROM  # noqa: E402

#: Поля, которые прежде приходили из Google-таблицы.
DICTIONARY_COLUMNS = (
    "adId", "media_type", "advertiser_type", "advertiser_main", "brand_main",
    "competitor", "category", "include_exclude", "retail_category", "delivery",
    "product_type", "message_type", "loyalty_category",
)
from functions.db import DatabaseError, create_database  # noqa: E402

#: Поля справочника, ради которых всё это и делается. Порядок как в отчёте:
#: сначала те, что режут выгрузку, потом те, что делят по разрезам.
WANTED = (
    "advertiser_type",
    "retail_category",
    "include_exclude",
    "message_type",
    "delivery",
    "competitor",
    "category",
    "product_type",
    "loyalty_category",
    "brand_main",
    "advertiser_main",
)

#: `category_5 AS segment` в тексте представления.
ALIAS = re.compile(r"\b(category_\d+)\s+AS\s+[`\"]?(\w+)[`\"]?", re.I)


def views_sql(database):
    return ("SELECT name FROM system.tables "
            "WHERE database = {db:String} AND engine LIKE '%View%' ORDER BY name")


def columns_sql():
    return ("SELECT name FROM system.columns "
            "WHERE database = {db:String} AND table = {tbl:String} ORDER BY position")


def mapping_from_views(db, database):
    """Соответствие category_N -> осмысленное имя, из определений представлений."""
    views = [row["name"] for row in db.fetch_all(views_sql(database), {"db": database})]
    if not views:
        return {}, []

    mapping, conflicts = {}, []
    for view in views:
        statement = db.fetch_all(f"SHOW CREATE TABLE {database}.`{view}`")
        text = statement[0][next(iter(statement[0]))] if statement else ""
        for column, alias in ALIAS.findall(text):
            known = mapping.get(column)
            if known and known[0] != alias:
                conflicts.append((column, known[0], known[1], alias, view))
                continue
            mapping.setdefault(column, (alias, view))
    return mapping, views


def values_sql(table, column, period_from, top):
    return f"""
SELECT {column} AS value, count() AS rows
FROM {table}
WHERE researchDate >= '{period_from}'
GROUP BY value
ORDER BY rows DESC
LIMIT {top}
"""


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default=None,
                        help="база ClickHouse; по умолчанию из .env")
    parser.add_argument("--table", default=COST_TABLE,
                        help=f"таблица, где смотреть значения (по умолчанию {COST_TABLE})")
    parser.add_argument("--values", action="store_true",
                        help="показать значения найденных колонок")
    parser.add_argument("--top", type=int, default=8,
                        help="сколько самых частых значений печатать")
    args = parser.parse_args()

    try:
        db = create_database(engine="clickhouse",
                             **({"database": args.database} if args.database else {}))
    except DatabaseError as error:
        sys.exit(str(error))

    database = args.database or db.database

    try:
        print(f"База: {database}\n")

        mapping, views = mapping_from_views(db, database)
        if not views:
            print("Представлений в базе нет — соответствие читать негде.")
            print("Тогда остаётся смотреть значения: --values\n")
        else:
            print(f"Представления, из которых читаем соответствие: {', '.join(views)}\n")

        print("=== Поля справочника в колонках базы ===")
        by_alias = {alias: (column, view) for column, (alias, view) in mapping.items()}
        table_columns = {row["name"] for row in
                         db.fetch_all(columns_sql(), {"db": database, "tbl": args.table})}

        for name in WANTED:
            if name in table_columns:
                print(f"  {name:<20} -> {name} (колонка так и называется)")
            elif name in by_alias:
                column, view = by_alias[name]
                found = "есть" if column in table_columns else "НЕТ в этой таблице"
                print(f"  {name:<20} -> {column}  (из {view}; в {args.table}: {found})")
            else:
                print(f"  {name:<20} -> не нашлось")

        missing = [name for name in DICTIONARY_COLUMNS
                   if name not in table_columns and name not in by_alias
                   and name not in ("adId", "media_type")]
        if missing:
            print(f"\n  Не нашлось совсем: {', '.join(missing)}.")
            print("  Эти поля отчёт берёт из Google-таблицы, и без них отказаться")
            print("  от неё не получится — либо искать в других представлениях,")
            print("  либо спрашивать владельцев базы.")
        print()

        if args.values:
            print(f"=== Что лежит в колонках, таблица {args.table} ===")
            for name in WANTED:
                column = name if name in table_columns else (
                    by_alias.get(name, (None, None))[0])
                if not column or column not in table_columns:
                    continue
                print(f"\n  {name} ({column}):")
                rows = db.fetch_all(values_sql(args.table, column, PERIOD_FROM, args.top))
                for row in rows:
                    print(f"    {str(row['value'])[:48]:<50} {row['rows']:>12,}")
            print()

    except DatabaseError as error:
        sys.exit(str(error))
    finally:
        db.close()


if __name__ == "__main__":
    main()
