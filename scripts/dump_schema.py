#!/usr/bin/env python3
"""
Выгружает структуру базы ClickHouse в читаемый файл.

Ничего не меняет и тяжёлых запросов не делает: только список таблиц, колонки
с типами и несколько строк-примеров. Результат — markdown-файл, который можно
прочитать самому или прислать целиком.

    # если имя базы неизвестно — начать отсюда: покажет, что вообще доступно
    python scripts/dump_schema.py --list

    # в какой базе лежит нужная таблица
    python scripts/dump_schema.py --find nat_tv

    python scripts/dump_schema.py

    # только интересующие таблицы
    python scripts/dump_schema.py --tables nat_tv,big_tv,reg_tv,media_cost_union

    # какие значения встречаются в колонке (для фильтров)
    python scripts/dump_schema.py --values nat_tv.prj_name,media_cost_union.estat

CLICKHOUSE_DATABASE в .env можно не заполнять: скрипт подключится к любой
доступной базе, потому что список баз и таблиц лежит в system.* и виден
отовсюду.

Файл можно скопировать в любой из трёх проектов — из проекта он берёт только
подключение (functions/db.py), а если его рядом нет, работает напрямую через
clickhouse-connect.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "reports" / "clickhouse_schema.md"

#: Сколько строк-примеров показывать. Больше не нужно, а нагрузка растёт.
SAMPLE_ROWS = 3

#: Сколько самых частых значений показывать для --values.
TOP_VALUES = 15


def connect(args):
    """
    Подключение: из проекта, если он рядом, иначе напрямую.

    Имя базы знать не обязательно. Если в .env его нет или оно неверное,
    подключаемся к любой доступной — список баз и таблиц лежит в system.*
    и виден из любой базы. Отвергнутые имена возвращаем, чтобы сказать
    об этом вслух, а не молча подсунуть не ту базу.
    """
    try:
        from functions.db import connect_for_discovery
        overrides = {
            key: value for key, value in
            dict(host=args.host, port=args.port, user=args.user,
                 password=args.password, database=args.database).items()
            if value is not None
        }
        return connect_for_discovery(**overrides)
    except ImportError:
        pass

    import clickhouse_connect

    # functions/db.py рядом нет — значит и .env никто не прочитал.
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
    except ImportError:
        pass

    for name, variable in (("host", "CLICKHOUSE_HOST"), ("port", "CLICKHOUSE_PORT"),
                           ("user", "CLICKHOUSE_USER"), ("password", "CLICKHOUSE_PASSWORD"),
                           ("database", "CLICKHOUSE_DATABASE")):
        if getattr(args, name) is None:
            setattr(args, name, os.getenv(variable))

    if not args.host:
        raise RuntimeError(
            "Не задан адрес ClickHouse: ни --host, ни CLICKHOUSE_HOST в окружении."
        )

    class Direct:
        def __init__(self, client, database):
            self.client = client
            self.database = database

        def fetch_all(self, query, params=None):
            result = self.client.query(query, parameters=params)
            return [dict(zip(result.column_names, row)) for row in result.result_rows]

        def execute(self, query, params=None):
            return self.client.command(query, parameters=params)

        def close(self):
            self.client.close()

    port = int(args.port or 8123)
    rejected = []
    for name in dict.fromkeys([n for n in (args.database, "default", "system") if n]):
        try:
            client = clickhouse_connect.get_client(
                host=args.host, port=port, username=args.user or "default",
                password=args.password or "", database=name,
                secure=(port == 8443),
            )
            client.command("SELECT 1")
            return Direct(client, name), rejected
        except Exception as error:
            rejected.append((name, str(error).split("\n")[0][:200]))

    raise RuntimeError(
        "Не удалось подключиться ни к одной базе.\n  "
        + "\n  ".join(f"{name}: {message}" for name, message in rejected)
    )


def collect(db, only_tables=None):
    tables = db.fetch_all(
        "SELECT name, engine, total_rows "
        "FROM system.tables WHERE database = {db:String} ORDER BY name",
        {"db": db.database},
    )

    if only_tables:
        wanted = {t.strip() for t in only_tables}
        tables = [t for t in tables if t["name"] in wanted]

    columns = db.fetch_all(
        "SELECT table, name, type, comment FROM system.columns "
        "WHERE database = {db:String} ORDER BY table, position",
        {"db": db.database},
    )

    by_table = {}
    for row in columns:
        by_table.setdefault(row["table"], []).append(row)

    return tables, by_table


def sample(db, table, columns, limit=SAMPLE_ROWS):
    """Несколько строк-примеров: по ним сразу видно формат значений."""
    names = ", ".join(f"`{c['name']}`" for c in columns)
    try:
        return db.fetch_all(f"SELECT {names} FROM `{table}` LIMIT {limit}")
    except Exception as error:
        return [{"ошибка": str(error).split("\n")[0][:120]}]


def top_values(db, table, column, limit=TOP_VALUES):
    """
    Самые частые значения колонки.

    Считается по первым 200 тысячам строк, а не по всей таблице: нам нужен
    состав значений, а не точная статистика, и так это не нагружает сервер.
    """
    try:
        rows = db.fetch_all(
            f"SELECT `{column}` AS value, count() AS n "
            f"FROM (SELECT `{column}` FROM `{table}` LIMIT 200000) "
            f"GROUP BY value ORDER BY n DESC LIMIT {limit}"
        )
        return [(r["value"], r["n"]) for r in rows]
    except Exception as error:
        return [(f"ошибка: {str(error).split(chr(10))[0][:100]}", 0)]


SYSTEM_DATABASES = ("system", "INFORMATION_SCHEMA", "information_schema")


def list_databases(db):
    """Доступные базы с числом таблиц. В system.* видно только своё, и это к лучшему."""
    if hasattr(db, "databases"):
        return db.databases()

    names = [r["name"] for r in db.fetch_all("SELECT name FROM system.databases ORDER BY name")]
    counts = {
        r["database"]: r for r in db.fetch_all(
            "SELECT database, count() AS tables, sum(total_rows) AS rows "
            "FROM system.tables GROUP BY database"
        )
    }
    return [
        {"name": n,
         "tables": (counts.get(n) or {}).get("tables", 0),
         "rows": (counts.get(n) or {}).get("rows", 0)}
        for n in names if n not in SYSTEM_DATABASES
    ]


def find_table(db, pattern):
    """В какой базе лежит таблица — поиск по части имени сразу во всех базах."""
    if hasattr(db, "find_table"):
        return db.find_table(pattern)

    rows = db.fetch_all(
        "SELECT database, name, engine, total_rows FROM system.tables "
        "WHERE positionCaseInsensitive(name, {pattern:String}) > 0 "
        "ORDER BY database, name",
        {"pattern": pattern},
    )
    return [r for r in rows if r["database"] not in SYSTEM_DATABASES]


def _number(value):
    return f"{value:,}".replace(",", " ") if value else "—"


def print_databases(rows):
    if not rows:
        print("Доступных баз не видно. Похоже, у пользователя нет прав ни на одну —\n"
              "это вопрос к тому, кто выдавал доступ.")
        return
    width = max(len(r["name"]) for r in rows)
    print(f"{'база'.ljust(width)}  таблиц  строк")
    for row in rows:
        print(f"{row['name'].ljust(width)}  {str(row['tables']).rjust(6)}  {_number(row['rows'])}")
    print("\nНужное имя пропиши в .env как CLICKHOUSE_DATABASE.")


def print_found(pattern, rows):
    if not rows:
        print(f"Таблиц с '{pattern}' в имени не нашлось ни в одной доступной базе.")
        return
    print(f"Таблицы с '{pattern}' в имени:\n")
    for row in rows:
        print(f"  {row['database']}.{row['name']}  "
              f"({row['engine']}, строк: {_number(row.get('total_rows'))})")
    databases = {row["database"] for row in rows}
    if len(databases) == 1:
        print(f"\nВсё в одной базе — в .env: CLICKHOUSE_DATABASE={databases.pop()}")


def write(path, database, tables, by_table, samples, values):
    lines = [f"# Структура базы ClickHouse `{database}`\n"]

    lines.append("## Таблицы\n")
    lines.append("| таблица | движок | строк |")
    lines.append("| --- | --- | --- |")
    for table in tables:
        count = table.get("total_rows")
        count = f"{count:,}".replace(",", " ") if count else "—"
        lines.append(f"| `{table['name']}` | {table['engine']} | {count} |")

    for table in tables:
        name = table["name"]
        lines.append(f"\n## {name}\n")

        columns = by_table.get(name, [])
        if not columns:
            lines.append("Колонки не видны — возможно, нет прав.\n")
            continue

        lines.append("| колонка | тип | описание |")
        lines.append("| --- | --- | --- |")
        for column in columns:
            comment = (column.get("comment") or "").replace("|", "/")
            lines.append(f"| `{column['name']}` | `{column['type']}` | {comment} |")

        rows = samples.get(name) or []
        if rows:
            lines.append(f"\n**Примеры значений** (первые {len(rows)} строк):\n")
            lines.append("| колонка | " +
                         " | ".join(f"строка {i + 1}" for i in range(len(rows))) + " |")
            lines.append("| --- " * (len(rows) + 1) + "|")
            for column in columns:
                cells = []
                for row in rows:
                    value = row.get(column["name"], "")
                    cells.append(str(value)[:40].replace("|", "/"))
                lines.append(f"| `{column['name']}` | " + " | ".join(cells) + " |")

    if values:
        lines.append("\n## Какие значения встречаются\n")
        for (table, column), pairs in values.items():
            lines.append(f"\n### {table}.{column}\n")
            lines.append("| значение | сколько раз |")
            lines.append("| --- | --- |")
            for value, count in pairs:
                lines.append(f"| `{value}` | {count} |")

    lines.append("""
