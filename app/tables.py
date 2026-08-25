import pandas as pd

MEDIA_MAPPING = {
    'tv_nat': 'нац тв',
    'tv_reg': 'рег тв',
    'tv_spon': 'тв спонсорство',
    'internet': 'интернет',
    'outdoor': 'оон',
    'ooh_new_cites_jun25': 'оон',
    'ooh_new_cites_may24': 'оон',
    'ooh_new_cites_jul25': 'оон',
    'radio': 'радио',
    'press': 'пресса'
}

HAVE_TO_DROP=['газпром-медиа', 'LEOMAX', 'leomax', 'ГАЗПРОМ-МЕДИА', 'МОЙ МИР', 'мой мир']




def normalize_offline(df, five_dict):
    df = df.copy()
    df['keys'] = df['media_type'] + df['ad_id'].astype('str')
    df = pd.merge(df, five_dict, on='keys', how='left')
    df = df[df['include_exclude'] == 'include']             # Можно и удалить, зависит от указаний
    df['date'] = pd.to_datetime(df['date'])
    return df

def normalize_digital(df):
    df = df.copy()
    df.rename(columns={'advertiser': 'advertiser_main',
                       'cost_estimated': 'cost_rub_disc'}, inplace=True)
    df['date'] = pd.to_datetime(df['year'].apply(str) + '-' + df['month'].apply(lambda x: str(x).rjust(2, '0')) + '-' + '01')
    df['media_type_detail'] = 'internet'
    df['retail_category'] = 'yes'
    df['competitor'] = 'yes'
    df['advertiser_type'] = 'producer'
    return df


def normalize_tv_rate(df, five_dict, reverse_map):
    df = df.copy()
    df['keys'] = 'tv' + df['id'].astype('str')
    df['date_full_date'] = df['date']
    df = pd.merge(df, five_dict, how='left', on='keys')
    df['date'] = df['date'].dt.to_period('M').dt.to_timestamp()
    df = df[df['include_exclude'] == 'include']                                 # Можно и удалить, зависит от указаний
    df['message_type_clear'] = df['message_type'].map(reverse_map)
    return df


# def build_top_20_advertisers(tv_norm, radio_norm, ooh_norm, press_norm, digital_norm, year, month=None):
#     """
#     period: 'annual' - за весь год
#             'monthly' - за конкретный месяц
#     year, month - для фильтрации
#     """
#     df = pd.concat([tv_norm, radio_norm, ooh_norm, press_norm, digital_norm], axis=0)[['advertiser_main', 'date', 'cost_rub_disc']]

#     df = df[df['date'].dt.year == year]
#     if month is not None:
#         df = df[df['date'].dt.month == month]

#     df = df.groupby('advertiser_main')['cost_rub_disc'].sum().sort_values(ascending=False)[:20]
#     return df



def build_top_20_advertisers_special(df, digital_dict ,year, month=None):
    """
    Строит топ 20 рекламодателей по суммарным затратам
    year, month - для фильтрации
    """
    df = df[['advertiser_main', 'month num', 'year', 'cost_rub_disc']]
    df = df[df['year'] == year]
    if month is not None:
        df = df[df['month num'] == month]
        digital_df = digital_dict[int(str(year) + str(month))]
    else:
        digital_df = digital_dict[year]

    df = df.groupby('advertiser_main')['cost_rub_disc'].sum()
    df = pd.merge(df, digital_df, how='outer', on='advertiser_main').fillna(0)
    df['total'] = df['cost_rub_disc'] + df['digital']
    
    # Удаление ненужных брендов
    df = df[~df['advertiser_main'].isin(HAVE_TO_DROP)]

    df = df.sort_values('total', ascending=False).reset_index(drop=True)
    return df[['advertiser_main', 'total']]


