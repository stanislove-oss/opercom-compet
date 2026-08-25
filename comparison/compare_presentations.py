"""
compare_presentations.py

Функции для сравнения данных графиков/таблиц эталонной презентации
с автоматизированными данными в виде DataFrame'ов.

Основная функция: compare_with_dataframes()
"""

import json
import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────
# Конвертация JSON → DataFrame
# ─────────────────────────────────────────────────────────────────

def chart_to_df(chart: dict) -> pd.DataFrame:
    """
    Конвертирует график из JSON в DataFrame.
    Индекс — категории, столбцы — серии.
    """
    df = pd.DataFrame()
    for ser in chart.get("series", []):
        min_len = min(len(ser.get("categories", [])), len(ser.get("values", [])))
        cats = ser["categories"][:min_len]
        vals = np.array(
            [v if str(v).strip() != "" else np.nan for v in ser["values"][:min_len]]
        ).astype(float)
        df = pd.concat(
            [df, pd.DataFrame(data=vals, index=cats, columns=[ser["name"]])],
            axis=1
        )
    # Убираем строки с пустым индексом — они разделители, не данные
    df = df[df.index.astype(str).str.strip() != ""]
    return df


def table_to_df(table: dict) -> pd.DataFrame:
    """
    Конвертирует таблицу из JSON в DataFrame.
    Индекс — первый столбец, остальные столбцы — данные.
    """
    cols = table.get("headers", [])[1:]
    idxs = [r[0] for r in table.get("rows", []) if r]
    vals = [
        np.array([
            float(str(v).replace(" ", "").replace("%", "").replace(",", "."))
            if str(v).strip() not in ("", "nan", "None") else np.nan
            for v in r[1:]
        ]).astype(float)
        for r in table.get("rows", []) if r
    ]
    return pd.DataFrame(data=vals, index=idxs, columns=cols)


# ─────────────────────────────────────────────────────────────────
# Сравнение двух презентаций (оба в виде JSON)
# ─────────────────────────────────────────────────────────────────

def compare_charts(etalon_chart: dict, auto_chart: dict):
    """Сравнивает два графика. Возвращает (abs_diff, rel_diff)."""
    e = chart_to_df(etalon_chart)
    a = chart_to_df(auto_chart)
    d = a - e
    return d, d / e


def compare_tables(etalon_table: dict, auto_table: dict):
    """Сравнивает две таблицы. Возвращает (abs_diff, rel_diff)."""
    e = table_to_df(etalon_table)
    a = table_to_df(auto_table)
    d = a - e
    return d, d / e


def compare_presentations(etalon_slides: list, auto_slides: list) -> dict:
    """
    Сравнивает два списка слайдов (каждый слайд — JSON-объект).

    Возвращает:
        {
          'slide_N': {
            'chart_1': (abs_diff, rel_diff),
            'table_1': (abs_diff, rel_diff),
          }
        }
    """
    results = {}
    for etalon_slide, auto_slide in zip(etalon_slides, auto_slides):
        sn = etalon_slide["slide"]
        for i, (ec, ac) in enumerate(zip(etalon_slide.get("charts", []), auto_slide.get("charts", [])), 1):
            results.setdefault(f"slide_{sn}", {})[f"chart_{i}"] = compare_charts(ec, ac)
        for i, (et, at) in enumerate(zip(etalon_slide.get("tables", []), auto_slide.get("tables", [])), 1):
            results.setdefault(f"slide_{sn}", {})[f"table_{i}"] = compare_tables(et, at)
    return results


# ─────────────────────────────────────────────────────────────────
# Сравнение JSON-эталона с авто-данными в виде DataFrame'ов
# ─────────────────────────────────────────────────────────────────


RU_MONTHS = {1:'Янв',2:'Фев',3:'Мар',4:'Апр',5:'Май',6:'Июн',
             7:'Июл',8:'Авг',9:'Сен',10:'Окт',11:'Ноя',12:'Дек'}

def _ts_to_candidates(ts) -> list:
    """Возвращает все возможные строковые представления Timestamp."""
    from datetime import date as _date
    d = ts.date() if hasattr(ts, 'date') else ts
    excel = str((d - _date(1899, 12, 30)).days)
    m = d.month
    y = d.year
    return [
        excel,                                          # '45658'
        f"{RU_MONTHS[m]} {y}",                         # 'Янв 2025'
        f"{RU_MONTHS[m].lower()}.{str(y)[2:]}",        # 'янв.25'
        f"{RU_MONTHS[m]} '{str(y)[2:]}",              # 'Янв '25'
        str(d),                                         # '2025-01-01'
        d.strftime("%d.%m.%Y"),                        # '01.01.2025'
    ]


def _to_timestamp(val) -> pd.Timestamp | None:
    """Пытается привести значение к Timestamp. Возвращает None если не получилось."""
    if isinstance(val, pd.Timestamp):
        return val
    if isinstance(val, str):
        try:
            return pd.Timestamp(val)
        except Exception:
            return None
    return None


