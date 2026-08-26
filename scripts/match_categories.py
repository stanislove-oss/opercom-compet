#!/usr/bin/env python3
"""
Какая category_N соответствует полю справочника — сверкой значений по ключу.

ЗАЧЕМ. Соответствие обычно читается из определений представлений
(scripts/check_categories.py) — там прямо написано `category_4 AS
retail_category`, и гадать не о чем. Этот скрипт нужен, когда так не вышло:
представлений нет, прав на SHOW CREATE нет, или в определении не тот псевдоним.

Тогда остаётся смотреть значения — и вот тут засада: `retail_category`
и `competitor` оба принимают только YES/NO. По набору значений они
неразличимы, и «похоже на нужное» ничего не доказывает.

ЧТО ДЕЛАЕТ СКРИПТ. Сравнивает не наборы значений, а значения ПО КЛЮЧУ.
Google-таблица ещё есть, и в ней для каждого media_key_id записано настоящее
`competitor`. Значит для каждой колонки-кандидата можно посчитать, на какой
доле ключей она совпала со справочником. У правильной колонки совпадение
около 100%, у любой другой — случайное.

    python scripts/match_categories.py --field competitor
    python scripts/match_categories.py --field retail_category   # перепроверить
    python scripts/match_categories.py --field competitor --table nat_tv

Это дешевле, чем строить презентацию на каждом кандидате и сверять слайды:
одна выгрузка вместо полного прогона, и ответ не «похоже», а доля совпадений.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sql_dict_connection import COST_TABLE, PERIOD_FROM  # noqa: E402
from functions.db import DatabaseError, create_database  # noqa: E402

#: Поля справочника, которые имеет смысл искать. Ключ мёржа и то, что и так
#: лежит под своим именем, сюда не входят.
FIELDS = (
    "competitor",
    "retail_category",
    "message_type",
    "delivery",
    "category",
    "product_type",
    "loyalty_category",
)

#: Сколько различных значений может быть у колонки-кандидата. Поля справочника
#: — это категории, а не свободный текст; колонка с тысячей значений заведомо
#: не про то.
MAX_DISTINCT = 60


def normalize(series):
    """Значения к общему виду: регистр и пробелы не должны мешать сравнению."""
    return (
        series.astype("string")
        .str.strip()
        .str.lower()
        .replace({"": pd.NA, "nan": pd.NA, "none": pd.NA})
    )


def agreement(truth, candidate):
    """Доля ключей, где кандидат совпал со справочником.

    Считается только по ключам, где известны оба значения: строки, которых
    в справочнике нет, ничего не говорят о правильности колонки.

    Возвращает (доля, сколько ключей сравнивали).
    """
    both = pd.DataFrame({"truth": truth, "candidate": candidate}).dropna()
    if both.empty:
        return 0.0, 0
    return float((both["truth"] == both["candidate"]).mean()), len(both)


def candidate_columns(db, table, limit=MAX_DISTINCT):
    """Колонки category_N с небольшим набором значений — то есть категории."""
    rows = db.fetch_all(
        "SELECT name FROM system.columns "
        "WHERE database = {db:String} AND table = {tbl:String} "
        "AND name LIKE 'category\\_%' ORDER BY position",
        {"db": table_database(db, table), "tbl": table_name(table)},
    )
    names = [row["name"] for row in rows]
    if not names:
        return []

    counts = ", ".join(f"uniqExact({name}) AS {name}" for name in names)
    stats = db.fetch_all(f"SELECT {counts} FROM {table} WHERE researchDate >= '{PERIOD_FROM}'")
    if not stats:
        return names
    return [name for name in names if 1 < (stats[0].get(name) or 0) <= limit]


def table_database(db, table):
    return table.split(".")[0] if "." in table else db.database


def table_name(table):
    return table.split(".")[-1]


def load_dictionary(url, field):
    """Справочник: ключ -> значение поля. Он здесь и есть источник истины."""
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass

    frame = pd.read_csv(url, low_memory=False)
    if "media_key_id" not in frame.columns:
        raise SystemExit(
            "В справочнике нет колонки media_key_id — сверять по ключу нечем.\n"
            f"Есть: {', '.join(map(str, frame.columns[:20]))}"
        )
    if field not in frame.columns:
        raise SystemExit(f"В справочнике нет колонки {field!r}.")

    frame = frame[["media_key_id", field]].copy()
    frame["keys"] = normalize(frame["media_key_id"])
    frame[field] = normalize(frame[field])
    frame = frame.dropna(subset=["keys"])
    frame = frame[~frame["keys"].duplicated()]
    return frame.set_index("keys")[field]


def load_candidates(db, table, columns):
    """Из базы: ключ -> значение каждой колонки-кандидата, по одной строке на ключ."""
    selected = ",\n    ".join(
        f"any(lowerUTF8({name})) AS {name}" for name in columns
    )
    sql = (
        f"SELECT\n    lowerUTF8(media_key_id) AS keys,\n    {selected}\n"
        f"FROM {table}\n"
        f"WHERE researchDate >= '{PERIOD_FROM}'\n"
        f"GROUP BY keys"
    )
    frame = db.fetch_df(sql)
    return frame.set_index("keys")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--field", default="competitor", choices=FIELDS,
                        help="какое поле справочника ищем (по умолчанию competitor)")
    parser.add_argument("--table", default=COST_TABLE,
                        help=f"где искать (по умолчанию {COST_TABLE})")
    parser.add_argument("--dictionary-url", default=None,
                        help="адрес Google-таблицы; по умолчанию OPERCOM_FIVE_DICT_URL")
    parser.add_argument("--top", type=int, default=8, help="сколько кандидатов показать")
    args = parser.parse_args()

    import os

    url = args.dictionary_url or os.getenv("OPERCOM_FIVE_DICT_URL")
    if not url:
        raise SystemExit(
            "Неизвестен адрес справочника. Передай --dictionary-url или задай\n"
            "OPERCOM_FIVE_DICT_URL в .env — сверять не с чем."
        )

    print(f"Ищем {args.field!r} среди колонок category_N таблицы {args.table}\n")

    truth = load_dictionary(url, args.field)
    print(f"Справочник: {len(truth):,} ключей, "
          f"значения: {', '.join(sorted(set(truth.dropna()))[:6])}\n")

    try:
        db = create_database("clickhouse")
        columns = candidate_columns(db, args.table)
        if not columns:
            raise SystemExit("Колонок category_N с небольшим набором значений не нашлось.")
        print(f"Кандидатов: {len(columns)} ({', '.join(columns)})\n")

        frame = load_candidates(db, args.table, columns)
    except DatabaseError as error:
        raise SystemExit(str(error))
    finally:
        try:
            db.close()
        except Exception:
            pass

    print(f"Из базы: {len(frame):,} ключей\n")

    aligned = truth.reindex(frame.index)
    results = []
    for name in columns:
        share, compared = agreement(aligned, normalize(frame[name]))
        values = sorted(set(normalize(frame[name]).dropna()))[:4]
        results.append((share, compared, name, values))

    results.sort(reverse=True)

    print(f"  {'колонка':<16} {'совпадение':>12} {'сравнили ключей':>18}  значения")
    for share, compared, name, values in results[: args.top]:
        mark = "  <-- это оно" if share > 0.98 else ""
        print(f"  {name:<16} {share:>11.1%} {compared:>18,}  "
              f"{', '.join(map(str, values))[:40]}{mark}")

    best = results[0] if results else None
    print()
    if best and best[0] > 0.98:
        env_name = {"competitor": "COMPETITOR_COLUMN",
                    "retail_category": "RETAIL_CATEGORY_COLUMN",
                    "message_type": "MESSAGE_TYPE_COLUMN",
                    "delivery": "DELIVERY_COLUMN"}.get(args.field)
        print(f"Совпадение {best[0]:.1%} — это {best[2]}.")
        if env_name:
            print(f"Прописать в .env:  {env_name}={best[2]}")
    elif best:
        print(f"Уверенного совпадения нет: лучший кандидат {best[2]} даёт {best[0]:.1%}.")
        print("Возможные причины: ключи справочника и базы разной формы;")
        print("справочник новее или старее выгрузки; поле в базе под другим именем.")
        print("Стоит сначала посмотреть определения представлений:")
        print("    python scripts/check_categories.py")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
