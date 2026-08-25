"""
report_excel.py

Генерирует Excel-отчёт по результатам compare_presentations() или compare_with_dataframes().

Формат таблицы:
    Категория | Серия 1: Эталон | Серия 1: Авто | Серия 1: Δ | Серия 2: Эталон | ...
    Строки с |Δ| >= 1 выделяются красным.

Использование:
    from report_excel import build_excel_report
    results = compare_with_dataframes(...)
    build_excel_report(results, "report.xlsx")
"""

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── Цвета ──────────────────────────────────────────────────────────
BG_DARK      = "1C1C1C"   # фон заголовка блока
BG_HEADER1   = "2C3E50"   # фон строки с именами серий
BG_HEADER2   = "34495E"   # фон строки Эталон/Авто/Δ
BG_DIFF      = "3A1010"   # фон строки с расхождением
FG_DIFF      = "E88080"   # текст строки с расхождением
BG_OK        = "1A1A1A"   # фон строки без расхождения
FG_OK        = "C8C8C4"   # текст строки без расхождения
FG_WHITE     = "FFFFFF"
FG_DIM       = "888882"
BORDER_COLOR = "2A2A2A"

ABS_THRESHOLD = 1.0  # порог абсолютной разницы — ниже считается округлением


# ── Стили ──────────────────────────────────────────────────────────

def _border():
    s = Side(style="thin", color=BORDER_COLOR)
    return Border(left=s, right=s, top=s, bottom=s)


def _style(cell, bg, fg, bold=False, align="center", size=9, wrap=False):
    cell.font = Font(name="Arial", size=size, bold=bold, color=fg)
    cell.fill = PatternFill("solid", start_color=bg)
    cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    cell.border = _border()