def build_advertising_comparison(offline_spends_df, digital_dict, year_1, year_2, month=None):
    """
    Строит верхний график 4-го слайда
    offline_spends_df – DataFrame с offline затратами
    digital_dict – словарь, в котором у нас хранятся всевозможные онлайн затарты.
    year_1 – первый год
    year_2 – второй год,
    month – отвечает за месяц, по которому происходит сравнение. Если указан None – значит сравение происходит по году.
    """
    f = build_top_20_advertisers_special(offline_spends_df[offline_spends_df.media_type_detail.isin(['tv reg', 
                                                                                                'tv nat', 
                                                                                                'press', 
                                                                                                'radio', 
                                                                                                'outdoor'])], 
                                    digital_dict, 
                                    year=year_1, month=month)
    s = build_top_20_advertisers_special(offline_spends_df[offline_spends_df.media_type_detail.isin(['tv reg', 
                                                                                                'tv nat', 
                                                                                                'press', 
                                                                                                'radio', 
                                                                                                'outdoor'])], 
                                    digital_dict, 
                                    year=year_2, month=month)
    df = pd.merge(f, s, how='outer', on='advertiser_main', suffixes=['_' + str(year_1), '_' + str(year_2)]).fillna(0).sort_values('total_' + str(year_2), ascending=False).reset_index(drop=True)
    return df[:20]



def build_media_mix_top_20_special(df, digital_dict, year, month=None):
    """
    Строит media-mix у топ 20 рекламодателей по суммарным затратам
    year, month - для фильтрации
    """
    df = df[['advertiser_main', 'media_type_detail', 'month num', 'year', 'cost_rub_disc']]
    df.loc[df['media_type_detail'].isin(['outdoor_new_cites_may2024', 'outdoor_new_cites_jun2025', 'outdoor_new_cites_jul2025']), 'media_type_detail'] = 'outdoor'
    df.rename(columns={'Media type_new': 'Media_type'}, inplace=True)
    df = df[df['year'] == year]
    
    if month is not None:
        df = df[df['month num'] == month]
        digital_df = digital_dict[int(str(year) + str(month))]
    else:
        digital_df = digital_dict[year]

    df = pd.pivot_table(data=df, index='advertiser_main', columns='media_type_detail', values='cost_rub_disc', fill_value=0, aggfunc='sum')
    df = pd.merge(df, digital_df, how='outer', on='advertiser_main').fillna(0)

    # Удаление ненужных брендов
    df = df[~df['advertiser_main'].isin(HAVE_TO_DROP)]
    
    df = df.iloc[df[['outdoor', 'press', 'radio', 'tv nat', 'tv reg', 'digital']].sum(axis=1).argsort()][::-1].reset_index(drop=True)
    return df.loc[:19, ['advertiser_main', 'tv nat', 'tv reg', 'digital', 'outdoor', 'radio', 'press']]


# def build_top_20_brand_tv(df, year, month=None, metric='tvr_18'):
#     """
#     Считает суммарные рейтинги всех компаний
#     """
#     df = df.copy()
#     df = df[df['date'].dt.year == year]

#     if month is not None:
#         df = df[df['date'].dt.month == month]

#     df = df.groupby('brand_main')[metric].sum().sort_values(ascending=False)[:20]
#     return df


def build_top_20_brand_tv_special(df, year, month=None, metric='TVR All 18+'):
    """
    Считает суммарные рейтинги всех компаний
    """
    df = df.copy()
    df = df[df['Year'] == year]

    if month is not None:
        df = df[df['Month№'] == month]

    df = df.groupby('brandName')[metric].sum().sort_values(ascending=False).reset_index()
    return df


def build_tv_nat_rating_comparison(tv_rating, always_show, year_1, year_2, month=None, metric='TVR All 18+'):
    f = build_top_20_brand_tv_special(tv_rating, year=year_1, month=month, metric=metric)
    s = build_top_20_brand_tv_special(tv_rating, year=year_2, month=month, metric=metric)
    df = pd.merge(f, s, how='outer', on='brandName', suffixes=['_' + str(year_1), '_' + str(year_2)]).fillna(0).sort_values(by=metric + '_' + str(year_2), ascending=False)
    df = df[~df['brandName'].isin(HAVE_TO_DROP)]
    always_show = set(df[:20].brandName.tolist()).union(always_show)
    return df[(df['brandName'].isin(always_show))].sort_values(by=metric + '_' + str(year_2), ascending=False)



