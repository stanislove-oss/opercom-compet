#!/usr/bin/env python3
"""
Проверка готовности проекта к переезду на ClickHouse.

Скрипт одинаково работает во всех трёх проектах автоматизации: он ничего не
знает про конкретные таблицы, а берёт запросы из указанного модуля.

    # только разбор запросов, без подключения
    python scripts/check_clickhouse.py --queries app.sql_dict_connection --offline

    # то же плюс проверка на живом сервере
    python scripts/check_clickhouse.py --queries app.sql_dict_connection

    # что вообще есть в базе
    python scripts/check_clickhouse.py --tables

Что делает:
  1. Показывает, что видно в .env (пароли не печатает).
  2. Подключается и печатает версию сервера.
  3. Разбирает каждый запрос линтером: что упадёт, что тихо изменит результат.
  4. Прогоняет каждый запрос через EXPLAIN PLAN — сервер разбирает его и
     сверяет имена колонок, но НЕ выполняет. Так видно ошибки, не дожидаясь
     полной выгрузки.
  5. Пишет отчёт в reports/clickhouse_report.md.
"""

import argparse
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from functions.db import (  # noqa: E402
    DatabaseError,
    connect_for_discovery,
    describe_environment,
)
from functions.sql_compat import (  # noqa: E402
    SEVERITY_ERROR,
    SEVERITY_SILENT,
    check_identifier_case,
    check_queries,
    collect_queries,
    format_identifier_case,
    format_report,
    summarize,
)

DEFAULT_REPORT = ROOT / "reports" / "clickhouse_report.md"


def load_queries(module_path):
    """Импортирует модуль с запросами и достаёт из него SQL-константы."""
    try:
        module = importlib.import_module(module_path)
    except ImportError as error:
        print(f"Не удалось импортировать {module_path!r}: {error}")
        print("Запускай из корня проекта, где лежит пакет с запросами.")
        return {}

    queries = collect_queries(module)
    if not queries:
        print(f"В {module_path!r} не нашлось строковых констант с SELECT.")
    return queries


def show_environment():
    print("=" * 70)
    print("ОКРУЖЕНИЕ")
    print("=" * 70)

    report = describe_environment()
    for key, value in report.items():
        if key == "предупреждения":
            continue
        print(f"  {key:22s} {value}")

    for warning in report["предупреждения"]:
        print(f"\n  ВНИМАНИЕ: {warning}")
    print()


def connect():
    """
    Подключение. Имя базы знать не обязательно: если в .env его нет или оно
    неверное, подключимся к доступной и скажем об этом — иначе проверка
    прошла бы «успешно», просто не в той базе.
    """
    try:
        db, rejected = connect_for_discovery()
    except DatabaseError as error:
        print(f"  {error}\n")
        return None

    for name, message in rejected:
        print(f"  база {name!r} не подошла: {message}")

    try:
        version = db.server_version()
    except DatabaseError as error:
        print(f"  {error}\n")
        return None

    print(f"  подключение есть, ClickHouse {version}, база {db.database!r}\n")
    if rejected:
        print("  Имя базы не совпало. Посмотреть доступные:\n"
              "      python scripts/dump_schema.py --list\n")
    return db


def show_tables(db, limit=40):
    print("=" * 70)
    print("ТАБЛИЦЫ")
    print("=" * 70)

    try:
        tables = db.tables()
    except DatabaseError as error:
        print(f"  {error}\n")
        return

    if not tables:
        print(f"  в базе {db.database!r} таблиц не видно\n"
              f"  какие базы вообще доступны:\n"
              f"      python scripts/dump_schema.py --list\n")
        return

    for row in tables[:limit]:
        rows = row.get("total_rows")
        rows = f"{rows:,}".replace(",", " ") if rows else "—"
        print(f"  {str(row['name']):44s} {str(row['engine']):18s} строк: {rows}")

    if len(tables) > limit:
        print(f"  … ещё {len(tables) - limit}")
    print()


def lint(queries):
    print("=" * 70)
    print("РАЗБОР ЗАПРОСОВ")
    print("=" * 70)
    print()

    report = check_queries(queries)
    print(format_report(report))

    print("-" * 70)
    print("РЕГИСТР ИМЁН")
    print("-" * 70)
    conflicts = check_identifier_case(queries)
    print(format_identifier_case(conflicts))

    counts = summarize(report)
    print(f"  Итого: упадёт — {counts[SEVERITY_ERROR]}, "
          f"тихо изменит результат — {counts[SEVERITY_SILENT]}\n")

    return report, conflicts


