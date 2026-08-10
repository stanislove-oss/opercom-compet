"""Конструкторы таблиц для оперком-отчёта.

Слой вычислений: принимает нормализованные датафреймы, возвращает таблицы.
Ничего не знает ни про PowerPoint, ни про источники данных.

Извлечено из main_2__3_.ipynb (ячейки 63-93).
"""

import pandas as pd

from functions.constants import months


DURATION_SERIES_ORDER = [5, 10, 15, 20, 25, "", 50, "Ср.Хроно"]


# ---- из ячейки 63 ----
def build_table(dfs, indexes, cols, estimate_col, groupby_func='sum', dates=None, requires_brands=None, mode='all'):
    if isinstance(dfs, list):
        df = pd.concat(dfs)
    else:
        df = dfs.copy() 

    # Ограничим нужными нам датами
    if dates is not None:
        dates = [pd.to_datetime(d) for d in dates]
        df = df[df['date'].isin(dates)]

    # Оставим только нужные бренды
    if requires_brands:
        df = df[df['brand_main'].isin(requires_brands)]

    if mode == 'offline':
        df = df[(df['delivery'] != 'доставка')]
    elif mode == 'delivery':
        df = df[(df['delivery'] == 'доставка')]

    # Сделаем так, чтобы все исходные колонки и индексы остались
    reference_columns = get_reference_index(
        df,
        cols,
    )

    reference_index = get_reference_index(
        df,
        indexes,
    )

    group_cols = list(dict.fromkeys(indexes + cols))

    if groupby_func == 'sum':
        grouped = (
            df
            .groupby(group_cols, dropna=False)[estimate_col]
            .sum()
            .reset_index()
        )

    elif groupby_func == 'count':
        grouped = (
            df
            .groupby(group_cols, dropna=False)[estimate_col]
            .count()
            .reset_index()
        )

    else:
        raise ValueError(f"Неизвестный groupby_func: {groupby_func}")

    result = pd.pivot_table(
        data=grouped,
        values=estimate_col,
        index=indexes,
        columns=cols,
        aggfunc='sum',
        fill_value=0
    )

    result = result.reindex(
        index=reference_index,
        columns=reference_columns,
        fill_value=0
    )

    return result


# ---- из ячейки 64 ----
def get_reference_index(df, columns, sort_values=True):
    """
    Возвращает полный набор индексов/колонок.

    Если columns = ['brand_main', 'year'],
    вернёт все комбинации:
    все brand_main × все year.
    """

    if isinstance(df, list):
        df = pd.concat(df)
    else:
        df = df.copy()

    if len(columns) == 1:
        values = df[columns[0]].dropna().unique()

        if sort_values:
            values = sorted(values)

        return pd.Index(values, name=columns[0])

    levels = []

    for col in columns:
        values = df[col].dropna().unique()

        if sort_values:
            values = sorted(values)

        levels.append(values)

    return pd.MultiIndex.from_product(
        levels,
        names=columns
    )


# ---- из ячейки 65 ----
def add_total(df):
    if 'total' in df.columns:
        return df
    df = df.copy()
    df['total'] = df.select_dtypes(['int', 'float']).sum(axis=1)
    return df

def make_interval_jan_to_cur_month(year, cur_month=None):
    if cur_month is None:
        raise ValueError("make_interval_jan_to_cur_month: cur_month обязателен")
    return list(pd.date_range(f"{year}-01-01", f"{year}-{str(cur_month).rjust(2, "0")}-01"))

def add_empty_col(df):
    df = df.copy()
    df[''] = 0
    return df

def add_avg(df):
    df = df.copy()
    total_duration = sum([df[col] * col for col in df.columns])
    total_count = df.sum(axis=1)
    df['avg'] = total_duration / total_count
    return df


# ---- из ячейки 66 ----
def build_media_mix_from_adv(dfs, indexes, cols, estimate_col, top_advertisers, key_order_df, cur_year, dates=None):
#     if mode == 'ytd':
#         top_adveriser_investment = top_adveriser_investment_ytd
#         df_key = df_ytd_slide.copy()
#     elif mode == 'month':
#         top_adveriser_investment = top_adveriser_investment_month
#         df_key = df_month_slide.copy()    
    digital_adex_cur_year = top_advertisers[["advertiser_main", f"digital_{cur_year}"]].rename(columns={f'digital_{cur_year}': 'digital'})


    f = build_table(dfs, 
            indexes=indexes,
            cols=cols,
            estimate_col=estimate_col,
            dates=dates).reset_index().merge(digital_adex_cur_year, left_on='advertiser_main', right_on='advertiser_main', how='outer')

            

    f = f.set_index('advertiser_main').loc[key_order_df.reset_index()['advertiser_main']]
    return f