def build_food_retail_tv(dfs, dates, always_show, delivery='all', metric='cost_rub_disc', group_by='brand_main'):
    """
    Строит суммарные затраты каждой из компании в сегменте food_retail по датам
    delivery – может принимать 3 значения: 'all' – все сегменты, 'offline'– без доставки, 'delivery' – только даставка, по умаолчанию 'all'
    dates — список дат, например:
        ['2025-01-01', '2026-01-01']  # YOY сравнение
        pd.date_range('2025-01-01', '2026-01-01', freq='MS')  # диапазон
    dfs – один df или список df'ов (например [tv_nat_norm, tv_reg_norm])
    always_show – список брендов, которые обязательно нужно включить при отображении
    metric – показатель, по которому мы суммируем
    group_by – поле, по которому мы разбиваем данные на столбцы
    """
    if isinstance(dfs, list):
        df = pd.concat(dfs, axis=0).copy()
    else:
        df = dfs.copy()

    # Вот тут работают все наши фильтры
    #-------------------------------------------

    df = df[df['retail_category'] == 'yes']
    if delivery == 'offline':
        df = df[df['delivery'] != 'доставка']
    elif delivery == 'delivery':
        df = df[df['delivery'] == 'доставка']

    dates = [pd.to_datetime(d) for d in dates]
    df = df[df['date'].isin(dates)]

    df = df[df['advertiser_type'] == 'producer']
    df = df[df['competitor'] == 'yes']
    df = df[df['brand_main'].isin(CONSIDER_BRANDS)]

    #-------------------------------------------

    df = pd.pivot_table(data=df, columns=group_by, index='date', values=metric, aggfunc='sum').fillna(0)

    df['total'] = df.sum(axis=1)

    # Логика, по которой мы будем определять `[sos >= 0.03]` имеет бренд или нет.
    sos = df.div(df['total'], axis=0)
    mean_sos = sos.mean()
    priority_brands = [b for b in always_show if b in df.columns]
    top_brands = list(set(mean_sos[mean_sos >= 0.03].drop('total').index.tolist()).difference(priority_brands))  # Здесь храняться те бренды, у которых sos >= 0.03, но которые не попали в always_show
    other_brands = list(set(df.drop(columns='total').columns).difference(set(set(top_brands).union(priority_brands))))
    df['другие'] = df[other_brands].sum(axis=1)
    
    cols = priority_brands + top_brands + ['другие', 'total']
    
    return df[cols]


def build_slide_12_right_table(dfs, date_1, date_2, always_show, delivery='all'):
    f = build_food_retail_tv(dfs, dates=[date_1], delivery=delivery, always_show=always_show + ['spar', 'metro'], metric='tvr_18')
    s = build_food_retail_tv(dfs, dates=[date_2], delivery=delivery, always_show=always_show + ['spar', 'metro'], metric='tvr_18')
    df = pd.concat([f, s], axis=0).fillna(0).T.drop(index=['total', 'другие'])
    df[f'{date_1} vs {date_2}'] = (df[date_2] - df[date_1])/df[date_1] * 100
    return df



def build_avg_duration(dfs, dates, brand, delivery='all'):
    """
    Строит количество реклам разного хронометража для разных компаний
    delivery – может принимать 3 значения: 'all' – все сегменты, 'offline'– без доставки, 'delivery' – только даставка, по умаолчанию 'all'
    dates — список дат, например:
        ['2025-01-01', '2026-01-01']  # YOY сравнение
        pd.date_range('2025-01-01', '2026-01-01', freq='MS')  # диапазон 
    """
    if isinstance(dfs, list):
        df = pd.concat(dfs, axis=0).copy()
    else:
        df = dfs.copy()

    df = df[df['retail_category'] == 'yes']
    if delivery == 'offline':
        df = df[df['delivery'] != 'доставка']
    elif delivery == 'delivery':
        df = df[df['delivery'] == 'доставка']


    dates = [pd.to_datetime(d) for d in dates]
    df = df[df['date'].isin(dates)]
    df = df[df['brand_main'] == brand]

    df = df[df['advertiser_type'] == 'producer']
    df = df[df['competitor'] == 'yes']
    
    df = df.groupby(['date', 'duration'])['id'].count().reset_index()
    df = pd.pivot_table(data=df, index='date', columns='duration', values='id', aggfunc='sum').fillna(0)

    df['ср. хроно'] = (df * df.columns).sum(axis=1) / df.sum(axis=1)
    return df



