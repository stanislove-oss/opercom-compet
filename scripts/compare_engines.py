#!/usr/bin/env python3
"""
Сверяет выгрузки из ClickHouse и SQL Server: где именно разошлись данные.

Сравнивать презентации — поздно: к слайду число уже прошло справочник,
группировки и топ-N, и по расхождению не видно причину. Здесь сравниваются
сами выгрузки, до всякой обработки.

    python scripts/compare_engines.py                    # все шесть запросов
    python scripts/compare_engines.py --queries TV_SQL   # по одному
    python scripts/compare_engines.py --save reports/compare_engines.md

Что показывает по каждому запросу:
  * колонки: чего не хватает и что появилось лишнего — это важнее всего,
    main.py обращается к колонкам по именам;
  * сколько строк стало и какие суммы по числовым колонкам;
  * разбивку по месяцам — видно, разошлось всё или только свежий период.

Запросы тяжёлые: каждый тянет данные с 2024 года, и тянет их дважды — по
разу на базу. Если памяти мало, гоняйте по одному через --queries.

Нужны оба подключения сразу, поэтому в .env должны быть заполнены и
CLICKHOUSE_*, и X5_SQL_* / DIGITAL_SQL_*.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.queries import queries_for  # noqa: E402
from functions.db import DatabaseError, create_database  # noqa: E402

#: Какой запрос из какого подключения берётся. Диджитал живёт отдельно —
#: и в SQL Server это была отдельная база, и в ClickHouse может быть.
#: Профиль подключения на запрос. У оперкома база одна, поэтому профиль
#: у всех общий: переменные ищутся без приставки (CLICKHOUSE_HOST и т.д.).
#: Диджитал сюда не входит — он приходит из Excel с сетевой шары, а не из базы.
QUERY_PROFILES = {
    "TV_SQL": None,
    "RADIO_SQL": None,
    "OOH_SQL": None,
    "PRESS_SQL": None,
    "OPERCOM_TV_RATE_NAT": None,
    "OPERCOM_TV_RATE_REG": None,
}


def fetch(engine, profile, query_name):
    """Выгрузка одним запросом. Ошибку не глушим, но и весь прогон не роняем."""
    db = create_database(engine=engine, profile=profile)
    try:
        queries = queries_for(db.engine)
        if query_name not in queries.names:
            return None, f"запроса {query_name} нет в {queries.source}"
        return db.fetch_df(getattr(queries, query_name)), None
    except DatabaseError as error:
        return None, str(error).split("\n")[0]
    finally:
        db.close()


def month_counts(frame):
    """Строки по месяцам — по колонке date, если она есть."""
    if "date" not in frame.columns:
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().all():
        return None
    return dates.dt.to_period("M").value_counts().sort_index()


#: До скольких различных значений колонка считается справочной. По таким
#: колонкам сравниваются сами значения: расхождение вида «press» против
#: «пресса» не меняет ни строк, ни сумм, но ломает мёрж со справочником
#: и подбор цветов на диаграммах.
CATEGORICAL_LIMIT = 60


def compare_values(old, new, column):
    """Значения, которые появились или пропали в справочной колонке."""
    was = set(old[column].dropna().astype("str"))
    now = set(new[column].dropna().astype("str"))
    if max(len(was), len(now)) > CATEGORICAL_LIMIT:
        return []

    lines = []
    if was - now:
        lines.append(f"  ПРОПАЛИ значения {column}: {', '.join(sorted(was - now))}")
    if now - was:
        lines.append(f"  появились значения {column}: {', '.join(sorted(now - was))}")
    return lines


def compare_frames(old, new):
    """Текст сравнения двух выгрузок одного запроса."""
    lines = []

    missing = [column for column in old.columns if column not in new.columns]
    extra = [column for column in new.columns if column not in old.columns]
    if missing:
        lines.append(f"  КОЛОНОК НЕ ХВАТАЕТ: {', '.join(missing)}")
    if extra:
        lines.append(f"  лишние колонки: {', '.join(extra)}")
    if not missing and not extra:
        lines.append(f"  колонки совпадают ({len(new.columns)} шт.)")

    delta = len(new) - len(old)
    share = f"{delta / len(old) * 100:+.1f}%" if len(old) else "—"
    lines.append(f"  строк: {len(old):,} -> {len(new):,} ({delta:+,}, {share})")

    common = [column for column in old.columns if column in new.columns]
    numeric = [
        column for column in common
        if pd.api.types.is_numeric_dtype(old[column])
        and pd.api.types.is_numeric_dtype(new[column])
    ]
    for column in numeric:
        was, now = float(old[column].sum()), float(new[column].sum())
        share = f"{(now / was - 1) * 100:+.1f}%" if was else "—"
        lines.append(f"  сумма {column}: {was:,.0f} -> {now:,.0f} ({share})")

    for column in common:
        if column in numeric or pd.api.types.is_datetime64_any_dtype(old[column]):
            continue
        lines.extend(compare_values(old, new, column))

    old_months, new_months = month_counts(old), month_counts(new)
    if old_months is not None and new_months is not None:
        months = sorted(set(old_months.index) | set(new_months.index))
        changed = [
            f"{month}: {int(old_months.get(month, 0)):,} -> {int(new_months.get(month, 0)):,}"
            for month in months
            if int(old_months.get(month, 0)) != int(new_months.get(month, 0))
        ]
        if changed:
            lines.append("  месяцы, где строк стало иначе:")
            lines.extend(f"    {item}" for item in changed)
        else:
            lines.append("  по месяцам расхождений нет")

        if new_months.index.max() != old_months.index.max():
            lines.append(
                f"  ПОСЛЕДНИЙ МЕСЯЦ РАЗНЫЙ: было {old_months.index.max()}, "
                f"стало {new_months.index.max()} — расчётный период отчёта сдвинется"
            )

    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", default=None,
                        help="через запятую; по умолчанию все: "
                             + ", ".join(QUERY_PROFILES))
    parser.add_argument("--old", default="mssql", help="прежний движок (по умолчанию mssql)")
    parser.add_argument("--new", default="clickhouse", help="новый движок (по умолчанию clickhouse)")
    parser.add_argument("--save", default=None, metavar="ФАЙЛ",
                        help="записать отчёт в файл")
    args = parser.parse_args()

    names = ([name.strip() for name in args.queries.split(",")]
             if args.queries else list(QUERY_PROFILES))

    unknown = [name for name in names if name not in QUERY_PROFILES]
    if unknown:
        sys.exit(f"Неизвестные запросы: {', '.join(unknown)}. "
                 f"Известные: {', '.join(QUERY_PROFILES)}")

    report = [f"Сверка выгрузок: {args.old} -> {args.new}", ""]
    failed = 0

    for name in names:
        profile = QUERY_PROFILES[name]
        block = [f"=== {name} (профиль {profile}) ==="]

        old, error = fetch(args.old, profile, name)
        new, new_error = (None, None) if error else fetch(args.new, profile, name)

        if error or new_error:
            block.append(f"  {args.old if error else args.new}: {error or new_error}")
            failed += 1
        else:
            block.extend(compare_frames(old, new))

        block.append("")
        report.extend(block)
        # Печатаем сразу: запросы долгие, ждать весь прогон ради вывода незачем.
        print("\n".join(block), flush=True)

    report.append(f"Не удалось сверить запросов: {failed}" if failed
                  else "Сверены все запросы")

    text = "\n".join(report)
    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(text + "\n", encoding="utf-8")
        print(f"\nОтчёт: {args.save}")
    elif failed:
        print(f"\nНе удалось сверить запросов: {failed}")


if __name__ == "__main__":
    main()