# ---- из ячейки 67 ----
def normalize_duration_for_chart(value):
    """
    Приводит фактическую длину ролика к сериям, которые есть в шаблоне.

    4 сек -> 5
    5 сек -> 5
    10 сек -> 10
    15 сек -> 15
    20 сек -> 20
    25 сек -> 25
    30+ сек -> 50

    В шаблоне серия 50 фактически используется как 'длинные ролики'.
    """
    if pd.isna(value):
        return pd.NA

    value = float(value)

    if value <= 5:
        return 5
    if value <= 10:
        return 10
    if value <= 15:
        return 15
    if value <= 20:
        return 20
    if value <= 25:
        return 25

    return 50


def build_avg_duration_table(dfs, dates=None):
    if isinstance(dfs, list):
        df = pd.concat(dfs, ignore_index=True)
    else:
        df = dfs.copy()

    if dates is not None:
        dates = pd.to_datetime(dates)
        df = df[df["date"].isin(dates)]

    df = df.copy()
    df["duration_bucket"] = df["tv_duration"].apply(normalize_duration_for_chart)

    # 1. TRP по длительностям роликов
    rtg_df = rename_month_year(
        build_table(
            df,
            indexes=["duration_bucket"],
            cols=["date"],
            estimate_col="tvr_18",
        ).T
    ).round()

    # 2. Средний хронометраж
    total_weighted_trp = pd.DataFrame(rtg_df.apply(lambda col: col * col.name).sum(axis=1))
    total_trp = pd.DataFrame(rtg_df.sum(axis=1))
    avg_duration = total_weighted_trp.div(total_trp)


    # 3. Гарантируем ровно те серии, которые есть в шаблоне
    for col in [5, 10, 15, 20, 25, 50]:
        if col not in rtg_df.columns:
            rtg_df[col] = 0

    # Пустая серия-разделитель из шаблона
    rtg_df[""] = 0

    # Средний хроно должен называться именно так, как в шаблоне
    rtg_df["Ср.Хроно"] = avg_duration

    rtg_df = rtg_df[DURATION_SERIES_ORDER]

    return rtg_df


# ---- из ячейки 68 ----
def build_promo_share(dfs, dates=None, requires_brands=None, mode='offline'):
    grouped_df = build_table(dfs, indexes=['brand_main', 'date'], cols=['message_type'], estimate_col='tvr_18', groupby_func='sum', dates=dates, requires_brands=requires_brands, mode=mode).reset_index()
    grouped_df['promo_share'] = grouped_df['промо']/(grouped_df['промо'] + grouped_df['имидж'])
    grouped_df = pd.pivot_table(data=grouped_df, index='date', columns='brand_main', values='promo_share')

    category_df = build_table(dfs, indexes=['date'], cols=['message_type'], estimate_col='tvr_18', groupby_func='sum', dates=dates, requires_brands=None, mode=mode)
    category_df['promo_share_category'] = category_df['промо']/(category_df['промо'] + category_df['имидж'])
    category_df = pd.DataFrame(category_df['promo_share_category'])

    res = pd.merge(grouped_df, category_df, how='inner', left_index=True, right_index=True).T

    return res