---

## Что осталось проверить на боевой базе

Схема отвечает, как называются колонки, но не что в них лежит. Переезд
опирается на четыре допущения — их стоит подтвердить до того, как цифры
уедут в отчёт.

1. **Соседняя витрина затрат.** Затраты берутся из `COST_TABLE`, а он по
   умолчанию указывает в другую базу (`mediascope_x5_big_v23`), потому что
   в основной они заканчиваются раньше. Устроена ли `media_costs_union`
   в ней так же:

       python scripts/dump_schema.py --database mediascope_x5_big_v23

2. **Ключ мёржа.** Выгрузка соединяется со справочником по `media_key_id`.
   Значения в базе и в Google-таблице должны совпадать по форме
   (регистр приводится, остальное — нет). Если не совпадут, мёрж не найдёт
   ни одной строки, и отчёт получится пустым, не упав — ноутбук на этот
   случай падает сам, с явным текстом.

3. **Фильтры estat и cleaning_flag.** В соседнем проекте на этой же базе они
   не режут ничего. Насколько режут на выборке оперкома:

       python scripts/check_filters.py

4. **Совпадают ли цифры со старой базой.** Ради этого прежний набор запросов
   и оставлен рядом:

       python scripts/compare_engines.py --old mssql --new clickhouse
""")

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true",
                        help="показать доступные базы и выйти (если имя базы неизвестно)")
    parser.add_argument("--find", default=None, metavar="ИМЯ",
                        help="найти, в какой базе лежит таблица, и выйти")
    parser.add_argument("--tables", default=None,
                        help="через запятую; по умолчанию все")
    parser.add_argument("--values", default=None,
                        help="через запятую, вида таблица.колонка")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--no-samples", action="store_true",
                        help="не показывать строки-примеры")
    for name in ("host", "port", "user", "password", "database"):
        parser.add_argument(f"--{name}", default=None,
                            help="по умолчанию берётся из .env")
    args = parser.parse_args()

    try:
        db, rejected = connect(args)
    except Exception as error:
        sys.exit(f"Не удалось подключиться: {error}")

    try:
        print(f"ClickHouse {db.execute('SELECT version()')}, база {db.database!r}\n")
    except Exception as error:
        sys.exit(f"Подключение есть, но запрос не прошёл: {error}")

    # Молчать об этом нельзя: иначе выгрузка уйдёт не из той базы, а выглядеть
    # будет как обычная.
    for name, message in rejected:
        print(f"База {name!r} не подошла: {message}")
    if rejected:
        print(f"Поэтому подключился к {db.database!r} — там лежит system.*,\n"
              f"а этого хватает, чтобы посмотреть список баз (--list).\n")

    if args.list:
        print_databases(list_databases(db))
        db.close()
        return

    if args.find:
        print_found(args.find, find_table(db, args.find))
        db.close()
        return

    only = args.tables.split(",") if args.tables else None
    tables, by_table = collect(db, only)
    print(f"Таблиц: {len(tables)}")

    # Просили конкретные таблицы, а их тут нет — почти наверняка база не та.
    # Показываем, где они лежат на самом деле, вместо пустого отчёта.
    if only and not tables:
        print(f"\nВ базе {db.database!r} таких таблиц нет. Ищу по всем доступным:\n")
        for wanted in only:
            print_found(wanted.strip(), find_table(db, wanted.strip()))
            print()
        db.close()
        return

    samples = {}
    if not args.no_samples:
        for table in tables:
            columns = by_table.get(table["name"], [])
            if columns:
                samples[table["name"]] = sample(db, table["name"], columns)
                print(f"  {table['name']}: {len(columns)} колонок")

    values = {}
    if args.values:
        for item in args.values.split(","):
            if "." not in item:
                print(f"  пропущено (нужен вид таблица.колонка): {item}")
                continue
            table, column = item.strip().split(".", 1)
            values[(table, column)] = top_values(db, table, column)
            print(f"  значения {table}.{column}: {len(values[(table, column)])}")

    write(args.output, db.database, tables, by_table, samples, values)
    db.close()

    print(f"\nГотово: {args.output}")
    print("Файл можно прочитать самому или прислать целиком — по нему подставлю "
          "имена колонок в запросы.")


if __name__ == "__main__":
    main()