def build_media_mix(dfs, always_show, dates, delivery='all', group_by='brand_main'):
    """
    Строит media-mix по суммарным затратам
    delivery – может принимать 3 значения: 'all' – все сегменты, 'offline'– без доставки, 'delivery' – только даставка, по умаолчанию 'all'
    dates — список дат, например:
        ['2025-01-01', '2026-01-01']  # YOY сравнение
        pd.date_range('2025-01-01', '2026-01-01', freq='MS')  # диапазон
    dfs – один df или список df'ов (например [tv_nat_norm, tv_reg_norm])
    always_show – список брендов, которые обязательно нужно включить при отображении
    group_by – поле, по которому мы разбиваем данные на строки
    """
    if isinstance(dfs, list):
        df = pd.concat(dfs).copy()
    else:
        df = df.copy()

    df = df[(df['retail_category'] == 'yes')]
    if delivery == 'offline':
        df = df[df['delivery'] != 'доставка']
    elif delivery == 'delivery':
        df = df[df['delivery'] == 'доставка']

    dates = [pd.to_datetime(d) for d in dates]
    df = df[df['date'].isin(dates)]
    df = df[df['advertiser_type'] == 'producer']
    df = df[df['competitor'] == 'yes']
    

    df['media_type_detail'] = df['media_type_detail'].map(MEDIA_MAPPING).fillna(df['media_type_detail'])

    df = pd.pivot_table(data=df, index='media_type_detail', columns=group_by, values='cost_rub_disc', aggfunc='sum').fillna(0)
    total = df.sum(axis=0).to_frame().T
    total.index = ['total']
    df = pd.concat([df, total], axis=0)
    
    total_sos = total.sum(axis=1).values[0]
    brands_above = [b for b in always_show if b in df.columns]
    top_brands = list(set(df.T[df.T['total']/total_sos >= 0.03].index).difference(brands_above))        # Те бренды, которые имеют sos >0.03, но не попали в always_show
    other_brands = list(set(df.columns).difference(brands_above + top_brands))
    df['other'] = df[other_brands].sum(axis=1)
    df['total'] = df.sum(axis=1)

    df = df[brands_above + top_brands + ['other', 'total']]

    return df.T



def build_delivery_split(dfs, dates, group_by='date'):
    """
    Считает суммарные затраты в разрезе поля delivery по датам
    
    dfs — один df или список df'ов (например [tv_norm, ooh_norm, radio_norm, press_norm, digital_norm])
    dates — список дат, например:
        ['2025-01-01', '2026-01-01']  # YOY сравнение
        pd.date_range('2025-01-01', '2026-01-01', freq='MS')  # диапазон
    group_by — колонка или список колонок для группировки, например:
        'date'  # левый график (динамика сегментов по датам)
        ['brand_main', 'date']  # правый график (динамика по брендам и датам)
    """
    if isinstance(dfs, list):
        df = pd.concat(dfs).copy()
    else:
        df = df.copy()

    df = df[(df['retail_category'] == 'yes') | (df['retail_category'].isna())]

    dates = [pd.to_datetime(d) for d in dates]
    df = df[df['date'].isin(dates)]
    df = df[df['advertiser_type'] == 'producer']
    df = df[df['competitor'] == 'yes']
    df = df[df['brand_main'].isin(CONSIDER_BRANDS)]

    df = pd.pivot_table(data=df, index=group_by, columns='delivery', values='cost_rub_disc', aggfunc='sum').fillna(0)
    df['total'] = df.sum(axis=1)

    return df