def _fmt(val):
    """Форматирует число для ячейки — возвращает полное число без сокращений."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return round(float(val), 2)


def _is_diff(abs_val):
    """True если расхождение реальное (не округление)."""
    if abs_val is None or (isinstance(abs_val, float) and np.isnan(abs_val)):
        return False
    return abs(abs_val) >= ABS_THRESHOLD


def _safe_val(df, idx, col):
    """Безопасно получает скалярное значение из DataFrame."""
    if idx not in df.index or col not in df.columns:
        return None
    v = df.loc[idx, col]
    if hasattr(v, "__len__"):
        v = v.iloc[0]
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


# ── Запись объекта на лист ─────────────────────────────────────────

def _write_object(ws, etalon_df, auto_df, abs_diff, obj_label, start_row):
    """
    Записывает один объект (график/таблицу) в виде широкой таблицы.
    Структура столбцов: Категория | Сер1:Эталон | Сер1:Авто | Сер1:Δ | Сер2:Эталон | ...
    Возвращает следующую свободную строку.
    """
    series = etalon_df.columns.tolist()
    categories = etalon_df.index.tolist()
    n_series = len(series)
    total_cols = 1 + n_series * 3  # категория + (эталон+авто+дельта) * кол-во серий

    row = start_row

    # ── Заголовок блока ──
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=total_cols)
    cell = ws.cell(row=row, column=1, value=obj_label)
    _style(cell, BG_DARK, FG_WHITE, bold=True, align="left", size=10)
    ws.row_dimensions[row].height = 20
    row += 1

    # ── Строка 1 заголовка: имена серий (объединённые по 3) ──
    ws.cell(row=row, column=1, value="")
    _style(ws.cell(row=row, column=1), BG_HEADER1, FG_WHITE)
    for i, ser in enumerate(series):
        col_start = 2 + i * 3
        ws.merge_cells(start_row=row, start_column=col_start, end_row=row, end_column=col_start + 2)
        cell = ws.cell(row=row, column=col_start, value=str(ser))
        _style(cell, BG_HEADER1, FG_WHITE, bold=True, wrap=True)
        # Стиль для объединённых ячеек
        for c in range(col_start + 1, col_start + 3):
            _style(ws.cell(row=row, column=c), BG_HEADER1, FG_WHITE)
    ws.row_dimensions[row].height = 22
    row += 1

    # ── Строка 2 заголовка: Эталон / Авто / Δ ──
    cell = ws.cell(row=row, column=1, value="Категория")
    _style(cell, BG_HEADER2, FG_WHITE, bold=True)
    for i in range(n_series):
        col_start = 2 + i * 3
        for j, label in enumerate(["Эталон", "Авто", "Δ"]):
            cell = ws.cell(row=row, column=col_start + j, value=label)
            _style(cell, BG_HEADER2, FG_WHITE, bold=True)
    ws.row_dimensions[row].height = 18
    row += 1

    # ── Данные ──
    for cat in categories:
        # Определяем есть ли расхождение в этой строке
        row_has_diff = any(
            _is_diff(_safe_val(abs_diff, cat, ser))
            for ser in series
            if ser in abs_diff.columns
        )
        bg = BG_DIFF if row_has_diff else BG_OK
        fg = FG_DIFF if row_has_diff else FG_OK

        # Категория
        cell = ws.cell(row=row, column=1, value=str(cat))
        _style(cell, bg, fg, align="left")

        # Данные по каждой серии
        for i, ser in enumerate(series):
            col_start = 2 + i * 3
            e_val = _safe_val(etalon_df, cat, ser)
            a_val = _safe_val(auto_df, cat, ser)
            d_val = _safe_val(abs_diff, cat, ser)

            for j, val in enumerate([_fmt(e_val), _fmt(a_val), _fmt(d_val)]):
                cell = ws.cell(row=row, column=col_start + j, value=val)
                _style(cell, bg, fg)

        ws.row_dimensions[row].height = 15
        row += 1

    return row + 1  # пустая строка между блоками


# ── Ширина столбцов ────────────────────────────────────────────────

def _set_col_widths(ws, n_series):
    ws.column_dimensions["A"].width = 24
    for i in range(n_series):
        for j in range(3):
            col_letter = get_column_letter(2 + i * 3 + j)
            ws.column_dimensions[col_letter].width = 13


# ── Основная функция ───────────────────────────────────────────────

def build_excel_report(results: dict, output_path: str = "report.xlsx"):
    """
    Строит Excel-отчёт по результатам compare_presentations() или compare_with_dataframes().

    Args:
        results:      словарь из compare_*:
                      {'slide_N': {'chart_1': (abs_diff, rel_diff[, etalon_df, auto_df])}}
        output_path:  путь для сохранения
    """
    wb = Workbook()

    # ── Сводный лист ──
    summary_ws = wb.active
    summary_ws.title = "Сводка"
    summary_ws.sheet_view.showGridLines = False

    sum_headers = ["Слайд", "Объект", "Тип", "Строк с Δ", "Макс |Δ|", "Статус"]
    for ci, h in enumerate(sum_headers, 1):
        cell = summary_ws.cell(row=1, column=ci, value=h)
        _style(cell, BG_DARK, FG_WHITE, bold=True)
    summary_ws.row_dimensions[1].height = 20

    for i, w in enumerate([10, 12, 10, 12, 14, 12], 1):
        summary_ws.column_dimensions[get_column_letter(i)].width = w

    sum_row = 2

    # ── Листы по слайдам ──
    for slide_key, objs in results.items():
        if not objs:
            continue

        slide_num = slide_key.replace("slide_", "")
        ws = wb.create_sheet(title=f"Сл.{slide_num}")
        ws.sheet_view.showGridLines = False
        cur_row = 1

        for obj_key, obj_data in objs.items():
            # Распаковываем — поддерживаем оба формата (2 и 4 элемента)
            if isinstance(obj_data, tuple) and len(obj_data) == 4:
                abs_diff, rel_diff, etalon_df, auto_df = obj_data
            else:
                abs_diff, rel_diff = obj_data[0], obj_data[1]
                etalon_df, auto_df = abs_diff.copy(), (abs_diff + abs_diff).copy()  # fallback

            obj_label = f"[{obj_key.upper()}]  Слайд {slide_num}"

            # Настраиваем ширину столбцов по первому объекту
            if cur_row == 1:
                _set_col_widths(ws, len(etalon_df.columns))

            # Пишем таблицу
            cur_row = _write_object(ws, etalon_df, auto_df, abs_diff, obj_label, cur_row)

            # Статистика для сводки
            diff_rows = 0
            max_abs = 0.0
            for cat in abs_diff.index:
                row_has_diff = False
                for col in abs_diff.columns:
                    v = _safe_val(abs_diff, cat, col)
                    if v is not None and _is_diff(v):
                        row_has_diff = True
                        max_abs = max(max_abs, abs(v))
                if row_has_diff:
                    diff_rows += 1

            overall = "есть Δ" if diff_rows > 0 else "—"
            bg = BG_DIFF if diff_rows > 0 else BG_OK
            fg = FG_DIFF if diff_rows > 0 else FG_OK

            for ci, val in enumerate([
                slide_num,
                obj_key.replace("_", " "),
                "chart" if "chart" in obj_key else "table",
                diff_rows,
                round(max_abs, 2) if max_abs else "—",
                overall,
            ], 1):
                cell = summary_ws.cell(row=sum_row, column=ci, value=val)
                _style(cell, bg, fg, align="center")
            summary_ws.row_dimensions[sum_row].height = 15
            sum_row += 1

    wb.save(output_path)
    print(f"Отчёт сохранён: {output_path}")
    return output_path