# ---- из ячейки 69 ----
def build_aww_table(
    dfs,
    requires_brands=None,
    min_weekly_trp=30,
    region_col='regionName',
    brand_col='brand_main',
    value_col='tvr_18_not_weighted',
    date_col='full_date',
    current_iso_year=None,
    current_month=None,
):
    if isinstance(dfs, list):
        df = pd.concat(dfs)
    else:
        df = dfs.copy()

    df = filter_by_iso_weeks(
        df,
        date_col=date_col,
        full_iso_years=[],
        current_iso_year=current_iso_year,
        current_month=current_month,
    )
    df = add_iso_week_fields(df, date_col=date_col)

    if requires_brands is not None:
        df = df[df[brand_col].isin(requires_brands)]

    weekly = (
        df
        .groupby([region_col, 'iso_year', 'iso_week', brand_col], as_index=False)
        [value_col]
        .sum()
    )

    weekly_active = weekly[
        weekly[value_col] >= min_weekly_trp
    ].copy()

    brand_aww = (
        weekly_active
        .groupby([region_col, brand_col], as_index=False)
        [value_col]
        .mean()
    )

    brand_table = pd.pivot_table(
        data=brand_aww,
        values=value_col,
        index=region_col,
        columns=brand_col,
        aggfunc='first',
        fill_value=0
    )

    active_brands_count = (
        weekly_active
        .groupby(region_col)[brand_col]
        .nunique()
    )

    avg_aww = (
        brand_aww
        .groupby(region_col)[value_col]
        .mean()
    )

    if requires_brands is not None:
        brand_table = brand_table.reindex(columns=requires_brands, fill_value=0)

    res = brand_table.copy()

    res.insert(0, 'ср. AWW', avg_aww)
    res.insert(0, 'Кол-во активных брендов', active_brands_count)

    res = res.fillna(0)

    return res


# ---- из ячейки 70 ----
def filter_by_iso_weeks(
    df,
    date_col="date",
    full_iso_years=(),
    current_iso_year=None,
    current_month=None,
):
    if current_iso_year is None or current_month is None:
        raise ValueError(
            "filter_by_iso_weeks: current_iso_year и current_month обязательны"
        )

    df = df.copy()

    df[date_col] = pd.to_datetime(df[date_col])

    iso = df[date_col].dt.isocalendar()

    df["_iso_year"] = iso["year"].astype(int)
    df["_iso_week"] = iso["week"].astype(int)

    # Находим последнюю ISO-неделю нужного месяца текущего года
    month_days = pd.date_range(
        start=f"{current_iso_year}-{current_month:02d}-01",
        end=pd.Timestamp(current_iso_year, current_month, 1) + pd.offsets.MonthEnd(0),
        freq="D",
    )

    month_iso = month_days.isocalendar()

    max_iso_week = (
        month_iso[month_iso["year"] == current_iso_year]["week"]
        .astype(int)
        .max()
    )

    mask_full_years = df["_iso_year"].isin(full_iso_years)

    mask_current_year_to_month = (
        (df["_iso_year"] == current_iso_year)
        & (df["_iso_week"] <= max_iso_week)
    )

    result = df[
        mask_full_years | mask_current_year_to_month
    ].copy()

    result = result.drop(columns=["_iso_year", "_iso_week"])

    return result


# ---- из ячейки 71 ----
def add_iso_week_fields(df, date_col="date"):
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])

    iso = df[date_col].dt.isocalendar()

    df["iso_year"] = iso["year"].astype(int)
    df["iso_week"] = iso["week"].astype(int)

    # понедельник ISO-недели
    df["week_start"] = (
        df[date_col]
        - pd.to_timedelta(df[date_col].dt.weekday, unit="D")
    )

    # базово месяц недели = месяц понедельника
    df["week_month"] = df["week_start"].values.astype("datetime64[M]")


    # спец-правило для недель на границе года:
    # 29.12.2025 -> ISO 2026-W01 -> январь 2026
    mask_next_iso_year = df["iso_year"] > df["week_start"].dt.year

    df.loc[mask_next_iso_year, "week_month"] = pd.to_datetime(
        df.loc[mask_next_iso_year, "iso_year"].astype(str) + "-01-01"
    )

    return df


