# Структура базы ClickHouse `other_media_x5_v1`

## Таблицы

| таблица | движок | строк |
| --- | --- | --- |
| `digital_investments` | MergeTree | 50 175 |
| `radio_dss_x5_v1` | MergeTree | 954 143 |
| `radio_monthly_view` | View | — |

## digital_investments

| колонка | тип | описание |
| --- | --- | --- |
| `brand_main` | `String` |  |
| `brand_segment` | `String` |  |
| `advertiser` | `String` |  |
| `brand` | `String` |  |
| `delivery` | `String` |  |
| `site` | `String` |  |
| `marketing_channel` | `String` |  |
| `date` | `String` |  |
| `year` | `UInt16` |  |
| `quarter` | `UInt8` |  |
| `month` | `UInt8` |  |
| `paid_marketing_channels` | `UInt8` |  |
| `cost_NOT_FOR_USE` | `Float64` |  |
| `cost_estimated` | `Float64` |  |
| `help` | `String` |  |
| `coef` | `Float64` |  |

**Примеры значений** (первые 3 строк):

| колонка | строка 1 | строка 2 | строка 3 |
| --- | --- | --- | --- |
| `brand_main` | FIX PRICE | FIX PRICE | FIX PRICE |
| `brand_segment` | OTHER | OTHER | OTHER |
| `advertiser` | FIX PRICE | FIX PRICE | FIX PRICE |
| `brand` | FIX PRICE | FIX PRICE | FIX PRICE |
| `delivery` | ОФФЛАЙН | ОФФЛАЙН | ОФФЛАЙН |
| `site` | FIX-PRICE.COM | FIX-PRICE.COM | FIX-PRICE.COM |
| `marketing_channel` | DIRECT | DISPLAY_ADS | MAIL |
| `date` | 2024-01 | 2024-01 | 2024-01 |
| `year` | 2024 | 2024 | 2024 |
| `quarter` | 1 | 1 | 1 |
| `month` | 1 | 1 | 1 |
| `paid_marketing_channels` | 0 | 1 | 1 |
| `cost_NOT_FOR_USE` | 0.0 | 1230891.77492 | 201866.63644 |
| `cost_estimated` | 0.0 | 1230891.77492 | 201866.63644 |
| `help` | 20241FIX PRICE | 20241FIX PRICE | 20241FIX PRICE |
| `coef` | 1.0 | 1.0 | 1.0 |

## radio_dss_x5_v1

