#!/usr/bin/env python3
"""Сборка презентации из командной строки — тот же путь, что дёргает кнопка.

Нужен, чтобы проверить весь пайплайн до того, как появится веб-интерфейс, и
чтобы запускать сборку по расписанию.

    python scripts/build_presentation.py                     # боевой прогон
    python scripts/build_presentation.py --check             # только проверка окружения
    python scripts/build_presentation.py --plan              # что будет исполнено
    python scripts/build_presentation.py --data-source csv   # на локальных снимках
    python scripts/build_presentation.py -o ~/deck.pptx      # положить результат сюда
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opercom.config import load_settings  # noqa: E402
from opercom.notebook_runner import describe_plan  # noqa: E402
from opercom.pipeline import PreflightFailed, build_presentation, describe_error  # noqa: E402
from opercom.preflight import is_ready, run_checks  # noqa: E402


def _print_checks(checks) -> None:
    for check in checks:
        mark = "✓" if check.ok else ("✗" if check.blocking else "!")
        print(f"  {mark} {check.name}: {check.detail}")


def _on_event(event: dict) -> None:
    """Печатает ход прогона: этапы, вывод ячеек, долгие ячейки."""
    kind = event.get("type")
    if kind == "plan":
        print(
            f"План: {event['to_run']} ячеек к исполнению из {event['code_cells']} "
            f"(источник данных: {event['data_source']})"
        )
    elif kind == "cell_start" and event.get("stage"):
        stage = event["stage"]
        if stage != _on_event.last_stage:
            _on_event.last_stage = stage
            print(f"\n[{event['executed']:>3}/{event['total']}] {stage}")
    elif kind == "cell_done" and event["duration_sec"] >= 5:
        print(f"      ячейка #{event['cell']} — {event['duration_sec']:.1f} с")
    elif kind == "output":
        print(f"      {event['text']}")
    elif kind == "error":
        print(f"\nОШИБКА в ячейке #{event['cell']} ({event.get('stage') or 'без раздела'}):")
        print(event["traceback"])


_on_event.last_stage = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-source", choices=["db", "csv"], help="переопределить источник данных")
    parser.add_argument("-o", "--output", type=Path, help="куда скопировать готовый .pptx")
    parser.add_argument("--check", action="store_true", help="только проверить окружение")
    parser.add_argument("--plan", action="store_true", help="только показать план прогона")
    parser.add_argument("--skip-preflight", action="store_true", help="запустить без проверки окружения")
    parser.add_argument("--quiet", action="store_true", help="не печатать ход прогона")
    args = parser.parse_args()

    settings = load_settings()
    if args.data_source:
        settings.data_source = args.data_source

    if args.plan:
        plan = list(describe_plan(settings.notebook_path, data_source=settings.data_source))
        for item in plan:
            mark = "RUN " if item.should_run else "skip"
            print(f"  {mark} #{item.index:>3} [{item.tag}] {item.reason}")
        print(f"\nВсего: {sum(1 for p in plan if p.should_run)} к исполнению, "
              f"{sum(1 for p in plan if not p.should_run)} пропускается")
        return 0

    checks = run_checks(settings)
    print(f"Проверка окружения (источник данных: {settings.data_source}):")
    _print_checks(checks)
    ready = is_ready(checks)

    if args.check:
        print("\nОкружение готово." if ready else "\nЕсть блокирующие проблемы.")
        return 0 if ready else 1

    if not ready and not args.skip_preflight:
        print("\nЕсть блокирующие проблемы — прогон не запущен.", file=sys.stderr)
        return 1

    print()
    try:
        result = build_presentation(
            settings,
            on_event=None if args.quiet else _on_event,
            skip_preflight=True,  # уже проверили выше
        )
    except PreflightFailed as exc:
        print(f"\nОкружение не готово: {exc}", file=sys.stderr)
        return 1
    except BaseException as exc:  # noqa: BLE001 - нужен читаемый вывод, а не трейс CLI
        info = describe_error(exc)
        print(f"\n{info['message']}: {info.get('detail', '')}", file=sys.stderr)
        return 1

    print(
        f"\nГотово за {result.duration_sec:.1f} с: {result.executed_cells} ячеек, "
        f"{result.dataframes_total} датафреймов, пропущено {result.skipped_cells}."
    )

    output = result.output_path
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.output_path, args.output)
        output = args.output

    print(f"Файл: {output} ({output.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