# ---- из ячейки 72 ----
def build_aww_ad_id(
    dfs,
    regions=None,
    mode='offline',
    min_weekly_trp=30,
    region_col='regionName',
    brand_col='brand_main',
    value_col='tvr_18_not_weighted',
    date_col='full_date',
    full_iso_years=(),
    current_iso_year=None,
    current_month=None,
):
    """
    Считает Ср. AWW для бренда в разрезе месяцев (week_month),
    аналогично build_aww_table, но по оси дат вместо оси регионов.

    regions:
        список городов. По умолчанию ['москва'].
        Если передать несколько городов, в результате будет
        отдельная колонка AWW по каждому из них (разделение по городам).
        Если город один - результат содержит одну колонку 'aww'.
    """

    if isinstance(dfs, list):
        df = pd.concat(dfs)
    else:
        df = dfs.copy()

    df = filter_by_iso_weeks(
        df,
        date_col=date_col,
        full_iso_years=full_iso_years,
        current_iso_year=current_iso_year,
        current_month=current_month,
    )
    df = add_iso_week_fields(df, date_col=date_col)

    reference_index = get_reference_index(df, ['week_month'])

    if regions is None:
        regions = ['москва']

    df = df[df[region_col].isin(regions)]

    if mode == 'offline':
        df = df[df['delivery'] != 'доставка']
    elif mode == 'delivery':
        df = df[df['delivery'] == 'доставка']

    weekly = (
        df
        .groupby([region_col, 'week_month', 'iso_year', 'iso_week', brand_col], as_index=False)
        [value_col]
        .sum()
    )

    weekly_active = weekly[weekly[value_col] >= min_weekly_trp].copy()

    brand_aww = (
        weekly_active
        .groupby([region_col, 'week_month', brand_col], as_index=False)
        [value_col]
        .mean()
    )

    avg_aww = (
        brand_aww
        .groupby([region_col, 'week_month'], as_index=False)
        [value_col]
        .mean()
        .rename(columns={value_col: 'aww'})
    )

    res = avg_aww.pivot(index='week_month', columns=region_col, values='aww')
    res = res.reindex(index=reference_index, columns=regions, fill_value=0)
    res = res.fillna(0)

    if len(regions) == 1:
        return res.rename(columns={regions[0]: 'aww'})[['aww']]

    return res


# ---- из ячейки 73 ----
def build_tv_tables_with_norm(dfs, dates, mode='all', estimate_col='cost_rub_disc'):
    df = add_total(add_total(rename_month_year(build_table(
        dfs,
        indexes=['date'],
        cols=['brand_main'],
        estimate_col=estimate_col,
        dates=dates,
        mode=mode
    )).T).sort_values('total', ascending=False).T)

    df_norm = df.drop('total', axis=1).div(df['total'], axis=0)

    res = pd.concat([df, df_norm], axis=1)
    return res


# ---- из ячейки 75 ----
def normalize_text(value):
    return str(value).strip().lower()


def month_label(month, year):
    return f"{months[month]}.{str(year)[-2:]}"


def quarter_label(quarter, year):
    return f"Q{quarter}'{str(year)[-2:]}"


def get_quarter_by_month(month):
    return (month - 1) // 3 + 1


def should_collapse_current_year_quarter(
    quarter,
    current_month,
    collapse_lag_months=4,
):
    """
    Определяет, нужно ли сворачивать квартал текущего года.

    Логика:
    Q1 заканчивается в марте.
    Если current_month >= 7, то Q1 сворачиваем.

    Q2 заканчивается в июне.
    Если current_month >= 10, то Q2 сворачиваем.

    Формула:
    quarter_end_month + collapse_lag_months
    """
    quarter_end_month = quarter * 3
    return current_month >= quarter_end_month + collapse_lag_months


def get_period_group(
    date,
    last_year,
    cur_year,
    current_month,
    collapse_lag_months=4,
):
    """
    Присваивает каждой дате период для таблицы.

    last_year:
        всегда кварталы:
        Q1'25, Q2'25, Q3'25, Q4'25

    cur_year:
        месяцы:
        янв.26, фев.26, мар.26 ...

        но завершённые кварталы сворачиваются:
        с июля Q1'26,
        с октября Q2'26.
    """
    date = pd.Timestamp(date)
    year = date.year
    month = date.month

    if year == last_year:
        quarter = get_quarter_by_month(month)
        return quarter_label(quarter, last_year)

    if year == cur_year:
        if month > current_month:
            return None

        quarter = get_quarter_by_month(month)

        if should_collapse_current_year_quarter(
            quarter=quarter,
            current_month=current_month,
            collapse_lag_months=collapse_lag_months,
        ):
            return quarter_label(quarter, cur_year)

        return month_label(month, cur_year)

    return None


def get_period_order(
    last_year,
    cur_year,
    current_month,
    collapse_lag_months=4,
):
    """
    Строит правильный порядок колонок таблицы.
    """

    periods = [
        quarter_label(1, last_year),
        quarter_label(2, last_year),
        quarter_label(3, last_year),
        quarter_label(4, last_year),
    ]

    cur_year_periods = []

    for month in range(1, current_month + 1):
        period = get_period_group(
            date=pd.Timestamp(cur_year, month, 1),
            last_year=last_year,
            cur_year=cur_year,
            current_month=current_month,
            collapse_lag_months=collapse_lag_months,
        )

        if period is not None and period not in cur_year_periods:
            cur_year_periods.append(period)

    return periods + cur_year_periods


