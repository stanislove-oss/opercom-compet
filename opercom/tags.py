"""Словарь тегов ячеек ноутбука и правила отбора ячеек для прогона.

Тег живёт в стандартном месте — `cell.metadata.tags` (список строк). Это тот же
механизм, которым пользуются papermill/nbconvert, поэтому теги видны и правятся
прямо в Jupyter: `View -> Cell Toolbar -> Tags`.

Правило простое: **у каждой code-ячейки должен быть ровно один тег из этого
словаря**. Умолчания «не проставил тег — значит выполняется» нет намеренно: иначе
новая исследовательская ячейка молча уедет в боевой прогон.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Ячейка входит в боевой прогон.
RUN = "run"

#: Ячейка параметров. Выполняется первой; рантайм переопределяет её значения.
PARAMETERS = "parameters"

#: Исследование, отладка, `df.head()`, битые ячейки. Не выполняется никогда.
SKIP = "skip"

#: Служебные ячейки разработчика (дампы снимков, сверка с baseline).
#: Выполняются только при `run_dev_cells=True`.
DEV = "dev"

#: Загрузка данных из MySQL + Google Sheets. Выполняется при data_source="db".
SOURCE_DB = "source:db"

#: Загрузка данных из локальных CSV в dummy_df/. Выполняется при data_source="csv".
SOURCE_CSV = "source:csv"

KNOWN_TAGS = frozenset(
    {RUN, PARAMETERS, SKIP, DEV, SOURCE_DB, SOURCE_CSV}
)

#: Теги, каждый из которых задаёт свой вариант одного и того же шага пайплайна.
#: Ровно один из них активен в прогоне.
SOURCE_TAGS = {
    "db": SOURCE_DB,
    "csv": SOURCE_CSV,
}

TAG_DESCRIPTIONS = {
    RUN: "боевая ячейка пайплайна",
    PARAMETERS: "ячейка параметров (значения переопределяются рантаймом)",
    SKIP: "исследование/отладка — не выполняется",
    DEV: "служебная ячейка разработчика — только при run_dev_cells=True",
    SOURCE_DB: "источник данных: MySQL + Google Sheets",
    SOURCE_CSV: "источник данных: локальные CSV из dummy_df/",
}


@dataclass(frozen=True)
class CellSelection:
    """Решение по одной ячейке: выполнять или нет, и почему."""

    index: int
    tag: str
    should_run: bool
    reason: str


def cell_tag(cell: dict) -> str | None:
    """Возвращает управляющий тег ячейки или None, если тега нет.

    Посторонние теги (например, поставленные nbconvert) игнорируются — берётся
    первый из известных.
    """
    for tag in cell.get("metadata", {}).get("tags", []) or []:
        if tag in KNOWN_TAGS:
            return tag
    return None


def select_cells(
    cells: list[dict],
    *,
    data_source: str = "db",
    run_dev_cells: bool = False,
) -> list[CellSelection]:
    """Строит план прогона: какие code-ячейки выполнять, а какие пропустить.

    Markdown-ячейки в план не попадают — они не исполняются в принципе.

    Raises:
        ValueError: если у code-ячейки нет известного тега или значение
            `data_source` неизвестно.
    """
    if data_source not in SOURCE_TAGS:
        raise ValueError(
            f"Неизвестный data_source={data_source!r}. "
            f"Допустимые значения: {sorted(SOURCE_TAGS)}"
        )

    active_source_tag = SOURCE_TAGS[data_source]
    plan: list[CellSelection] = []

    for index, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue

        source = "".join(cell.get("source", []))
        tag = cell_tag(cell)

        if tag is None:
            if not source.strip():
                # Пустая ячейка в конце ноутбука — безобидна, но и тега не требует.
                plan.append(CellSelection(index, SKIP, False, "пустая ячейка"))
                continue
            raise ValueError(
                f"У code-ячейки #{index} нет тега из {sorted(KNOWN_TAGS)}. "
                f"Проставь тег (см. scripts/tag_notebook.py). "
                f"Начало ячейки: {source.strip().splitlines()[0][:80]!r}"
            )

        if tag in (RUN, PARAMETERS):
            plan.append(CellSelection(index, tag, True, TAG_DESCRIPTIONS[tag]))
        elif tag == SKIP:
            plan.append(CellSelection(index, tag, False, TAG_DESCRIPTIONS[tag]))
        elif tag == DEV:
            plan.append(
                CellSelection(
                    index,
                    tag,
                    run_dev_cells,
                    "dev-ячейка включена" if run_dev_cells else "dev-ячейки отключены",
                )
            )
        elif tag in SOURCE_TAGS.values():
            active = tag == active_source_tag
            plan.append(
                CellSelection(
                    index,
                    tag,
                    active,
                    f"источник данных: {data_source}"
                    if active
                    else f"другой источник данных (активен {data_source})",
                )
            )
        else:  # pragma: no cover — защищено KNOWN_TAGS
            raise ValueError(f"Тег {tag!r} есть в KNOWN_TAGS, но не обработан")

    return plan