| колонка | тип | описание |
| --- | --- | --- |
| `media_key_id` | `String` |  |
| `media_type` | `LowCardinality(String)` |  |
| `Clip ID` | `Int64` |  |
| `Advertisers list` | `Nullable(String)` |  |
| `Brands list` | `Nullable(String)` |  |
| `Subbrands list` | `Nullable(String)` |  |
| `Models list` | `Nullable(String)` |  |
| `Article list2` | `Nullable(String)` |  |
| `Article list3` | `Nullable(String)` |  |
| `Article list4` | `Nullable(String)` |  |
| `Clip` | `Nullable(String)` |  |
| `Clip description` | `Nullable(String)` |  |
| `First issue date` | `Nullable(Date)` |  |
| `Week day` | `LowCardinality(String)` |  |
| `Date` | `Date` |  |
| `Week` | `UInt8` |  |
| `Week start` | `Date` |  |
| `Week num` | `UInt8` |  |
| `month` | `LowCardinality(String)` |  |
| `month num` | `UInt8` |  |
| `year` | `UInt16` |  |
| `Region` | `Nullable(String)` |  |
| `Clip placement` | `Nullable(String)` |  |
| `Station` | `Nullable(String)` |  |
| `Station original` | `Nullable(String)` |  |
| `Holding` | `Nullable(String)` |  |
| `Clip type` | `Nullable(String)` |  |
| `Clip expected duration` | `Nullable(Int32)` |  |
| `Programme` | `Nullable(String)` |  |
| `Clip position` | `Nullable(String)` |  |
| `Time start` | `Nullable(String)` |  |
| `Cost RUB` | `Nullable(Decimal(20, 0))` |  |
| `disc` | `Nullable(Decimal(10, 8))` |  |
| `CostRUB_disc` | `Nullable(Decimal(20, 8))` |  |
| `Quantity` | `Int32` |  |
| `Volume` | `Nullable(Int32)` |  |
| `advertiser_type` | `Nullable(String)` |  |
| `advertiser_main` | `Nullable(String)` |  |
| `brand_main` | `Nullable(String)` |  |
| `category_1` | `Nullable(String)` |  |
| `category_2` | `Nullable(String)` |  |
| `include_exclude` | `Nullable(String)` |  |
| `cleaning_flag` | `UInt8` |  |
| `category_4` | `Nullable(String)` |  |
| `category_5` | `Nullable(String)` |  |
| `category_6` | `Nullable(String)` |  |
| `category_7` | `Nullable(String)` |  |
| `category_8` | `Nullable(String)` |  |
| `category_9` | `Nullable(String)` |  |
| `category_10` | `Nullable(String)` |  |
| `category_11` | `Nullable(String)` |  |
| `category_12` | `Nullable(String)` |  |
| `category_13` | `Nullable(String)` |  |
| `category_14` | `Nullable(String)` |  |
| `category_15` | `Nullable(String)` |  |
| `category_16` | `Nullable(String)` |  |
| `category_17` | `Nullable(String)` |  |
| `category_18` | `Nullable(String)` |  |
| `category_19` | `Nullable(String)` |  |
| `category_20` | `Nullable(String)` |  |
| `category_21` | `Nullable(String)` |  |
| `category_22` | `Nullable(String)` |  |
| `category_23` | `Nullable(String)` |  |
| `load_datetime` | `DateTime` |  |
| `load_id` | `String` |  |

**Примеры значений** (первые 3 строк):

