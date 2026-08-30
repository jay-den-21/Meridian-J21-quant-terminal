

"""
@author: Jayden21 <jayden0721@163.com>
本软件非开源软件，版权所有者为作者，购买者享有个人使用授权，
但不得向第三方拷贝传播该框架相关内容，非许可禁止公开传播，一经发现将严肃追究法律责任！
"""
from basis import *


def init_currentDate():
    currentDate = datetime.datetime.now().strftime('%Y%m%d')
    return currentDate


class PrerequisiteDataError(RuntimeError):
    """Raised when a required code-list table is unavailable or empty."""


class init_data:
    @staticmethod
    def init_codeList(engine, table_name):
        table_contracts = {
            "hq_fund_basic": ("ts_code", "", "公募基金列表"),
            "hq_cb_basic": ("ts_code", "", "可转债基本信息"),
            "hq_us_basic": ("ts_code", "", "美股基本信息"),
            "hq_hk_basic": ("ts_code", "", "港股基本信息"),
            "hq_fut_basic": ("ts_code", "", "期货合约信息表"),
            "hq_opt_basic": ("ts_code", "", "期权合约信息表"),
            "hq_idx_basic": ("ts_code", "", "指数基本信息"),
            "hq_stk_basic": ("ts_code", "", "股票基本信息"),
            "hq_idx_sw_classify": (
                "index_code",
                "where level='L1' and src='SW2021'",
                "申万行业分类",
            ),
            "hq_stk_kpl_concept": ("ts_code", "", "开盘啦题材库"),
            "hq_ths_index": ("ts_code", "", "同花顺概念和行业指数"),
        }
        try:
            column_name, where, description = table_contracts[table_name]
        except KeyError as exc:
            raise PrerequisiteDataError(
                f"unsupported prerequisite table: {table_name}"
            ) from exc
        sql = (
            f"select distinct {column_name} as ts_code from "
            f"{table_name} {where} order by ts_code"
        )
        try:
            code_list = pd.read_sql_query(sql, engine)
        except Exception as exc:
            raise PrerequisiteDataError(
                f"prerequisite table {table_name} ({description}) is "
                "unavailable; load it explicitly before this endpoint"
            ) from exc
        if "ts_code" not in code_list.columns:
            raise PrerequisiteDataError(
                f"prerequisite table {table_name} did not return ts_code"
            )
        if code_list.empty:
            raise PrerequisiteDataError(
                f"prerequisite table {table_name} is empty; load it "
                "explicitly before this endpoint"
            )
        return code_list

    def init_fut_ts_mcodeList(engine):
        sql = """select distinct ts_code from hq_fut_basic where (substr(ts_code ,instr(ts_code ,'.')-1,1) REGEXP '[^0-9.]') = 1 order by ts_code """
        codeList = pd.read_sql_query(sql, engine)
        return codeList

    def init_idx_codeList_lite(engine):
        sql = '''select distinct ts_code from hq_idx_basic WHERE right(ts_code,3) not in ('.MI','SPI','.SI','.CI','.CN',
        '.DF','.GI','.IB','SCH','CZC','DCE','DHF','EXB','FMM','JRF','SHF','SPI','SSI') order by ts_code'''
        codeList = pd.read_sql_query(sql, engine)
        return codeList
