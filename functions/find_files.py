from pathlib import Path
from collections.abc import Iterable

def find_data_file(
    pattern: str,
    root: str | Path,
    exclude: Iterable[str] = (),
    *,
    strict: bool = False
) -> Path:
    files = []
    exclude = tuple(exclude)
    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f"Корневой путь {root_path} не найден")
    if not root_path.is_dir():
        raise FileNotFoundError(f"{root_path} – файл")
    for item_path in root_path.glob(pattern):
        if item_path.name.startswith("~$") or item_path.stem.endswith(exclude) or not item_path.is_file():
            continue
        files.append(item_path)

    if not files:
        raise FileNotFoundError(f"В {root_path} не найден ни один файл, который соответствует {pattern} и обходит {', '.join(exclude)}")
    if len(files) > 1 and strict:
        raise ValueError(f"При строгом режиме возможен только один файл, а найдено несколько: {list(files)}")

    return max(files, key=lambda item: item.stat().st_mtime)