| колонка | строка 1 | строка 2 | строка 3 |
| --- | --- | --- | --- |
| `media_key_id` | RADIO_2346482 | RADIO_2346482 | RADIO_2346482 |
| `media_type` | RADIO | RADIO | RADIO |
| `Clip ID` | 2346482 | 2346482 | 2346482 |
| `Advertisers list` | PIZZA RONI | PIZZA RONI | PIZZA RONI |
| `Brands list` | PIZZA RONI | PIZZA RONI | PIZZA RONI |
| `Subbrands list` | PIZZA RONI | PIZZA RONI | PIZZA RONI |
| `Models list` | PIZZA RONI ДОСТАВКА ГОТОВОЙ ЕДЫ | PIZZA RONI ДОСТАВКА ГОТОВОЙ ЕДЫ | PIZZA RONI ДОСТАВКА ГОТОВОЙ ЕДЫ |
| `Article list2` | УСЛУГИ ОБЩЕСТВЕННОГО ПИТАНИЯ | УСЛУГИ ОБЩЕСТВЕННОГО ПИТАНИЯ | УСЛУГИ ОБЩЕСТВЕННОГО ПИТАНИЯ |
| `Article list3` | УСЛУГИ ОБЩЕСТВЕННОГО ПИТАНИЯ | УСЛУГИ ОБЩЕСТВЕННОГО ПИТАНИЯ | УСЛУГИ ОБЩЕСТВЕННОГО ПИТАНИЯ |
| `Article list4` | ДОСТАВКА ГОТОВОЙ ЕДЫ | ДОСТАВКА ГОТОВОЙ ЕДЫ | ДОСТАВКА ГОТОВОЙ ЕДЫ |
| `Clip` | ПИЦЦА РОНИ (PIZZA RONI) ДОСТАВКА ГОТОВОЙ | ПИЦЦА РОНИ (PIZZA RONI) ДОСТАВКА ГОТОВОЙ | ПИЦЦА РОНИ (PIZZA RONI) ДОСТАВКА ГОТОВОЙ |
| `Clip description` | ПИЦЦА PIZZA RONI - ИХ ДОСТАВКА ВСЕХ ОБГО | ПИЦЦА PIZZA RONI - ИХ ДОСТАВКА ВСЕХ ОБГО | ПИЦЦА PIZZA RONI - ИХ ДОСТАВКА ВСЕХ ОБГО |
| `First issue date` | 2022-09-21 | 2022-09-21 | 2022-09-21 |
| `Week day` | ВОСКРЕСЕНЬЕ | ВОСКРЕСЕНЬЕ | ВОСКРЕСЕНЬЕ |
| `Date` | 2023-01-01 | 2023-01-01 | 2023-01-01 |
| `Week` | 52 | 52 | 52 |
| `Week start` | 2022-12-26 | 2022-12-26 | 2022-12-26 |
| `Week num` | 52 | 52 | 52 |
| `month` | ЯНВАРЬ | ЯНВАРЬ | ЯНВАРЬ |
| `month num` | 1 | 1 | 1 |
| `year` | 2023 | 2023 | 2023 |
| `Region` | САНКТ-ПЕТЕРБУРГ | САНКТ-ПЕТЕРБУРГ | САНКТ-ПЕТЕРБУРГ |
| `Clip placement` | LOCAL | LOCAL | LOCAL |
| `Station` | РАДИО РЕКОРД (САНКТ-ПЕТЕРБУРГ) | РАДИО РЕКОРД (САНКТ-ПЕТЕРБУРГ) | РАДИО РЕКОРД (САНКТ-ПЕТЕРБУРГ) |
| `Station original` | RADIO RECORD (SAINT-PETESRBURG) | RADIO RECORD (SAINT-PETESRBURG) | RADIO RECORD (SAINT-PETESRBURG) |
| `Holding` | N/A | N/A | N/A |
| `Clip type` | РОЛИК | РОЛИК | РОЛИК |
| `Clip expected duration` | 17 | 17 | 17 |
| `Programme` | МЕСТНОЕ ВЕЩАНИЕ | МЕСТНОЕ ВЕЩАНИЕ | МЕСТНОЕ ВЕЩАНИЕ |
| `Clip position` | ПОСЛЕДНИЙ | ПОСЛЕДНИЙ | ПОСЛЕДНИЙ |
| `Time start` | 11:16 | 12:16 | 14:15 |
| `Cost RUB` | 7875 | 7875 | 7875 |
| `disc` | 0.65000000 | 0.65000000 | 0.65000000 |
| `CostRUB_disc` | 2756.25000000 | 2756.25000000 | 2756.25000000 |
| `Quantity` | 1 | 1 | 1 |
| `Volume` | 17 | 17 | 17 |
| `advertiser_type` | PRODUCER | PRODUCER | PRODUCER |
| `advertiser_main` | PIZZA RONI (С-ПБ) | PIZZA RONI (С-ПБ) | PIZZA RONI (С-ПБ) |
| `brand_main` | !OTHER | !OTHER | !OTHER |
| `category_1` | NO | NO | NO |
| `category_2` | ДОСТАВКА ГОТОВОЙ ЕДЫ | ДОСТАВКА ГОТОВОЙ ЕДЫ | ДОСТАВКА ГОТОВОЙ ЕДЫ |
| `include_exclude` | EXCLUDE | EXCLUDE | EXCLUDE |
| `cleaning_flag` | 2 | 2 | 2 |
| `category_4` | NO | NO | NO |
| `category_5` | None | None | None |
| `category_6` | None | None | None |
| `category_7` | None | None | None |
| `category_8` | NO | NO | NO |
| `category_9` | None | None | None |
| `category_10` | None | None | None |
| `category_11` | None | None | None |
| `category_12` | None | None | None |
| `category_13` | PIZZA RONI (С-ПБ) ДОСТАВКА ГОТОВОЙ ЕДЫ | PIZZA RONI (С-ПБ) ДОСТАВКА ГОТОВОЙ ЕДЫ | PIZZA RONI (С-ПБ) ДОСТАВКА ГОТОВОЙ ЕДЫ |
| `category_14` | None | None | None |
| `category_15` | None | None | None |
| `category_16` | None | None | None |
| `category_17` | None | None | None |
| `category_18` | None | None | None |
| `category_19` | None | None | None |
| `category_20` | None | None | None |
| `category_21` | None | None | None |
| `category_22` | None | None | None |
| `category_23` | None | None | None |
| `load_datetime` | 2026-08-25 14:48:11+03:00 | 2026-08-25 14:48:11+03:00 | 2026-08-25 14:48:11+03:00 |
| `load_id` | RADIO_20230101_20231231_20260825_114811_ | RADIO_20230101_20231231_20260825_114811_ | RADIO_20230101_20231231_20260825_114811_ |

