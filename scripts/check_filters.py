#!/usr/bin/env python3
"""
Что лежит в media_costs_union и сколько режут фильтры базы.

Два вопроса, на которые схема не отвечает — в ней видны имена колонок, но не
значения:

1. **Как разложены медиа.** Ключ к справочнику собирается как
   `media_type + adId`, и `media_type` — это `lowerUTF8(media_type_long)`.
   Значения обязаны совпадать с колонкой `media_type` Google-таблицы
   (`tv`, `radio`, `outdoor`, `пресса`). Если не совпадут, мёрж не найдёт
   ни одной строки: отчёт получится пустым, не упав. Здесь же видно, чем
   помечен каждый подтип.

2. **Сколько режут `estat` и `cleaning_flag`.** Этих колонок в SQL Server
   не было, и включать фильтры наугад нельзя: `estat = 'R'` отбрасывает
   виртуальную рекламу (бюджеты станут меньше — это ожидаемо), а
   `cleaning_flag` — служебная чистка базы, которая у нас дублирует работу
   справочника. Скрипт показывает, сколько строк и рублей уходит на каждом.

    python scripts/check_filters.py
    python scripts/check_filters.py --from 2025-01-01
    python scripts/check_filters.py --filters "estat = 'R'" "cleaning_flag = 1"

Считает всё на стороне базы через countIf/sumIf, поэтому быстро и почти
ничего не выкачивает.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sql_dict_connection import (  # noqa: E402
    COST_TABLE,
    PERIOD_FROM,
    REG_TV_TABLE,
)
from functions.db import DatabaseError, create_database  # noqa: E402

#: Фильтры-кандидаты. Задаются как есть, текстом условия.
DEFAULT_FILTERS = ("estat = 'R'", "cleaning_flag = 1")


def media_split_sql(period_from):
    """Раскладка медиа: коды, длинные имена и подтипы с объёмами."""
    return f"""
SELECT
    media_type,
    lowerUTF8(media_type_long) AS media_type_key,
    lowerUTF8(media_type_detail) AS media_type_detail,
    count() AS rows,
    SUM(ConsolidatedCostRUB_disc) AS cost
FROM {COST_TABLE}
WHERE researchDate >= '{period_from}'
GROUP BY media_type, media_type_key, media_type_detail
ORDER BY cost DESC
"""


def filters_sql(table, filters, period_from, metric):
    """Сколько строк и метрики остаётся после каждого фильтра по отдельности."""
    parts = [
        "    count() AS rows_all",
        f"    SUM({metric}) AS metric_all",
    ]
    for index, condition in enumerate(filters):
        parts.append(f"    countIf({condition}) AS rows_{index}")
        parts.append(f"    SUMIf({metric}, {condition}) AS metric_{index}")

    return f"""
SELECT
{',\n'.join(parts)}
FROM {table}
WHERE researchDate >= '{period_from}'
"""


def share(part, whole):
    return f"{part / whole * 100:.1f}%" if whole else "—"


def report_media_split(db, period_from):
    print("=== Раскладка медиа в media_costs_union ===")
    frame = db.fetch_df(media_split_sql(period_from))
    if frame.empty:
        print("  данных нет")
        return

    total = float(frame["cost"].sum())
    print(f"  {'media_type':<12} {'ключ справочника':<20} {'подтип':<22} "
          f"{'строк':>12} {'затраты':>18}  доля")
    for row in frame.itertuples():
        print(f"  {row.media_type:<12} {row.media_type_key:<20} "
              f"{row.media_type_detail:<22} {row.rows:>12,} {row.cost:>18,.0f}  "
              f"{share(float(row.cost), total)}")

    print("\n  Ключ справочника (второй столбец) должен совпадать со значениями")
    print("  media_type в Google-таблице: tv, radio, outdoor, пресса.")
    print("  Диджитала здесь нет: он приходит из Excel с сетевой шары.\n")


def report_filters(db, table, filters, period_from, metric, title):
    print(f"=== {title} ===")
    frame = db.fetch_df(filters_sql(table, filters, period_from, metric))
    if frame.empty:
        print("  данных нет\n")
        return

    row = frame.iloc[0]
    rows_all, metric_all = int(row["rows_all"]), float(row["metric_all"])
    print(f"  без фильтров: строк {rows_all:,}, {metric} {metric_all:,.0f}")

    for index, condition in enumerate(filters):
        rows = int(row[f"rows_{index}"])
        value = float(row[f"metric_{index}"])
        print(f"  {condition:<22} останется строк {rows:>12,} "
              f"({share(rows, rows_all)}), {metric} {value:>18,.0f} "
              f"({share(value, metric_all)})")
    print()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="period_from", default=PERIOD_FROM,
                        help=f"с какой даты считать (по умолчанию {PERIOD_FROM})")
    parser.add_argument("--filters", nargs="+", default=list(DEFAULT_FILTERS),
                        help="условия-кандидаты, как есть")
    parser.add_argument("--database", default=None,
                        help="база ClickHouse; по умолчанию из .env — чтобы сравнить соседние витрины")
    args = parser.parse_args()

    try:
        db = create_database(engine="clickhouse",
                            **({"database": args.database} if args.database else {}))
    except DatabaseError as error:
        sys.exit(str(error))

    try:
        report_media_split(db, args.period_from)
        report_filters(db, COST_TABLE, args.filters, args.period_from,
                       "ConsolidatedCostRUB_disc", "Фильтры на затратах")
        # В reg_tv колонки estat нет — спрашиваем только про то, что есть.
        report_filters(db, REG_TV_TABLE, [f for f in args.filters if "estat" not in f],
                       args.period_from, f"`RtgPer_w_ALL_18+`",
                       "Фильтры на рейтингах регионального ТВ")
    except DatabaseError as error:
        sys.exit(str(error))
    finally:
        db.close()


if __name__ == "__main__":
    main()
