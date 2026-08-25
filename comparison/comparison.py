import pandas as pd
import numpy as np

def chart_to_df(chart):
    df = pd.DataFrame()
    for ser in chart['series']:
        min_len = min(len(ser['categories']), len(ser['values']))
        categories = ser['categories'][:min_len]
        values = np.array(ser['values'][:min_len]).astype(float)
        df = pd.concat([df, pd.DataFrame(data=values,
                                         index=categories,
                                         columns=[ser['name']])], axis=1)
    return df


def compare_charts(etalon_chart, auto_chart):
    etalon_chart = chart_to_df(etalon_chart)
    auto_chart = chart_to_df(auto_chart)
    diffs = auto_chart - etalon_chart
    return diffs, (diffs) / etalon_chart


def table_to_df(table):
    columns = table['headers'][1:]
    indexes = [row[0] for row in table['rows']]
    values = [np.array([val.replace(" ", "") if val.strip() != "" else np.nan for val in row[1:]]).astype(float) for row in table['rows']]
    return pd.DataFrame(data=values, index=indexes, columns=columns)


def compare_tables(etalon_table, auto_table):
    etalon_table = table_to_df(etalon_table)
    auto_table = table_to_df(auto_table)
    diffs = auto_table - etalon_table
    return diffs, diffs / etalon_table


def compare_presentations(etalon_presentation, auto_presentation):
    results = {}
    for etalon_slide, auto_slide in zip(etalon_presentation, auto_presentation):
        slide_num = etalon_slide['slide']
        for chart_num, (etalon_chart, auto_chart) in enumerate(zip(etalon_slide['charts'], auto_slide['charts']), 1):
            results.setdefault(f"slide_{slide_num}", {})
            results[f"slide_{slide_num}"][f"chart_{chart_num}"] = compare_charts(etalon_chart, auto_chart)
        for table_num, (etalon_table, auto_table) in enumerate(zip(etalon_slide['tables'], auto_slide['tables']), 1):
            results.setdefault(f"slide_{slide_num}", {})
            results[f"slide_{slide_num}"][f"table_{table_num}"] = compare_tables(etalon_table, auto_table)
            
    return results
    