## radio_monthly_view

| колонка | тип | описание |
| --- | --- | --- |
| `media_key_id` | `String` |  |
| `adId` | `Int64` |  |
| `media_type` | `LowCardinality(String)` |  |
| `advertiserListName` | `Nullable(String)` |  |
| `brandListName` | `Nullable(String)` |  |
| `subbrandListName` | `Nullable(String)` |  |
| `modelListName` | `Nullable(String)` |  |
| `articleList2Name` | `Nullable(String)` |  |
| `articleList3Name` | `Nullable(String)` |  |
| `articleList4Name` | `Nullable(String)` |  |
| `adName` | `Nullable(String)` |  |
| `adNotes` | `Nullable(String)` |  |
| `adFirstIssueDate` | `Nullable(Date)` |  |
| `Week day` | `LowCardinality(String)` |  |
| `Date` | `Date` |  |
| `Week` | `UInt8` |  |
| `Week start` | `Date` |  |
| `Week num` | `UInt8` |  |
| `month` | `LowCardinality(String)` |  |
| `month num` | `UInt8` |  |
| `month_start` | `Date` |  |
| `month_number` | `UInt8` |  |
| `year` | `UInt16` |  |
| `regionName` | `Nullable(String)` |  |
| `adDistributionType_name` | `Nullable(String)` |  |
| `companyName` | `Nullable(String)` |  |
| `netName` | `Nullable(String)` |  |
| `holdingName` | `Nullable(String)` |  |
| `adTypeName` | `Nullable(String)` |  |
| `adStandardDuration` | `Nullable(Int32)` |  |
| `programmeName` | `Nullable(String)` |  |
| `adPositionName` | `Nullable(String)` |  |
| `Time start` | `Nullable(String)` |  |
| `advertiser_type` | `Nullable(String)` |  |
| `advertiser_main` | `Nullable(String)` |  |
| `brand_main` | `Nullable(String)` |  |
| `competitor` | `Nullable(String)` |  |
| `category` | `Nullable(String)` |  |
| `retail_category` | `Nullable(String)` |  |
| `delivery` | `Nullable(String)` |  |
| `product_type` | `Nullable(String)` |  |
| `message_type` | `Nullable(String)` |  |
| `loyalty_category` | `Nullable(String)` |  |
| `advertiser_type_loyalty` | `Nullable(String)` |  |
| `brand_loyalty` | `Nullable(String)` |  |
| `coop` | `Nullable(String)` |  |
| `campaign_name` | `Nullable(String)` |  |
| `product_name` | `Nullable(String)` |  |
| `new_campaign_name` | `Nullable(String)` |  |
| `ConsolidatedCostRUB` | `Nullable(Decimal(38, 0))` |  |
| `ConsolidatedCostRUB_disc` | `Nullable(Decimal(38, 8))` |  |
| `Quantity` | `Int64` |  |
| `Volume` | `Nullable(Int64)` |  |

**Примеры значений** (первые 3 строк):

