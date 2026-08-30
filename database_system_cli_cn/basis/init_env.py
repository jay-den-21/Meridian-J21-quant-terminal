"""Pure-Python reconstruction of ``basis.init_env``."""

from functools import lru_cache

import pandas as pd
import tushare as ts
from sqlalchemy import create_engine

from basis.constant import ts2db_config
from basis.log_man import logging


HQ_LOST_SQL = (
    "create table if not exists hq_lost("
    "lost_Type varchar(200) null, trade_Date date null, "
    "ts_Code varchar(20) null, reason varchar(200) null)"
)
HQ_IS_OK_SQL = (
    "create table if not exists hq_is_ok ("
    "table_name varchar(500) not null, is_ok varchar(1) default 'N' not null, "
    "last_date_count DECIMAL(25, 4) null, "
    "last_t1_date_count DECIMAL(25, 4) null, "
    "last_check_time timestamp NOT NULL )"
)
SS_DATA_STATUS_SQL = (
    "create table if not exists ss_data_status ("
    "table_name varchar(500) NULL,trade_date DATE NULL, "
    "row_count DECIMAL(25,4) default 0 NULL, refresh_date DATE NULL )"
)


def _tushare_token():
    for item in ts2db_config.ts2db_config["server_config"]:
        if item["server"] == "ts":
            return item["token"]
    return None


def init_ts_pro():
    token = _tushare_token()
    ts.set_token(token)
    api = ts.pro_api(timeout=30)
    logging.info(
        "tushare 服务器报告：tushare pro_api 接口初始化成功 "
        "已存入 params.ts_pro ！接口版本: "
        f"{ts.__version__} J21 database 框架版本: 7.0"
    )
    return api


def init_ts():
    token = _tushare_token()
    ts.set_token(token)
    logging.info(
        "tushare 服务器报告：tushare api     接口初始化成功 "
        "已存入 params.ts ！    接口版本: "
        f"{ts.__version__} J21 database 框架版本: 7.0"
    )
    return ts


def init_hq_lost(engine):
    engine.execute(HQ_LOST_SQL)


def init_hq_is_ok(engine):
    engine.execute(HQ_IS_OK_SQL)


def init_ss_data_stats(engine):
    engine.execute(SS_DATA_STATUS_SQL)


@lru_cache(maxsize=None)
def has_schema(engine, schema_name):
    sql = (
        "SELECT count(*) FROM information_schema.schemata "
        f"WHERE schema_name = '{schema_name}'"
    )
    return bool(pd.read_sql_query(sql, engine).iloc[0, 0] > 0)


@lru_cache(maxsize=None)
def has_table(engine, table_name):
    schema_name = engine.url.database
    sql = (
        "SELECT count(*) from INFORMATION_SCHEMA.TABLES "
        f"where TABLE_SCHEMA = '{schema_name}' and TABLE_NAME = '{table_name}'"
    )
    try:
        return bool(pd.read_sql_query(sql, engine).iloc[0, 0] > 0)
    except Exception as ex:
        logging.warning(f"检查数据表 {table_name} 时出错：{ex}")
        return False


def _configured_database_name():
    connect_info = ts2db_config.dbPath
    return connect_info[connect_info.rfind("/") + 1 :]


def init_schema(engine):
    engine.execute(f"create schema if not exists {_configured_database_name()}")


def get_db_schema(engine):
    del engine
    return _configured_database_name()


def have_table(db_engine, table_name):
    db_schema = get_db_schema(db_engine)
    sql = (
        "select count(*) from information_schema.TABLES  "
        f"where TABLE_SCHEMA ='{db_schema}' and TABLE_NAME = '{table_name}'"
    )
    return bool(pd.read_sql_query(sql, db_engine).iloc[0, 0] > 0)


def init_db(echo=True):
    del echo
    connect_info = ts2db_config.dbPath
    engine_init = create_engine(
        connect_info,
        max_overflow=1000,
        pool_size=50,
        pool_timeout=600,
        pool_recycle=1800,
        pool_pre_ping=True,
    )
    init_schema(engine_init)
    init_hq_lost(engine_init)
    init_hq_is_ok(engine_init)
    init_ss_data_stats(engine_init)
    logging.info(f"J21 database：数据库链接初始化成功 {engine_init}")
    return engine_init


def drop_table(db_engine, prefix, name):
    db_engine.execute(f"drop table if exists {prefix}")
    logging.info(f"数据表 {name}({prefix}) 已删除(如有)，开始重新加载数据")


def truncate_Table(db_engine, prefix):
    db_engine.execute(f"truncate table {prefix}")
    logging.info(f"数据表 {prefix} 已清数据，开始重新加载数据")