def build_tv_sov_year_month(dfs, year, always_show, delivery='all'):
    """
    Строит таблицу SOV для верхних графиков слайда 19.
    Возвращает две строки: месяц отчёта (январь) и накопленный период (весь год).
    
    dfs — один df или список df'ов (например [tv_nat_norm, tv_reg_norm])
    year — год отчёта (например 2026)
    always_show — список брендов, которые обязательно нужно включить при отображении
    delivery — может принимать 3 значения:
        'all' — все сегменты (по умолчанию)
        'offline' — без доставки
        'delivery' — только доставка
    """
    month_tv_df = build_food_retail_tv(
        dfs=dfs,
        dates=[pd.to_datetime(str(year) + '-01-01')],
        delivery=delivery,
        metric='tvr_18',
        always_show=always_show
    )

    year_tv_df = build_food_retail_tv(
        dfs=dfs,
        dates=pd.date_range(pd.to_datetime(str(year-1) + '-01-01'), pd.to_datetime(str(year) + '-12-01'), freq='MS'),
        delivery=delivery,
        metric='tvr_18',
        always_show=always_show
    )


    df = pd.concat([month_tv_df, year_tv_df.sum().to_frame().T]).rename(index={0: str(year-1)}).fillna(0)
    return pd.concat([df.drop(columns=['другие', 'total']), df[['другие', 'total']]], axis=1)



def build_tv_sov_split(nat_rv, reg_tv, always_show, dates, delivery='all'):
    """
    Строит таблицу с разбивкой SOV на Нац. ТВ и Рег. ТВ по брендам.
    Используется для правого нижнего графика слайда 19.
    
    nat_rv — df с данными Нац. ТВ (tv_nat_norm)
    reg_tv — df с данными Рег. ТВ (tv_reg_norm)
    always_show — список брендов, которые обязательно нужно включить при отображении
    dates — список дат, например:
        ['2025-01-01', '2026-01-01']  # YOY сравнение
        pd.date_range('2025-01-01', '2026-01-01', freq='MS')  # диапазон
    delivery — может принимать 3 значения:
        'all' — все сегменты (по умолчанию)
        'offline' — без доставки
        'delivery' — только доставка
    """
    tv_nat_df = build_food_retail_tv(nat_rv, dates, always_show, delivery=delivery, metric='tvr_18')
    tv_reg_df = build_food_retail_tv(reg_tv, dates, always_show, delivery=delivery, metric='tvr_18')

    if len(dates) == 1:
        tv_nat_df = tv_nat_df.T.rename(columns={pd.to_datetime(dates[0]): 'nat_tv'})
        tv_reg_df = tv_reg_df.T.rename(columns={pd.to_datetime(dates[0]): 'reg_tv'})
    else:
        tv_nat_df = tv_nat_df.drop('total', axis=1).sum(axis=1).to_frame().rename(columns={0: 'nat_tv'})
        tv_reg_df = tv_reg_df.drop('total', axis=1).sum(axis=1).to_frame().rename(columns={0: 'reg_tv'})

    df = pd.concat([tv_nat_df, tv_reg_df], axis=1)
    df['total'] = df.sum(axis=1)
    return df