def build_chrono_rating_table(
    dfs,
    last_year,
    cur_year,
    current_month,
    date_col="date",
    segment_col="segment",
    rating_col="tvr_18",
    chrono_col="chrono",
    promo_values=("промо",),
    image_values=("имидж",),
    chrono_method="mean",
    collapse_lag_months=4,
    fill_value=0,
):
    """
    Строит таблицу:

        Средний Хроно
        Промо
        Имидж
        Итого

    По колонкам:
        Q1 прошлого года, Q2 прошлого года, ...
        месяцы/свёрнутые кварталы текущего года.

    chrono_method:
        "mean"     -> простое среднее хронометража по всем строкам
        "weighted" -> sum(chrono * rating) / sum(rating) по всем строкам
    """

    if isinstance(dfs, list):
        df = pd.concat(dfs, ignore_index=True)
    else:
        df = dfs.copy()

    df[date_col] = pd.to_datetime(df[date_col])

    promo_norm = {normalize_text(x) for x in promo_values}
    image_norm = {normalize_text(x) for x in image_values}
    valid_segments = promo_norm | image_norm

    df["_segment_norm"] = df[segment_col].apply(normalize_text)

    df = df[df["_segment_norm"].isin(valid_segments)].copy()

    df["_period_group"] = df[date_col].apply(
        lambda x: get_period_group(
            date=x,
            last_year=last_year,
            cur_year=cur_year,
            current_month=current_month,
            collapse_lag_months=collapse_lag_months,
        )
    )

    df = df[df["_period_group"].notna()].copy()

    period_order = get_period_order(
        last_year=last_year,
        cur_year=cur_year,
        current_month=current_month,
        collapse_lag_months=collapse_lag_months,
    )

    def _aggregate_chrono(data):
        if chrono_method == "mean":
            return (
                data
                .groupby("_period_group")[chrono_col]
                .mean()
            )

        if chrono_method == "weighted":
            tmp = data.copy()
            tmp["_weighted_chrono"] = tmp[chrono_col] * tmp[rating_col]

            grouped = (
                tmp
                .groupby("_period_group")
                .agg(
                    weighted_chrono_sum=("_weighted_chrono", "sum"),
                    rating_sum=(rating_col, "sum"),
                )
            )

            return (
                grouped["weighted_chrono_sum"]
                / grouped["rating_sum"].replace(0, pd.NA)
            )

        raise ValueError(
            "chrono_method должен быть 'mean' или 'weighted'"
        )

    chrono_row = _aggregate_chrono(df)

    promo_row = _aggregate_chrono(
        df[df["_segment_norm"].isin(promo_norm)]
    )

    image_row = _aggregate_chrono(
        df[df["_segment_norm"].isin(image_norm)]
    )

    result = pd.DataFrame(
        {
            "Промо": promo_row,
            "Имидж": image_row,
            "Итого": chrono_row,
        }
    ).T

    result = result.reindex(columns=period_order, fill_value=fill_value)

    result = result.fillna(fill_value)

    return result


# ---- из ячейки 81 ----
def flatten_brand_period_index_with_empty_rows(
    df,
    brand_level=0,
    period_level=1,
    brand_title=True,
    empty_row_suffix="_empty",
):
    df = df.copy()

    if not isinstance(df.index, pd.MultiIndex):
        return df

    rows = []
    index_values = []

    for brand, group in df.groupby(level=brand_level, sort=False):

        for idx, row in group.iterrows():
            brand_name = str(idx[brand_level]).strip()
            period = str(idx[period_level]).strip()

            year_suffix = period.split("'")[-1]
            year_suffix = "'" + year_suffix

            if brand_title:
                brand_name = brand_name.title()

            index_values.append(f"{brand_name}{year_suffix}")
            rows.append(row)

        # пустая строка после пары бренда
        empty_row = pd.Series(
            0,
            index=df.columns,
            name=f"{brand}{empty_row_suffix}",
        )

        index_values.append("")
        rows.append(empty_row)

    result = pd.DataFrame(rows)
    result.index = index_values
    result.index.name = "cat"

    return result


