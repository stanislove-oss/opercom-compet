import pandas as pd

def define_cur_year(dfs):
    if isinstance(dfs, list):
        df = pd.concat(dfs)
    else:
        df = dfs.copy() 
    
    cur_year, cur_month = df['date'].max().year, df['date'].max().month
    
    if pd.Timestamp.now().month == cur_month:
        cur_month -= 1


    return cur_year-1, cur_year, cur_month
