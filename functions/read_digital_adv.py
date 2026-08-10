import pandas as pd
import re


MONTH_ORDER = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}


def make_top_advertisers_view(
    df,
    top_n=20,
    required_advertisers=("ТАНДЕР", "X5 GROUP"),
    sort_col=None,
    strict_top_n=True,
):
    """
    Делает срез для конкретного слайда:
    топ-N + обязательные рекламодатели.

    Важно:
    эта функция НЕ должна применяться к основному df,
    если потом df нужен для merge / join / расчётов.
    """

    df = df.copy()

    if sort_col is None:
        if "rank" in df.columns:
            df = df.sort_values("rank", ascending=True)
        else:
            total_cols = [
                c for c in df.columns
                if str(c).startswith("total_")
            ]

            if not total_cols:
                raise ValueError("Не найден rank или total_* для сортировки")

            sort_col = sorted(total_cols)[-1]
            df = df.sort_values(sort_col, ascending=False)
    else:
        df = df.sort_values(sort_col, ascending=False)

    df["_advertiser_norm"] = (
        df["advertiser_main"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    required_norm = {
        str(x).strip().upper()
        for x in required_advertisers
    }

    top_df = df.head(top_n).copy()

    missing_required = [
        name for name in required_norm
        if name not in set(top_df["_advertiser_norm"])
    ]

    required_rows = df[
        df["_advertiser_norm"].isin(missing_required)
    ].copy()

    result = pd.concat(
        [top_df, required_rows],
        ignore_index=True
    )

    result = result.drop_duplicates(
        subset="_advertiser_norm",
        keep="first"
    )

    if strict_top_n and len(result) > top_n:
        required_mask = result["_advertiser_norm"].isin(required_norm)

        required_part = result[required_mask].copy()
        regular_part = result[~required_mask].copy()

        available_regular_rows = top_n - len(required_part)

        result = pd.concat(
            [
                regular_part.head(max(available_regular_rows, 0)),
                required_part,
            ],
            ignore_index=True,
        )

    if "rank" in result.columns:
        result = result.sort_values("rank", ascending=True)

    result = result.drop(columns=["_advertiser_norm"])

    return result.reset_index(drop=True)


def normalize_month_name(value):
    return str(value).strip().lower()


def get_month_from_period_title(title, period_type):
    left_part = str(title).split(",")[0].strip().lower()
    left_part = re.sub(r"\s+20\d{2}$", "", left_part)

    if period_type == "ytd":
        if "-" in left_part:
            return left_part.split("-")[-1].strip()
        return left_part.strip()

    if period_type == "month":
        return left_part.strip()

    raise ValueError(f"Неизвестный period_type: {period_type}")


def is_valid_period_title(text, current_year, previous_year, period_type):
    text = str(text).strip()
    lower_text = text.lower()

    if str(current_year) not in text or str(previous_year) not in text:
        return False

    if period_type == "ytd":
        # Январь-март 2026, Январь-март 2025
        return lower_text.startswith("январь")

    if period_type == "month":
        # март 2026, март 2025
        return not lower_text.startswith("январь-")

    raise ValueError(f"Неизвестный period_type: {period_type}")


def block_has_real_numbers(raw_df, title_row, start_col, min_valid_rows=3):
    """
    Проверяет, что в блоке действительно есть числа,
    а не #Н/Д / пусто (как в сломанном блоке).

    Смотрим колонку total текущего года (start_col + 4).
    """
    data_start = title_row + 3
    total_col = start_col + 4

    if total_col >= raw_df.shape[1]:
        return False

    values = raw_df.iloc[data_start:data_start + 45, total_col]
    values = pd.to_numeric(values, errors="coerce")

    return int((values > 0).sum()) >= min_valid_rows


def find_latest_period_block_row(
    raw_df,
    current_year=2026,
    previous_year=2025,
    period_type="ytd",
    title_col=0,
    start_col=0,
    skip_broken_blocks=True,
):
    candidates = []

    for row_idx, value in raw_df.iloc[:, title_col].items():
        if not isinstance(value, str):
            continue

        text = value.strip()

        if not is_valid_period_title(
            text=text,
            current_year=current_year,
            previous_year=previous_year,
            period_type=period_type,
        ):
            continue

        month_name = get_month_from_period_title(
            title=text,
            period_type=period_type,
        )

        month_num = MONTH_ORDER.get(normalize_month_name(month_name))

        if month_num is None:
            continue

        candidates.append({
            "month_num": month_num,
            "row_idx": row_idx,
            "title": text,
            "has_data": block_has_real_numbers(
                raw_df=raw_df,
                title_row=row_idx,
                start_col=start_col,
            ),
        })

    if not candidates:
        raise ValueError(
            f"Не найден блок period_type={period_type} "
            f"для {current_year} vs {previous_year}"
        )

    # Отсекаем блоки-пустышки (#Н/Д), например дубль
    # "Январь-май 2026,Январь-май 2025" внизу листа.
    if skip_broken_blocks:
        valid_candidates = [c for c in candidates if c["has_data"]]

        if not valid_candidates:
            raise ValueError(
                f"Все блоки period_type={period_type} пустые (#Н/Д). "
                f"Задай title_row_excel вручную."
            )

        candidates = valid_candidates

    # month_num - основной ключ, row_idx - чтобы выбор был детерминированным
    return sorted(
        candidates,
        key=lambda x: (x["month_num"], x["row_idx"]),
    )[-1]


def parse_top_advertisers_block(
    raw_df,
    title_row,
    current_year=2026,
    previous_year=2025,
    start_col=0,
):
    data_start = title_row + 3

    cols = [
        start_col + 0,  # rank
        start_col + 1,  # advertiser
        start_col + 2,  # offline current
        start_col + 3,  # digital current
        start_col + 4,  # total current
        start_col + 6,  # offline previous
        start_col + 7,  # digital previous
        start_col + 8,  # total previous
    ]

    df = raw_df.iloc[data_start:, cols].copy()

    df.columns = [
        "rank",
        "advertiser_main",
        f"offline_{current_year}",
        f"digital_{current_year}",
        f"total_{current_year}",
        f"offline_{previous_year}",
        f"digital_{previous_year}",
        f"total_{previous_year}",
    ]

    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")

    # Блок заканчивается там, где обрывается сплошная нумерация rank.
    # Иначе ниже по листу подтянется следующий блок
    # (например, дубль "Январь-май" с #Н/Д, где ранги 1-40 тоже проставлены).
    is_row = df["rank"].notna()

    if len(is_row) == 0 or not bool(is_row.iloc[0]):
        raise ValueError(
            f"Пустой блок: в строке Excel {data_start + 1} нет rank. "
            f"Проверь title_row / title_row_excel."
        )

    block_len = int(is_row.cumprod().sum())
    df = df.iloc[:block_len].copy()

    df["rank"] = df["rank"].astype(int)

    # Страховка от строк-хвостов без рекламодателя
    df = df[df["advertiser_main"].notna()].copy()
    df = df[
        df["advertiser_main"].astype(str).str.strip() != ""
    ].copy()

    value_cols = [
        f"offline_{current_year}",
        f"digital_{current_year}",
        f"total_{current_year}",
        f"offline_{previous_year}",
        f"digital_{previous_year}",
        f"total_{previous_year}",
    ]

    for col in value_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    prev_total = df[f"total_{previous_year}"].replace(0, pd.NA)

    df["delta_total"] = (
        df[f"total_{current_year}"] / prev_total - 1
    ).fillna(0)

    return df


def read_top_advertisers_period(
    file_path,
    sheet_name,
    current_year=2026,
    previous_year=2025,
    period_type="ytd",
    title_row_excel=None,
    skip_broken_blocks=True,
):
    """
    period_type:
        "ytd"   -> последний накопленный период, например Январь-март 2026
        "month" -> последний отчётный месяц, например март 2026

    title_row_excel:
        номер строки Excel (как в самом файле, с 1) с заголовком блока,
        например 571 для "Январь-май 2026,Январь-май 2025".
        Если задан - поиск блока не выполняется, берём строго этот блок.
        Нужен, когда в листе лежат несколько блоков с одинаковым заголовком.

    skip_broken_blocks:
        при автопоиске пропускать блоки, где вместо чисел #Н/Д.
    """

    raw = pd.read_excel(
        file_path,
        sheet_name=sheet_name,
        header=None,
        engine="openpyxl",
    )

    if period_type == "ytd":
        title_col = 0      # колонка A
        start_col = 0      # блок A:I

    elif period_type == "month":
        title_col = 19     # колонка T
        start_col = 19     # блок T:AB

    else:
        raise ValueError(f"Неизвестный period_type: {period_type}")

    if title_row_excel is not None:
        row_idx = int(title_row_excel) - 1
        title = str(raw.iloc[row_idx, title_col]).strip()

        block = {
            "row_idx": row_idx,
            "title": title,
            "month_num": MONTH_ORDER.get(
                normalize_month_name(
                    get_month_from_period_title(title, period_type)
                )
            ),
            "manual": True,
        }

        if not block_has_real_numbers(
            raw_df=raw,
            title_row=row_idx,
            start_col=start_col,
        ):
            print(
                f"[warning] В блоке '{title}' (строка Excel {title_row_excel}) "
                f"нет чисел - возможно, указана не та строка."
            )

    else:
        block = find_latest_period_block_row(
            raw_df=raw,
            current_year=current_year,
            previous_year=previous_year,
            period_type=period_type,
            title_col=title_col,
            start_col=start_col,
            skip_broken_blocks=skip_broken_blocks,
        )
        block["manual"] = False

    df = parse_top_advertisers_block(
        raw_df=raw,
        title_row=block["row_idx"],
        current_year=current_year,
        previous_year=previous_year,
        start_col=start_col,
    )


    meta = {
        "sheet_name": sheet_name,
        "period_type": period_type,
        "title": block["title"],
        "month_num": block["month_num"],
        "title_row_excel": block["row_idx"] + 1,
        "start_col_excel": start_col + 1,
        "manual_block": block["manual"],
    }

    return df, meta