#!/usr/bin/env python3
"""
Размножают ли LEFT JOIN'ы строки в прежних запросах к SQL Server.

ЗАЧЕМ. После переезда сверка показала, что строк стало меньше во ВСЕХ шести
запросах сразу — от -10% до -35%, ровно во всех месяцах. Общего фильтра,
который дал бы такую картину, нет. Зато есть другое общее: у каждого прежнего
запроса от двух до четырёх `LEFT JOIN` к справочникам, а в ClickHouse
справочники растворены в самой таблице и джойнов не осталось ни одного.

    media_tv_costs LEFT JOIN adex_ad_dict_list_tv ON dur.adId = tv_main.adId

Если в справочнике на один adId приходится больше одной строки, такой JOIN
не дополняет строку, а размножает её. И поскольку колонка из справочника
(adStandardDuration, netName, adTypeName) стоит в GROUP BY, копии не
схлопываются, а становятся отдельными строками результата — и их затраты
попадают в сумму по разу на копию.

То есть вопрос стоит не «куда делись строки в ClickHouse», а «не было ли
лишних строк в SQL Server». Скрипт отвечает на него прямо: смотрит сами
справочники и считает, во сколько раз JOIN увеличивает выгрузку.

    python scripts/check_join_fanout.py
    python scripts/check_join_fanout.py --from 2025-01-01 --to 2025-01-31

Работает только со старой базой: DB_ENGINE тут ни при чём, подключение
всегда mssql. Если её уже отключили, проверять нечего — и это само по себе
ответ, сверять будет не с чем.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from functions.db import DatabaseError, create_database, one_line  # noqa: E402

#: Справочник: (таблица, колонка-ключ). Ключ — то, по чему идёт ON.
DICTIONARIES = [
    ("adex_ad_dict_list_tv", "adId"),
    ("adex_company_dict_tv", "cid"),
    ("adex_regions_dict", "regionId"),
    ("adex_ad_dict_list_radio", "adId"),
    ("adex_company_dict_radio", "cid"),
    ("adex_ad_type_dict_radio", "ad_type_custom"),
    ("adex_ad_type_dict_outdoor", "ad_type_custom"),
    ("adex_ad_type_dict_press", "ad_type_custom"),
    ("adex_company_dict_press", "cid"),
    ("tv_index_ad_type_dict", "adTypeId"),
    ("tv_index_region_dict", "regionId"),
]

#: Запрос -> (таблица затрат/рейтингов, список (справочник, ключ слева, ключ справа)).
#: Списано с app/sql_dict_connection_mssql.py.
QUERIES = {
    "TV_SQL": ("media_tv_costs", [
        ("adex_company_dict_tv", "cid", "cid"),
        ("adex_ad_dict_list_tv", "adId", "adId"),
        ("adex_regions_dict", "regionId", "regionId"),
    ]),
    "RADIO_SQL": ("media_radio_costs", [
        ("adex_ad_type_dict_radio", "ad_type_custom", "ad_type_custom"),
        ("adex_company_dict_radio", "cid", "cid"),
        ("adex_ad_dict_list_radio", "adId", "adId"),
    ]),
    "OOH_SQL": ("media_outdoor_costs", [
        ("adex_ad_type_dict_outdoor", "ad_type_custom", "ad_type_custom"),
        ("adex_regions_dict", "regionId", "regionId"),
    ]),
    "PRESS_SQL": ("media_press_costs", [
        ("adex_ad_type_dict_press", "ad_type_custom", "ad_type_custom"),
        ("adex_company_dict_press", "cid", "cid"),
    ]),
    "OPERCOM_TV_RATE_NAT": ("nat_tv_simple", [
        ("tv_index_ad_type_dict", "adTypeId", "adTypeId"),
        ("tv_index_region_dict", "regionId", "regionId"),
    ]),
    "OPERCOM_TV_RATE_REG": ("reg_tv_simple", [
        ("tv_index_ad_type_dict", "adTypeId", "adTypeId"),
        ("tv_index_region_dict", "regionId", "regionId"),
    ]),
}


def scalar(db, sql):
    rows = db.fetch_all(sql)
    if not rows:
        return None
    return list(rows[0].values())[0]


def check_dictionaries(db):
    """Есть ли в справочниках повторы по ключу JOIN."""
    print("=" * 72)
    print("СПРАВОЧНИКИ: сколько строк приходится на один ключ")
    print("=" * 72)
    print(f"  {'справочник':<28} {'ключ':<16} {'строк':>10} {'ключей':>10}  во сколько раз")

    guilty, checked, failures = [], 0, []
    for table, key in DICTIONARIES:
        try:
            rows = scalar(db, f"SELECT COUNT(*) FROM {table}")
            keys = scalar(db, f"SELECT COUNT(DISTINCT {key}) FROM {table}")
        except DatabaseError as error:
            failures.append(one_line(error, 200))
            print(f"  {table:<28} {key:<16} {'—':>10} {'—':>10}  {one_line(error, 60)}")
            continue

        if not keys:
            continue
        checked += 1
        ratio = rows / keys
        mark = "  <-- размножает" if ratio > 1.0001 else ""
        if ratio > 1.0001:
            guilty.append((table, key, ratio))
        print(f"  {table:<28} {key:<16} {rows:>10,} {keys:>10,}  ×{ratio:.3f}{mark}")

    print()
    if not checked:
        # Ни один справочник не посмотрели — молчание тут значит «не проверено»,
        # а не «повторов нет». Сказать второе было бы прямой дезинформацией.
        raise DatabaseError(
            "Ни один справочник не удалось прочитать, проверка не состоялась.\n  "
            + (failures[0] if failures else "причина неизвестна")
        )

    if guilty:
        print("  Справочники с повторами найдены. Каждая лишняя строка справочника")
        print("  превращает одну строку выгрузки в несколько, и её затраты попадают")
        print("  в сумму по разу на копию. В ClickHouse таких JOIN'ов нет вовсе,")
        print("  поэтому там строк меньше — и, вероятно, правильнее.\n")
    else:
        print("  Повторов нет: JOIN'ы строки не размножают, причина расхождения")
        print("  в другом. Дальше стоит смотреть на сами данные — check_filters.py")
        print("  и сверку по одному месяцу.\n")

    return guilty


def check_queries(db, period_from, period_to):
    """Во сколько раз JOIN'ы увеличивают выгрузку на выбранном отрезке."""
    print("=" * 72)
    print(f"ЗАПРОСЫ: строк до и после JOIN'ов ({period_from} .. {period_to})")
    print("=" * 72)

    where = f"WHERE base.researchDate >= '{period_from}' AND base.researchDate <= '{period_to}'"

    for name, (table, joins) in QUERIES.items():
        try:
            plain = scalar(db, f"SELECT COUNT(*) FROM {table} AS base {where}")
        except DatabaseError as error:
            print(f"\n=== {name} ===\n  {one_line(error, 140)}")
            continue

        joined_sql = f"SELECT COUNT(*) FROM {table} AS base"
        for index, (dictionary, left, right) in enumerate(joins):
            joined_sql += f"\n  LEFT JOIN {dictionary} AS d{index} ON d{index}.{right} = base.{left}"
        joined_sql += f"\n{where}"

        try:
            joined = scalar(db, joined_sql)
        except DatabaseError as error:
            print(f"\n=== {name} ===\n  {one_line(error, 140)}")
            continue

        ratio = joined / plain if plain else 0
        print(f"\n=== {name} ===  {table}")
        print(f"  без JOIN'ов: {plain:>12,}")
        print(f"  с JOIN'ами:  {joined:>12,}   ×{ratio:.3f}")
        if ratio > 1.0001:
            extra = joined - plain
            print(f"  лишних строк: {extra:,} ({extra / joined * 100:.1f}% выгрузки) —"
                  f" это и есть разница со старой базой")

    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="period_from", default="2025-01-01",
                        help="начало отрезка для подсчёта строк (по умолчанию 2025-01-01)")
    parser.add_argument("--to", dest="period_to", default="2025-01-31",
                        help="конец отрезка (по умолчанию 2025-01-31)")
    parser.add_argument("--dictionaries-only", action="store_true",
                        help="только справочники, без тяжёлого подсчёта по запросам")
    args = parser.parse_args()

    try:
        db = create_database("mssql")
    except DatabaseError as error:
        print(f"Не удалось подключиться к старой базе: {error}", file=sys.stderr)
        print("\nПодключение здесь всегда mssql — сверять новую базу саму с собой"
              "\nсмысла нет. Заполни MSSQL_* в .env.", file=sys.stderr)
        return 1

    try:
        guilty = check_dictionaries(db)
    except DatabaseError as error:
        print(f"{error}", file=sys.stderr)
        print("\nПодключение здесь всегда mssql — проверять размножение строк"
              "\nимеет смысл только на той базе, где эти JOIN'ы были.", file=sys.stderr)
        return 1

    if not args.dictionaries_only:
        check_queries(db, args.period_from, args.period_to)

    print("=" * 72)
    print("ЧТО ДАЛЬШЕ")
    print("=" * 72)
    if guilty:
        print("  Строк в ClickHouse меньше потому, что в SQL Server их было больше")
        print("  положенного. Сверять надо не количество строк, а суммы затрат")
        print("  и рейтингов по месяцам — и на старой стороне брать выгрузку")
        print("  с DISTINCT по ключу размещения, иначе сравниваются разные вещи.")
    else:
        print("  JOIN'ы ни при чём. Дальше по порядку:")
        print("    python scripts/check_filters.py     estat и cleaning_flag")
        print("    python scripts/compare_engines.py --queries TV_SQL")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
