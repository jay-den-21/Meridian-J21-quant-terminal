"""Pure-Python reconstruction of date-keyed missing-data repair."""

import datetime
import numbers
import re

import pandas as pd

from basis.log_man import logging


_LOST_TYPE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_TRADE_DATE = re.compile(r"[0-9]{8}")
_RECEIPT_KEYS = frozenset(
    {"schema_version", "scope", "committed_rows", "marker_keys"}
)
_ACKNOWLEDGE_CODE_MARKER_SQL = (
    "delete from hq_lost "
    "where reason = :reason and lost_Type = :lost_type "
    "and trade_Date = :trade_date and ts_Code = :ts_code limit 1"
)
_ACKNOWLEDGE_NULL_MARKER_SQL = (
    "delete from hq_lost "
    "where reason = :reason and lost_Type = :lost_type "
    "and trade_Date = :trade_date "
    "and (ts_Code is null or trim(ts_Code) = '') limit 1"
)


def _validated_marker_keys(receipt, requested_date):
    if (
        type(receipt) is not dict
        or frozenset(receipt) != _RECEIPT_KEYS
        or type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != 1
        or type(receipt["scope"]) is not str
        or receipt["scope"] != "date"
        or type(receipt["committed_rows"]) is not int
        or receipt["committed_rows"] <= 0
        or type(receipt["marker_keys"]) is not list
        or not receipt["marker_keys"]
    ):
        raise ValueError("invalid date repair receipt")

    marker_keys = []
    seen = set()
    for marker_key in receipt["marker_keys"]:
        if type(marker_key) is not list or len(marker_key) != 2:
            raise ValueError("invalid date repair marker key")
        trade_date, ts_code = marker_key
        if (
            type(trade_date) is not str
            or _TRADE_DATE.fullmatch(trade_date) is None
            or trade_date != requested_date
            or (
                ts_code is not None
                and (
                    type(ts_code) is not str
                    or not ts_code
                    or not ts_code.strip()
                )
            )
        ):
            raise ValueError("date repair marker key is outside request scope")
        try:
            datetime.datetime.strptime(trade_date, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("invalid date repair trade date") from exc
        exact_key = (trade_date, ts_code)
        if exact_key in seen:
            raise ValueError("duplicate date repair marker key")
        seen.add(exact_key)
        marker_keys.append(exact_key)

    if len(marker_keys) > receipt["committed_rows"]:
        raise ValueError("date repair receipt overclaims marker keys")
    return marker_keys


def _acknowledge_markers(db_engine, lost_type, marker_keys):
    code_statement = _ACKNOWLEDGE_CODE_MARKER_SQL
    null_statement = _ACKNOWLEDGE_NULL_MARKER_SQL
    if getattr(db_engine, "dialect", None) is not None:
        from sqlalchemy import text

        code_statement = text(code_statement)
        null_statement = text(null_statement)

    def execute(executor):
        acknowledged_count = 0
        for trade_date, ts_code in marker_keys:
            parameters = {
                "reason": "lost",
                "lost_type": lost_type,
                "trade_date": trade_date,
            }
            statement = null_statement
            if ts_code is not None:
                parameters["ts_code"] = ts_code
                statement = code_statement
            result = executor.execute(statement, parameters)
            rowcount = getattr(result, "rowcount", None)
            if not (
                isinstance(rowcount, numbers.Integral)
                and not isinstance(rowcount, bool)
                and rowcount == 1
            ):
                raise RuntimeError(
                    "lost-data marker acknowledgement must affect one row"
                )
            acknowledged_count += 1
        return acknowledged_count

    begin = getattr(db_engine, "begin", None)
    if callable(begin):
        with begin() as connection:
            if connection is None:
                raise RuntimeError(
                    "lost-data acknowledgement transaction returned no connection"
                )
            return execute(connection)
    if len(marker_keys) != 1:
        raise RuntimeError(
            "multiple lost-data markers require an acknowledgement transaction"
        )
    return execute(db_engine)


def init_LostList_by_date(db_engine):
    sql = (
        "select distinct lost_Type,trade_Date from hq_lost "
        "where reason = 'lost' order by lost_Type desc,trade_Date "
    )
    return pd.read_sql_query(sql, db_engine)


def get_LostData_by_date_and_lost_Type(
    db_engine, get_data_run, trade_Date, lost_Type
):
    if (
        not isinstance(lost_Type, str)
        or _LOST_TYPE_IDENTIFIER.fullmatch(lost_Type) is None
    ):
        raise ValueError(f"invalid lost-data table identifier: {lost_Type!r}")

    idate = trade_Date.strftime("%Y%m%d")
    try:
        receipt = get_data_run(idate, idate)
    except Exception as exc:
        logging.error(
            f"缺失数据自动补全（按日期）：{lost_Type} trade_date 日期为 {idate}，"
            f"回调异常 {type(exc).__name__}，保留 hq_lost 登记"
        )
        return

    try:
        marker_keys = _validated_marker_keys(receipt, idate)
    except ValueError:
        logging.error(
            f"缺失数据自动补全（按日期）：{lost_Type} trade_date 日期为 {idate}，"
            f"回调未提供严格匹配的提交收据（返回 {type(receipt).__name__}），"
            "保留 hq_lost 登记"
        )
        return

    try:
        acknowledged_count = _acknowledge_markers(
            db_engine, lost_Type, marker_keys
        )
    except Exception as exc:
        logging.error(
            f"缺失数据自动补全（按日期）：{lost_Type} trade_date 日期为 {idate}，"
            f"删除 hq_lost 登记失败 {type(exc).__name__}"
        )
        raise

    logging.info(
        f"缺失数据自动补全（按日期）：{lost_Type} trade_date 日期为 {idate}，"
        f"已删除 hq_lost 中 {acknowledged_count} 条登记"
    )


def get_LostData_By_Date(db_engine, tableDict_date):
    lostListArray = init_LostList_by_date(db_engine).__array__()
    for lost_Type, trade_Date in lostListArray:
        if (
            not isinstance(lost_Type, str)
            or _LOST_TYPE_IDENTIFIER.fullmatch(lost_Type) is None
        ):
            logging.error(
                f"缺失数据自动补全（按日期）：无效的数据表标识 {lost_Type!r}，"
                "保留 hq_lost 登记"
            )
            continue
        if lost_Type in tableDict_date.keys():
            get_LostData_by_date_and_lost_Type(
                db_engine, tableDict_date[lost_Type], trade_Date, lost_Type
            )
        else:
            logging.info(
                f"缺失数据自动补全（按日期）：找不到 {lost_Type} 接口处理模块"
            )
