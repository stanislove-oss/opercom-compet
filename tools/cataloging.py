import json


def make_catalog(df) -> list[str]:
    """
    df – DataFrame, в самом обычном виде без группировки
    """
    res_data = {}
    for index, row in df.iterrows():
        res_data[str(row["ad_id_x"])] = {
                                    "company": row["brand_main"],
                                    "direction": row["delivery"],
                                    "segment": row["category"],
                                    "start_date": str(row["date"].date()),
                                    "screenshot_second": str(3)
                                }
    with open("catalog.json", "w", encoding="utf-8") as file:
        json.dump(res_data, file, ensure_ascii=False, indent=4)

    return list(res_data.keys())


def make_plan(df, group=None):
    res_data = {
        "sections": []
    }
    if group is None:
        return None
    for group in df[group].unique():
        data = {}
        data["name"] = group
        data["creative_ids"] = list(map(str, df['ad_id_x'].unique()))
        data["after_slide"] = 0

        res_data["sections"].append(data)

    print(res_data)

    with open("plan1.json", "w", encoding="utf-8") as file:
        json.dump(res_data, file, ensure_ascii=False, indent=4)

    return list(df["ad_id_x"].unique())