def dry_run(db, queries):
    print("=" * 70)
    print("ПРОВЕРКА НА СЕРВЕРЕ (EXPLAIN PLAN — запросы не выполняются)")
    print("=" * 70)

    results = {}
    for name, sql in queries.items():
        try:
            db.dry_run(sql)
            results[name] = None
            print(f"  ok    {name}")
        except DatabaseError as error:
            message = str(error).split("Ошибка:")[-1].strip()
            results[name] = message
            print(f"  ОШИБКА {name}")
            print(f"         {message[:160]}")
    print()
    return results


def write_report(path, queries, lint_report, dry_results, environment, conflicts=()):
    lines = ["# Готовность к переезду на ClickHouse\n"]

    lines.append("## Окружение\n")
    lines.append("| параметр | значение |")
    lines.append("| --- | --- |")
    for key, value in environment.items():
        if key != "предупреждения":
            lines.append(f"| {key} | {value} |")
    for warning in environment.get("предупреждения", []):
        lines.append(f"\n> {warning}")

    counts = summarize(lint_report)
    lines.append("\n## Итог\n")
    lines.append(f"- запросов проверено: **{len(queries)}**")
    lines.append(f"- упадёт: **{counts[SEVERITY_ERROR]}**")
    lines.append(f"- тихо изменит результат: **{counts[SEVERITY_SILENT]}**")

    if dry_results:
        broken = [n for n, e in dry_results.items() if e]
        lines.append(f"- не компилируется на сервере: **{len(broken)}**")

    if conflicts:
        lines.append("\n## Имена, различающиеся только регистром\n")
        lines.append("В SQL Server регистр имён не важен, в ClickHouse важен — "
                     "неверное написание даст «Unknown expression identifier».\n")
        lines.append("| имя | написания | где встречается |")
        lines.append("| --- | --- | --- |")
        for item in conflicts:
            for form, where in item["variants"].items():
                lines.append(f"| {item['identifier']} | `{form}` | {', '.join(where)} |")

    lines.append("\n## По запросам\n")
    for name in queries:
        lines.append(f"### {name}\n")

        findings = lint_report.get(name, [])
        if findings:
            lines.append("| важность | что | нашлось | как быть |")
            lines.append("| --- | --- | --- | --- |")
            seen = set()
            for item in findings:
                if item["code"] in seen:
                    continue
                seen.add(item["code"])
                lines.append(f"| {item['severity']} | {item['what']} | "
                             f"`{item['fragment']}` | {item['fix']} |")
        else:
            lines.append("Замечаний нет.")

        if dry_results and dry_results.get(name):
            lines.append(f"\n**Сервер не принял запрос:** `{dry_results[name][:300]}`")
        elif dry_results and name in dry_results:
            lines.append("\nСервер запрос принимает.")
        lines.append("")

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", default=None,
                        help="модуль с SQL-константами, например app.sql_dict_connection")
    parser.add_argument("--offline", action="store_true",
                        help="не подключаться, только разобрать запросы")
    parser.add_argument("--tables", action="store_true", help="показать таблицы базы")
    parser.add_argument("--table", default=None, help="показать колонки таблицы")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    show_environment()
    environment = describe_environment()

    db = None
    if not args.offline:
        print("=" * 70)
        print("ПОДКЛЮЧЕНИЕ")
        print("=" * 70)
        db = connect()

    if db and (args.tables or args.table is None and args.queries is None):
        show_tables(db)

    if db and args.table:
        print(f"Колонки {args.table}:")
        for column in db.columns(args.table):
            print(f"  {column['name']:36s} {column['type']}")
        print()

    queries, lint_report, dry_results, conflicts = {}, {}, {}, []

    if args.queries:
        queries = load_queries(args.queries)
        if queries:
            lint_report, conflicts = lint(queries)
            if db:
                dry_results = dry_run(db, queries)

            write_report(args.report, queries, lint_report, dry_results,
                         environment, conflicts)
            print(f"Отчёт: {args.report}")

            counts = summarize(lint_report)
            broken = [n for n, e in dry_results.items() if e]
            if counts[SEVERITY_ERROR] or broken:
                sys.exit(1)

    if db:
        db.close()


if __name__ == "__main__":
    main()