| колонка | строка 1 | строка 2 | строка 3 |
| --- | --- | --- | --- |
| `media_key_id` | RADIO_2425205 | RADIO_2390276 | RADIO_2399644 |
| `adId` | 2425205 | 2390276 | 2399644 |
| `media_type` | RADIO | RADIO | RADIO |
| `advertiserListName` | ИНТЕРНЕТ РЕШЕНИЯ | СБЕР | X5 GROUP |
| `brandListName` | COFFESSO; OZON | ЕАПТЕКА; СБЕР БАНК | ВЕРНЕР; ЧИЖИК (СУПЕРМАРКЕТ) |
| `subbrandListName` | COFFESSO; OZON | ЕАПТЕКА; СБЕР БАНК СПАСИБО | ВЕРНЕР; ЧИЖИК (СУПЕРМАРКЕТ) |
| `modelListName` | COFFESSO КОФЕ НАТУРАЛЬНЫЙ В КАПСУЛАХ; OZ | ЕАПТЕКА АПТЕКА; СБЕР БАНК СПАСИБО БОНУСН | ВЕРНЕР СОСИСКИ; ЧИЖИК СУПЕРМАРКЕТ |
| `articleList2Name` | БЕЗАЛКОГОЛЬНЫЕ НАПИТКИ; УСЛУГИ В ОБЛАСТИ | УСЛУГИ В ОБЛАСТИ ТОРГОВЛИ; УСЛУГИ ФИНАНС | ПРОДУКТЫ ПИТАНИЯ; УСЛУГИ В ОБЛАСТИ ТОРГО |
| `articleList3Name` | ИНТЕРНЕТ-ТОРГОВЛЯ; КОФЕ И КАКАО | ТОРГОВЫЕ ОРГАНИЗАЦИИ; УСЛУГИ УПРАВЛЕНИЯ  | МЯСО-КОЛБАСНЫЕ ИЗДЕЛИЯ; ТОРГОВЫЕ ОРГАНИЗ |
| `articleList4Name` | КОФЕ НАТУРАЛЬНЫЙ В КАПСУЛАХ; МАРКЕТПЛЕЙС | АПТЕКИ И ОПТИКИ; УСЛУГИ БАНКОВ | СОСИСКИ; СУПЕРМАРКЕТЫ |
| `adName` | ОЗОН (OZON) МАРКЕТПЛЕЙС (COFFESSO, ИНТЕР | ЕАПТЕКА АПТЕКА (СПАСИБО) WWW | ЧИЖИК СУПЕРМАРКЕТ (ВЕРНЕР СОСИСКИ, ДО 8  |
| `adNotes` | ГОТОВЬТЕСЬ К ЛЕТУ И ЖАРКИМ СКИДКАМ. ЛЕТО | ПОКУПАЙ В ЕАПТЕКЕ, ПОЛУЧАЙ КЭШБЭК ДО 100 | ЧИЖИК - ПРОДУКТОВЫЙ МАГАЗИН ЧТО НАДО, БЕ |
| `adFirstIssueDate` | 2024-05-02 | 2023-08-09 | 2023-10-26 |
| `Week day` | ПЯТНИЦА | ВТОРНИК | ВОСКРЕСЕНЬЕ |
| `Date` | 2024-05-10 | 2023-08-22 | 2023-10-29 |
| `Week` | 19 | 34 | 43 |
| `Week start` | 2024-05-06 | 2023-08-21 | 2023-10-23 |
| `Week num` | 19 | 34 | 43 |
| `month` | МАЙ | АВГУСТ | ОКТЯБРЬ |
| `month num` | 5 | 8 | 10 |
| `month_start` | 2024-05-01 | 2023-08-01 | 2023-10-01 |
| `month_number` | 5 | 8 | 10 |
| `year` | 2024 | 2023 | 2023 |
| `regionName` | МОСКВА | МОСКВА | МОСКВА |
| `adDistributionType_name` | NETWORK | NETWORK | LOCAL |
| `companyName` | НОВОЕ РАДИО | РУССКОЕ РАДИО | РУССКОЕ РАДИО |
| `netName` | NEW RADIO | RUSSKOE RADIO | RUSSKOE RADIO |
| `holdingName` | ЕВРОПЕЙСКАЯ МЕДИА ГРУППА | РУССКАЯ МЕДИА ГРУППА | РУССКАЯ МЕДИА ГРУППА |
| `adTypeName` | РОЛИК | РОЛИК | РОЛИК |
| `adStandardDuration` | 20 | 16 | 20 |
| `programmeName` | ПОЗНАВАТЕЛЬНО-МУЗЫКАЛЬНЫЙ ЭФИР | МУЗЫКАЛЬНО-ИНФОРМАЦИОННЫЙ ЭФИР | МУЗЫКАЛЬНО-ИНФОРМАЦИОННЫЙ ЭФИР |
| `adPositionName` | ВТОРОЙ | СРЕДНИЙ | ВТОРОЙ |
| `Time start` | 12:39 | 13:39 | 14:51 |
| `advertiser_type` | PRODUCER | PRODUCER | PRODUCER |
| `advertiser_main` | ИНТЕРНЕТ РЕШЕНИЯ | СБЕР | X5 GROUP |
| `brand_main` | OZON | !OTHER | ЧИЖИК (СУПЕРМАРКЕТ) |
| `competitor` | YES | NO | YES |
| `category` | МАРКЕТПЛЕЙСЫ | !OTHER | СУПЕРМАРКЕТЫ |
| `retail_category` | YES | NO | YES |
| `delivery` | ДОСТАВКА | None | ОФФЛАЙН |
| `product_type` | БАКАЛЕЯ | None | КОЛБАСНЫЕ ИЗДЕЛИЯ |
| `message_type` | ЦЕНОВОЕ ПРОМО | None | ЦЕНОВОЕ ПРОМО |
| `loyalty_category` | NO | YES | NO |
| `advertiser_type_loyalty` | None | PRODUCER | None |
| `brand_loyalty` | None | СБЕР БАНК СПАСИБО | None |
| `coop` | None | None | None |
| `campaign_name` | None | None | None |
| `product_name` | COFFESSO КОФЕ НАТУРАЛЬНЫЙ В КАПСУЛАХ | СБЕР БАНК СПАСИБО БОНУСНАЯ ПРОГРАММА; СБ | ВЕРНЕР СОСИСКИ |
| `new_campaign_name` | None | None | None |
| `ConsolidatedCostRUB` | 72845 | 118800 | 84480 |
| `ConsolidatedCostRUB_disc` | 18211.25000000 | 23760.00000000 | 16896.00000000 |
| `Quantity` | 1 | 1 | 1 |
| `Volume` | 20 | 16 | 20 |

---

## Что осталось проверить на боевой базе

Схема отвечает, как называются колонки, но не что в них лежит. Переезд
опирается на четыре допущения — их стоит подтвердить до того, как цифры
уедут в отчёт.

1. **Соседняя витрина затрат.** Затраты берутся из `COST_TABLE`, а он по
   умолчанию указывает в другую базу (`mediascope_x5_big_v23`), потому что
   в основной они заканчиваются раньше. Устроена ли `media_costs_union`
   в ней так же:

       python scripts/dump_schema.py --database mediascope_x5_big_v23

2. **Ключ мёржа.** Выгрузка соединяется со справочником по `media_key_id`.
   Значения в базе и в Google-таблице должны совпадать по форме
   (регистр приводится, остальное — нет). Если не совпадут, мёрж не найдёт
   ни одной строки, и отчёт получится пустым, не упав — ноутбук на этот
   случай падает сам, с явным текстом.

3. **Фильтры estat и cleaning_flag.** В соседнем проекте на этой же базе они
   не режут ничего. Насколько режут на выборке оперкома:

       python scripts/check_filters.py

4. **Совпадают ли цифры со старой базой.** Ради этого прежний набор запросов
   и оставлен рядом:

       python scripts/compare_engines.py --old mssql --new clickhouse