# ---- из ячейки 82 ----
def renamer_jan_cur_month(df, cur_month=None, level=None):
    if cur_month is None:
        raise ValueError("cur_month обязателен")
    
    df = df.copy()
    
    if isinstance(df.columns, pd.MultiIndex):
        level = level if level is not None else 1
        new_cols = []
        for col in df.columns:
            renamed = f"янв-{months[cur_month]}'{(''.join([ch for ch in str(col[level]) if ch.isnumeric()]))[2:]}"
            new_cols.append(col[:level] + (renamed,) + col[level+1:])
        df.columns = pd.MultiIndex.from_tuples(new_cols)
    else:
        for col in df.select_dtypes([int, float]).columns:
            df = df.rename(columns={col: f"янв-{months[cur_month]}'{(''.join([ch for ch in str(col) if ch.isnumeric()]))[2:]}"})
    
    return df

def rename_to_month(df, cur_month=None):
    if cur_month is None:
        raise ValueError("cur_month обязателен")
    df = df.copy()
    for col in df.select_dtypes([int, float]).columns:
        df = df.rename(columns={col: f"{months[cur_month]}'{''.join([ch for ch in str(col) if ch.isnumeric()])[2:]}"})
    return df

def rename_month_year(df):
    df = df.copy()

    df.index = df.index.strftime('%y-%m').map(lambda x: months[int(x.split('-')[1])] + '.' + x.split('-')[0])
    return df


# ---- из ячейки 84 ----
def sort_grouped_by_period_total(
    df,
    group_level=0,
    period_level=1,
    sort_period=None,
    sort_col="total",
    period_order=None,
    ascending=False,
):
    if sort_period is None:
        raise ValueError("sort_grouped_by_period_total: sort_period обязателен")

    """
    Сортирует MultiIndex dataframe группами.

    Пример:
    index = brand_main × period

    Сортировка идёт по total выбранного периода, например янв-мар'26,
    но строки внутри бренда остаются рядом:
        brand A / янв-мар'25
        brand A / янв-мар'26
        brand B / янв-мар'25
        brand B / янв-мар'26
    """

    df = df.copy()

    if not isinstance(df.index, pd.MultiIndex):
        raise ValueError("Ожидается MultiIndex в index dataframe")

    if period_order is None:
        periods = df.index.get_level_values(period_level).unique().tolist()
        period_order = sorted(periods)

    # достаём значение total за нужный период для каждого бренда
    sort_values = {}

    for group_name in df.index.get_level_values(group_level).unique():
        try:
            value = df.loc[(group_name, sort_period), sort_col]
        except KeyError:
            value = 0

        sort_values[group_name] = value

    # порядок брендов по total нужного периода
    sorted_groups = sorted(
        sort_values,
        key=lambda x: sort_values[x],
        reverse=not ascending,
    )

    # собираем новый порядок индекса:
    # каждый бренд, внутри него периоды в нужном порядке
    new_index = []

    for group_name in sorted_groups:
        for period in period_order:
            idx = (group_name, period)

            if idx in df.index:
                new_index.append(idx)

    return df.loc[new_index]


# ---- из ячейки 86 ----
def norm_table(df):
    df = df.copy()
    if 'total' not in df.columns:
        total = df.sum(axis=1)
    else:
        total = df['total']

    df = df.div(total, axis=0)
    return df


# ---- из ячейки 88 ----
def filter_indexes(df, indexes=None, columns=None):
    if indexes is not None:
        indexes = [idx for idx in indexes if idx in df.index]
        df = df.loc[indexes]
    if columns is not None:
        columns = [col for col in columns if col in df.columns]
        df = df[columns]
    return df


# ---- из ячейки 89 ----
def sort_necessary_cols(df: pd.DataFrame, nec_cols: list | tuple) -> pd.DataFrame:
    nec_cols = [col for col in nec_cols if col in df.columns]
    mis_cols = [col for col in df.columns if col not in nec_cols]
    cols = nec_cols + mis_cols
    return df[cols]


# ---- из ячейки 91 ----
def find_diff_between_periods(df):
    diffs = (df[df.columns[1]] - df[df.columns[0]]) / df[df.columns[0]]
    res = pd.DataFrame(index=df.index, columns=['diff'], data=diffs).fillna('new').replace(float('inf'), 'new')
    if '' in res.index:
        res = res.drop(index='')
    return res


# ---- из ячейки 93 ----
def add_empty_month(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    last = pd.to_datetime(df.index).max()
    end = pd.Timestamp(year=last.year, month=12, day=1)
    full = pd.date_range(df.index.min(), end, freq="MS")

    df = df.reindex(index=full, fill_value=0)
    return df
