#!/usr/bin/env python3
"""Доразметка ноутбука: проставляет тег code-ячейкам, у которых его нет.

Первичная разметка сделана один раз; этот скрипт нужен, когда в ноутбук
добавили ячейки и `check_notebook.py` ругается, что у них нет тега.

Правил с привязкой к номерам ячеек здесь намеренно нет: они устаревают при
первой же правке ноутбука и превращаются в вечный долг. Тег предлагается по
содержимому, и по умолчанию скрипт только показывает, что собирается сделать.

    python scripts/tag_notebook.py            # показать предложение
    python scripts/tag_notebook.py --apply    # записать
    python scripts/tag_notebook.py --apply --tag skip   # всем без тега — skip

Предложение простое и намеренно осторожное:

    ячейка что-то присваивает или импортирует  -> run
    ячейка состоит из одного выражения         -> skip  (это просмотр)

Оно угадывает не всегда: ячейку с побочным эффектом без присваивания скрипт
пометит `skip`. Поэтому решение всегда показывается вместе с первой строкой
ячейки — проверить глазами дешевле, чем ловить пустой отчёт.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opercom import tags as T  # noqa: E402

NOTEBOOK = Path(__file__).resolve().parent.parent / "main_2.ipynb"


def suggest_tag(source: str) -> str:
    """Какой тег напрашивается по содержимому ячейки."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Разобрать не удалось — пусть решает человек, в прод такое не пускаем.
        return T.SKIP

    body = [node for node in tree.body]
    if not body:
        return T.SKIP

    # Ячейка целиком из выражений — это просмотр датафрейма.
    if all(isinstance(node, ast.Expr) for node in body):
        return T.SKIP

    return T.RUN


def first_line(source: str) -> str:
    for line in source.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:70]
    return source.strip().splitlines()[0][:70] if source.strip() else "(пусто)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--apply", action="store_true", help="записать изменения в файл")
    parser.add_argument(
        "--tag",
        choices=sorted(T.KNOWN_TAGS),
        help="поставить всем ячейкам без тега именно этот тег",
    )
    args = parser.parse_args()

    notebook = json.loads(args.notebook.read_text(encoding="utf-8"))
    cells = notebook["cells"]

    proposals = []
    for index, cell in enumerate(cells):
        if cell.get("cell_type") != "code" or T.cell_tag(cell) is not None:
            continue
        source = "".join(cell.get("source", []))
        if not source.strip():
            continue
        proposals.append((index, cell, args.tag or suggest_tag(source), first_line(source)))

    if not proposals:
        tagged = sum(
            1 for cell in cells
            if cell.get("cell_type") == "code" and T.cell_tag(cell) is not None
        )
        print(f"Все code-ячейки размечены ({tagged} шт.).")
        return 0

    print(f"Ячеек без тега: {len(proposals)}\n")
    for index, _cell, tag, preview in proposals:
        print(f"  #{index:>3}  {tag:<12} {preview}")

    if not args.apply:
        print("\nЗапустить с --apply, чтобы записать. Тег можно задать явно: --tag run")
        return 0

    for _index, cell, tag, _preview in proposals:
        metadata = cell.setdefault("metadata", {})
        extra = [t for t in (metadata.get("tags") or []) if t not in T.KNOWN_TAGS]
        metadata["tags"] = [tag, *extra]

    args.notebook.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"\nЗаписано {len(proposals)} тегов в {args.notebook}")
    print("Проверить:  python scripts/check_notebook.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