def build_aww_by_city_v2(dfs, dates, always_show, delivery='all'):
    """
    Строит таблицу средненедельных весов (AWW) по городам.
    AWW считается как суммарный TRP города / количество недель где суммарный TRP >= 15.
    
    dfs — один df или список df'ов (например [tv_nat_norm, tv_reg_norm])
    dates — список дат, например:
        ['2026-01-01']  # один месяц
        pd.date_range('2025-01-01', '2026-01-01', freq='MS')  # диапазон
    always_show — список брендов, которые обязательно нужно включить в таблицу
    delivery — может принимать 3 значения:
        'all' — все сегменты (по умолчанию)
        'offline' — без доставки
        'delivery' — только доставка
    
    Возвращает таблицу где:
        index — города (regionName)
        колонки — active_weeks, ср. aww, бренды из always_show
    """
    dfs[1] = dfs[1].drop('tvr_18', axis=1).rename(columns={'tvr_18_not_weighted': 'tvr_18'})
    if isinstance(dfs, list):
        df = pd.concat(dfs).copy()
    else:
        df = dfs.copy()

    dates = [pd.to_datetime(d) for d in dates]
    df = df[df['date'].isin(dates)]

    df = df[df['retail_category'] == 'yes']
    if delivery == 'offline':
        df = df[df['delivery'] != 'доставка']
    elif delivery == 'delivery':
        df = df[df['delivery'] == 'доставка']

    active_brands = df.groupby('regionName')['brand_main'].nunique()


    df['week'] = df['date_full_date'].dt.isocalendar().week
    df['year_week'] = df['date_full_date'].dt.isocalendar().year.astype(str) + '_' + df['week'].astype(str)

    weekly = df.groupby(['regionName', 'year_week'])['tvr_18'].sum().reset_index()
    weekly['tvr >= 15'] = weekly['tvr_18'] >= 15
    brand_week_tvr = weekly.groupby('regionName')['tvr_18'].sum().reset_index()             # Суммарные tvr_18 по регионам
    weekly = weekly.groupby('regionName')['tvr >= 15'].sum().reset_index().rename(columns={'tvr >= 15': 'active_weeks'})

    region_brand_tvr = pd.pivot_table(data=df, index='regionName', columns='brand_main', values='tvr_18', aggfunc='sum').fillna(0).reset_index()    
    region_brand_tvr = pd.concat([region_brand_tvr['regionName'], region_brand_tvr.drop(columns='regionName').div(weekly['active_weeks'], axis=0)], axis=1)

    df = pd.merge(weekly, brand_week_tvr, on='regionName')
    df['ср. aww'] = df['tvr_18'] / df['active_weeks'].replace(0, pd.NA)
    df = pd.merge(region_brand_tvr, df, on='regionName')
    cols = [b for b in always_show if b in df.columns]
    df['active_brands'] = active_brands.values

    return df[['regionName', 'active_weeks', 'active_brands', 'ср. aww'] + cols]


def build_aww_by_city_v3(dfs, dates, always_show, delivery='all'):
    """
    Строит таблицу средненедельных весов (AWW) по городам.
    AWW считается как суммарный TRP города / количество недель где суммарный TRP >= 15.
    
    dfs — один df или список df'ов (например [tv_nat_norm, tv_reg_norm])
    dates — список дат, например:
        ['2026-01-01']  # один месяц
        pd.date_range('2025-01-01', '2026-01-01', freq='MS')  # диапазон
    always_show — список брендов, которые обязательно нужно включить в таблицу
    delivery — может принимать 3 значения:
        'all' — все сегменты (по умолчанию)
        'offline' — без доставки
        'delivery' — только доставка
    
    Возвращает таблицу где:
        index — города (regionName)
        колонки — active_weeks, ср. aww, бренды из always_show
    """
    dfs[1] = dfs[1].drop('tvr_18', axis=1).rename(columns={'tvr_18_not_weighted': 'tvr_18'})
    if isinstance(dfs, list):
        df = pd.concat(dfs).copy()
    else:
        df = dfs.copy()

    dates = [pd.to_datetime(d) for d in dates]
    df = df[df['date'].isin(dates)]

    df = df[df['retail_category'] == 'yes']
    if delivery == 'offline':
        df = df[df['delivery'] != 'доставка']
    elif delivery == 'delivery':
        df = df[df['delivery'] == 'доставка']

    df = df[df['advertiser_type'] == 'producer']
    df = df[df['competitor'] == 'yes']
    df = df[df['brand_main'].isin(CONSIDER_BRANDS)]

    df['start_of_week'] = df['date_full_date'].dt.to_period(freq='W').dt.to_timestamp()
    df = df.groupby(['regionName', 'start_of_week', 'brand_main'])['tvr_18'].sum().reset_index()
    
    # Ищем кол-во активных брендов
    active_brands = df.groupby(['regionName', 'brand_main'])['tvr_18'].sum().reset_index()
    active_brands['tvr >= 15'] = active_brands['tvr_18'] >= 15
    active_brands = active_brands.groupby('regionName')['tvr >= 15'].sum().reset_index().rename(columns={'tvr >= 15': 'active_brands'})

    # Ищем кол-во активных недель у брендов по городам
    brands_active_weeks = df.copy()
    brands_active_weeks['tvr >= 15'] = brands_active_weeks['tvr_18'] >= 15
    brands_active_weeks = brands_active_weeks.groupby(['regionName', 'brand_main'])['tvr >= 15'].sum().reset_index().rename(columns={'tvr >= 15': 'active_weeks'})

    # Ищем кол-во активных недель у городов
    region_active_weeks = df.groupby(['regionName', 'start_of_week'])['tvr_18'].sum().reset_index()
    region_active_weeks['tvr >= 15'] = region_active_weeks['tvr_18'] >= 15
    total_tvr_region = region_active_weeks.groupby('regionName')['tvr_18'].sum().reset_index()
    region_active_weeks = region_active_weeks.groupby('regionName')['tvr >= 15'].sum().reset_index().rename(columns={'tvr >= 15': 'active_weeks'})

    # Ищем ср. aww по региону

    df = df.groupby(['regionName', 'brand_main'])['tvr_18'].sum().reset_index().rename(columns={'tvr_18': 'total_tvr'})
    df['aww_tvr'] = df['total_tvr'].div(brands_active_weeks['active_weeks'], axis=0)

    df = pd.pivot_table(data=df, index='regionName', columns='brand_main', values='aww_tvr').fillna(0).reset_index()
    df['ср. aww'] = total_tvr_region['tvr_18'] / region_active_weeks['active_weeks']
    df['active_brands'] = active_brands['active_brands']

    return df[['regionName', 'active_brands', 'ср. aww'] + df.drop(columns=['active_brands', 'ср. aww']).columns.tolist()]