def _align_index(auto_idx: pd.Index, etalon_idx: pd.Index) -> pd.Index:
    """
    Пытается привести auto_idx к формату etalon_idx.
    Работает с Timestamp и строками-датами вида '2025-01-01'.
    """
    # Пробуем привести каждый элемент к Timestamp
    parsed = [_to_timestamp(v) for v in auto_idx]
    if not any(parsed):
        return auto_idx  # ни один элемент не распарсился — возвращаем как есть

    etalon_set = set(etalon_idx.astype(str))

    # Ищем подходящий формат по первому успешно распарсенному элементу
    for ts in parsed:
        if ts is None:
            continue
        for candidate in _ts_to_candidates(ts):
            if candidate in etalon_set:
                # Нашли формат — применяем ко всему индексу
                fmt_idx = _ts_to_candidates(ts).index(candidate)
                new_idx = []
                for orig, p in zip(auto_idx, parsed):
                    if p is not None:
                        new_idx.append(_ts_to_candidates(p)[fmt_idx])
                    else:
                        new_idx.append(str(orig))
                return pd.Index(new_idx)

    # Ничего не нашли — возвращаем как есть
    return auto_idx

def _normalize_auto_df(df: pd.DataFrame, index_col: str = None) -> pd.DataFrame:
    """
    Приводит авто DataFrame к стандартному виду:
    - если index_col указан и такой столбец есть — переносит его в индекс
    - если индекс уже нечисловой — оставляет как есть
    - конвертирует значения в float (обрабатывает %, запятые, пробелы)
    - пропускает datetime-столбцы
    """
    df = df.copy()
    # Переносим в индекс только если указан index_col и индекс ещё числовой
    if index_col and index_col in df.columns:
        df = df.set_index(index_col)
    elif pd.api.types.is_integer_dtype(df.index):
        # Числовой индекс 0,1,2... — пробуем найти первый строковый столбец
        str_cols = [c for c in df.columns if df[c].dtype == object]
        if str_cols:
            df = df.set_index(str_cols[0])
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        try:
            df[col] = df[col].apply(
                lambda x: float(str(x).replace(" ", "").replace("%", "").replace(",", "."))
                if str(x).strip() not in ("", "nan", "None") else np.nan
            )
        except Exception:
            pass
    return df


def compare_with_dataframes(
    auto_dfs: dict,
    mapping: dict,
    etalon_slides: list,
    index_col: str = "advertiser_main",
) -> dict:
    """
    Сравнивает авто DataFrame'ы с эталонными данными из JSON.

    Args:
        auto_dfs:       словарь {название: DataFrame} из автоматизированной системы
        mapping:        соответствие названий объектам в JSON:
                        {
                          'Слайд 4 верх': {
                            'slide': 4,
                            'type': 'chart',   # 'chart' или 'table'
                            'index': 1,        # номер объекта на слайде (1-based)
                            'index_col': 'advertiser_main'  # опционально
                          }
                        }
        etalon_slides:  список JSON-объектов эталонной презентации
        index_col:      дефолтное название столбца-индекса (бренды/категории)

    Returns:
        dict в том же формате что и compare_presentations():
        {'slide_N': {'chart_1': (abs_diff, rel_diff, etalon_df, auto_df)}}
    """
    e_by_slide = {s["slide"]: s for s in etalon_slides}
    results = {}

    for name, auto_df in auto_dfs.items():
        if name not in mapping:
            print(f"⚠ '{name}' не найден в mapping — пропускаем")
            continue

        m = mapping[name]
        slide_num = m["slide"]
        obj_type  = m["type"]
        obj_idx   = m["index"] - 1  # переводим в 0-based

        # Находим слайд и объект в эталоне
        e_slide = e_by_slide.get(slide_num)
        if e_slide is None:
            print(f"⚠ Слайд {slide_num} не найден в эталоне — пропускаем '{name}'")
            continue

        e_objects = e_slide.get("charts" if obj_type == "chart" else "tables", [])
        if obj_idx >= len(e_objects):
            print(f"⚠ Объект {obj_idx+1} не найден на слайде {slide_num} — пропускаем '{name}'")
            continue

        # Конвертируем эталон в DataFrame
        e_obj = e_objects[obj_idx]
        etalon_df = chart_to_df(e_obj) if obj_type == "chart" else table_to_df(e_obj)

        # Нормализуем авто DataFrame
        col = m.get("index_col", index_col)
        auto_df_norm = _normalize_auto_df(auto_df, col)

        # Приводим индекс авто к формату эталона (обработка дат)
        auto_df_norm.index = _align_index(auto_df_norm.index, etalon_df.index)

        # Сравниваем по именам индексов и столбцов
        common_idx  = etalon_df.index.intersection(auto_df_norm.index)
        common_cols = etalon_df.columns.intersection(auto_df_norm.columns)

        if common_idx.empty or common_cols.empty:
            print(f"⚠ Нет общих индексов/столбцов для '{name}' — пропускаем")
            print(f"   Эталон индексы: {etalon_df.index.tolist()[:3]}")
            print(f"   Авто индексы:   {auto_df_norm.index.tolist()[:3]}")
            continue

        e_aligned = etalon_df.loc[common_idx, common_cols]
        a_aligned = auto_df_norm.loc[common_idx, common_cols]

        # Оставляем только числовые столбцы
        numeric_cols = [
            c for c in common_cols
            if pd.api.types.is_numeric_dtype(e_aligned[c])
            and pd.api.types.is_numeric_dtype(a_aligned[c])
        ]
        e_aligned = e_aligned[numeric_cols]
        a_aligned = a_aligned[numeric_cols]

        if e_aligned.empty:
            print(f"⚠ Нет числовых столбцов для '{name}' — пропускаем")
            continue

        diffs    = a_aligned - e_aligned
        rel_diff = diffs / e_aligned

        slide_key = f"slide_{slide_num}"
        obj_key   = f"{obj_type}_{m['index']}"
        results.setdefault(slide_key, {})[obj_key] = (diffs, rel_diff, e_aligned, a_aligned)

    return results
