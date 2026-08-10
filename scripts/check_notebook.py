#!/usr/bin/env python3
"""Статическая проверка ноутбука перед деплоем. Ничего не выполняет.

Ловит четыре класса регрессий:

1. code-ячейка без управляющего тега (новая ячейка уехала бы в прод молча);
2. синтаксическая ошибка в боевой ячейке;
3. хардкод, который должен был переехать в ячейку параметров (Z:\\, dummy_df,
   main_2_filled.pptx, имя шаблона);
4. имя, которое боевая ячейка читает, но никто из боевых ячеек не определяет —
   типичный симптом «ячейку с определением пометили skip».

Код возврата 0 — всё в порядке, 1 — есть проблемы.

    python scripts/check_notebook.py
    python scripts/check_notebook.py --data-source csv
"""

from __future__ import annotations

import argparse
import ast
import builtins
import io
import sys
import tokenize
from pathlib import Path

#: Ноутбук использует вложенные кавычки в f-строках (PEP 701) — это Python 3.12+.
#: На более старом интерпретаторе ячейки не разберутся и проверка бессмысленна.
MIN_PYTHON = (3, 12)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opercom import tags as T  # noqa: E402
from opercom.notebook_runner import load_notebook  # noqa: E402

NOTEBOOK = Path(__file__).resolve().parent.parent / "main_2.ipynb"

# Строки, которых не должно остаться в боевых ячейках: всё это переехало в
# ячейку параметров и подставляется рантаймом.
FORBIDDEN_LITERALS = [
    ("Z:\\", "путь к сетевой шаре — используй MMO_DATA_ROOT / DIGITAL_DATA_ROOT"),
    ("'dummy_df", "путь к снимкам данных — используй DUMMY_DF_ROOT"),
    ('"dummy_df', "путь к снимкам данных — используй DUMMY_DF_ROOT"),
    ("main_2_filled.pptx", "имя файла результата — используй OUTPUT_PPTX"),
    ("_fin_named.pptx", "имя шаблона — используй TEMPLATE_PPTX"),
]

#: Имена, которые ячейка параметров и рантайм гарантируют до первой боевой ячейки.
INJECTED_NAMES = {
    "TEMPLATE_PPTX",
    "OUTPUT_PPTX",
    "MMO_DATA_ROOT",
    "DIGITAL_DATA_ROOT",
    "DUMMY_DF_ROOT",
    "FIVE_DICT",
    "PROJECT_ROOT",
    "display",
}


class _NameCollector(ast.NodeVisitor):
    """Собирает читаемые и определяемые имена верхнего уровня ячейки."""

    def __init__(self) -> None:
        self.loaded: set[str] = set()
        self.stored: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loaded.add(node.id)
        else:
            self.stored.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stored.add(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.stored.add(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stored.add(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.stored.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                # `from x import *` — какие имена придут, статически не узнать.
                self.stored.add("*")
            else:
                self.stored.add(alias.asname or alias.name)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.generic_visit(node)


def strip_comments(source: str) -> str:
    """Убирает комментарии, чтобы поиск хардкода не срабатывал на пояснениях."""
    try:
        tokens = [
            token
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type != tokenize.COMMENT
        ]
        return tokenize.untokenize(tokens)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Не разобралось — лучше проверить с комментариями, чем не проверить вовсе.
        return source


def check(notebook_path: Path, data_source: str, run_dev_cells: bool) -> list[str]:
    notebook = load_notebook(notebook_path)
    cells = notebook["cells"]
    problems: list[str] = []

    try:
        plan = T.select_cells(cells, data_source=data_source, run_dev_cells=run_dev_cells)
    except ValueError as exc:
        return [str(exc)]

    if not any(item.tag == T.PARAMETERS for item in plan):
        problems.append("В ноутбуке нет ячейки с тегом 'parameters' — рантайму некуда подставить пути.")

    known_names = set(dir(builtins)) | INJECTED_NAMES
    star_imported = False

    for item in plan:
        if not item.should_run:
            continue

        source = "".join(cells[item.index].get("source", []))

        if item.tag != T.PARAMETERS:
            code_only = strip_comments(source)
            for literal, why in FORBIDDEN_LITERALS:
                if literal in code_only:
                    problems.append(f"Ячейка #{item.index}: остался хардкод {literal!r} — {why}")

        try:
            tree = ast.parse(source, filename=f"<cell {item.index}>")
        except SyntaxError as exc:
            problems.append(f"Ячейка #{item.index}: синтаксическая ошибка — {exc}")
            continue

        collector = _NameCollector()
        collector.visit(tree)

        if not star_imported:
            # Имена, определённые в этой же ячейке, тоже считаются известными:
            # ячейка исполняется целиком, порядок строк внутри неё корректен.
            missing = sorted(collector.loaded - known_names - collector.stored)
            if missing:
                problems.append(
                    f"Ячейка #{item.index}: имена не определены ни в одной боевой ячейке выше: "
                    + ", ".join(missing[:8])
                    + (" …" if len(missing) > 8 else "")
                )

        if "*" in collector.stored:
            # После `from ... import *` статический анализ имён теряет смысл.
            star_imported = True
        known_names |= collector.stored

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--data-source", default="db", choices=sorted(T.SOURCE_TAGS))
    parser.add_argument("--run-dev-cells", action="store_true")
    args = parser.parse_args()

    if sys.version_info < MIN_PYTHON:
        print(
            f"Нужен Python >= {'.'.join(map(str, MIN_PYTHON))}, запущен "
            f"{sys.version.split()[0]}. Ноутбук использует вложенные кавычки в "
            f"f-строках (PEP 701), на этой версии его нельзя ни разобрать, ни выполнить.",
            file=sys.stderr,
        )
        return 1

    problems = check(args.notebook, args.data_source, args.run_dev_cells)

    if problems:
        print(f"Найдено проблем: {len(problems)}", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    plan = T.select_cells(
        load_notebook(args.notebook)["cells"],
        data_source=args.data_source,
        run_dev_cells=args.run_dev_cells,
    )
    print(
        f"OK: {sum(1 for p in plan if p.should_run)} ячеек к исполнению, "
        f"{sum(1 for p in plan if not p.should_run)} пропускается "
        f"(источник данных: {args.data_source})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