def build_promo_share(dfs, dates, always_show, delivery='all'):
    """
    Считает долю промо-коммуникации в общем ТВ весе по брендам и датам.
    
    dfs — один df или список df'ов (например [tv_nat_norm, tv_reg_norm])
    dates — список дат, например:
        ['2025-01-01', '2026-01-01']  # YOY сравнение
        pd.date_range('2025-01-01', '2026-01-01', freq='MS')  # диапазон
    always_show — список брендов, которые обязательно нужно включить при отображении
    delivery — может принимать 3 значения:
        'all' — все сегменты (по умолчанию)
        'offline' — без доставки
        'delivery' — только доставка
    
    Возвращает таблицу где:
        index — даты
        колонки — бренды из always_show
        значения — доля промо от общего TRP (от 0 до 1)
    """
    if isinstance(dfs, list):
        df = pd.concat(dfs).copy()
    else:
        df = dfs.copy()

    dates = [pd.to_datetime(d) for d in dates]
    df = df[df['date'].isin(dates)]

    df = df[df['retail_category'] == 'yes']
    if delivery == 'offline':
        df = df[df['delivery'] != 'доставка']
    elif delivery == 'delivery':
        df = df[df['delivery'] == 'доставка']

    df = df[df['advertiser_type'] == 'producer']
    df = df[df['competitor'] == 'yes']
    df = df[df['brand_main'].isin(CONSIDER_BRANDS)]

    df = df.groupby(['brand_main', 'date', 'message_type_clear'])['tvr_18'].sum().reset_index()
    total = df.groupby(['brand_main', 'date'])['tvr_18'].sum().reset_index().rename(columns={'tvr_18': 'total_trp'})
    promo = df[df['message_type_clear'] == 'промо'].groupby(['brand_main', 'date'])['tvr_18'].sum().reset_index().rename(columns={'tvr_18': 'promo_trp'})
    res_df = pd.merge(promo, total, on=['brand_main', 'date'], how='right').fillna(0)
    res_df['promo_share'] = res_df['promo_trp'] / res_df['total_trp']

    df = pd.pivot_table(data=res_df, index='date', columns='brand_main', values='promo_share', aggfunc='mean')

    cols = [b for b in always_show if b in df.columns]
    return df[cols]