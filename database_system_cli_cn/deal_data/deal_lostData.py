"""Pure-Python reconstruction of missing-data discovery and dispatch."""

import pandas as pd

from basis.log_man import logging
from deal_data.get_lostData_by_code import get_LostData_By_Code
from deal_data.get_lostData_by_date import get_LostData_By_Date


def insert_lost_into_hq_lost_by_date(db_engine, prefix, str_date, end_date):
    sql_str = (
        f"insert into hq_lost select '{prefix}' as lost_Type, "
        "jg.cal_date, jg.ts_code, 'lost' as reason from "
        "(select * from (select cal_date from hq_trade_cal "
        "where is_open = '1' and exchange = 'SSE' "
        f"and cal_date between '{str_date}' and '{end_date}') cal "
        f"left join {prefix} tb on cal.cal_date = tb.trade_date ) jg "
        "where jg.trade_date is null"
    )
    try:
        db_engine.execute(sql_str)
    except Exception:
        sql_str = (
            f"insert into hq_lost select '{prefix}' as lost_Type, "
            "jg.cal_date as trade_Date, ' ' as ts_Code, 'lost' as reason from "
            "(select * from (select cal_date from hq_trade_cal "
            "where is_open = '1' and exchange = 'SSE' "
            f"and cal_date between '{str_date}' and '{end_date}') cal "
            f"left join {prefix} tb on cal.cal_date = tb.trade_date ) jg "
            "where jg.trade_date is null"
        )
        db_engine.execute(sql_str)
    sql = (
        "select count(*) from hq_lost "
        f"where reason = 'lost' and lost_Type = '{prefix}'"
    )
    return pd.read_sql_query(sql, db_engine)


def deal_lost_data(params, tableDict_date, tableDict_code):
    db_engine = params.db_engine
    for table_name in tableDict_date:
        insert_lost_into_hq_lost_by_date(
            db_engine, table_name, params.str_date, params.end_date
        )
    code_count = how_many_by_code(db_engine)
    date_count = how_many_by_date(db_engine)
    logging.info(f"缺失数据登记：按代码 {code_count}，按日期 {date_count}")
    get_LostData_By_Code(db_engine, tableDict_code)
    get_LostData_By_Date(db_engine, tableDict_date)


def how_many_by_code(db_engine):
    sql = (
        "select count(distinct lost_Type,ts_Code) from hq_lost "
        "where reason = 'lost' "
    )
    return pd.read_sql_query(sql, db_engine)


def how_many_by_date(db_engine):
    sql = (
        "select count(distinct lost_Type,trade_Date) from hq_lost "
        "where reason = 'lost'  "
    )
    return pd.read_sql_query(sql, db_engine)
