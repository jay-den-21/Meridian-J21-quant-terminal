"""Pure-Python duplicate-data repair without machine-bound authorization."""

import re

import pandas as pd

from basis.constant import ts2db_config
from basis.errors import legacy_authorization_removed
from basis.init_env import have_table
from basis.log_man import logging


_SQL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SQL_SCOPE_VALUE = re.compile(r"[A-Za-z0-9._:@+\-]+")


def _quote_identifier(value):
    value = value.strip()
    if _SQL_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"invalid SQL identifier: {value!r}")
    return f"`{value}`"


def _quote_scope_value(value):
    text = str(value).strip()
    if not text or _SQL_SCOPE_VALUE.fullmatch(text) is None:
        raise ValueError(f"invalid duplicate scope value: {text!r}")
    return f"'{text}'"


def _scope_filters(params):
    filters = getattr(params, "deal_duplicate_scope_filters", None)
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("deal_duplicate_scope_filters must be a dictionary")
    normalized = {}
    for key, value in filters.items():
        if not isinstance(key, str):
            raise ValueError("duplicate scope filter names must be strings")
        name = key.strip()
        _quote_identifier(name)
        normalized[name] = _quote_scope_value(value)
    return normalized


def _scope_where(alias, date_scope, filters):
    prefix = f"{alias}." if alias else ""
    clauses = []
    if date_scope:
        start_date = _quote_scope_value(date_scope[0])
        end_date = _quote_scope_value(date_scope[1])
        clauses.append(
            f"{prefix}`trade_date` between {start_date} and {end_date}"
        )
    clauses.extend(
        f"{prefix}{_quote_identifier(key)} = {value}"
        for key, value in filters.items()
    )
    if not clauses:
        return ""
    return " where " + " and ".join(clauses)


def _duplicate_stats_query(prefix, pkey, date_scope, filters):
    table = _quote_identifier(prefix)
    keys = ", ".join(_quote_identifier(item) for item in pkey.split(","))
    scope = _scope_where("", date_scope, filters)
    return (
        "select count(*) as duplicate_groups, "
        "coalesce(sum(ct), 0) as duplicate_rows from ("
        f"select count(*) as ct from {table}{scope} "
        f"group by {keys} having count(*) > 1) duplicate_sets"
    )


def _duplicate_id_query(prefix, pkey, date_scope, filters, limit):
    table = _quote_identifier(prefix)
    keys = [_quote_identifier(item) for item in pkey.split(",")]
    equality = " and ".join(
        f"old.{key} <=> newer.{key}" for key in keys
    )
    old_scope = _scope_where("old", date_scope, filters)
    newer_scope = _scope_where("newer", date_scope, filters)
    scope_parts = []
    if old_scope:
        scope_parts.append(old_scope.removeprefix(" where "))
    if newer_scope:
        scope_parts.append(newer_scope.removeprefix(" where "))
    scope = " where " + " and ".join(scope_parts) if scope_parts else ""
    return (
        f"select old.`id` from {table} old join {table} newer on "
        f"{equality} and old.`id` < newer.`id`{scope} "
        "group by old.`id` order by old.`id` "
        f"limit {int(limit)}"
    )


def _delete_duplicate_batches(
    db_engine,
    prefix,
    pkey,
    date_scope,
    scope_filters,
    expected_rows,
    batch_size,
    strict,
):
    total_deleted = 0
    id_query = _duplicate_id_query(
        prefix,
        pkey,
        date_scope,
        scope_filters,
        batch_size,
    )
    while total_deleted < expected_rows:
        try:
            id_frame = pd.read_sql_query(id_query, db_engine)
            ids = [int(value) for value in id_frame.get("id", [])]
            if not ids:
                break
            id_list = ", ".join(str(value) for value in ids)
            table = _quote_identifier(prefix)
            result = db_engine.execute(
                f"delete from {table} where id in ({id_list})"
            )
            deleted_rows = int(result.rowcount)
        except Exception as ex:
            logging.error(f"{prefix} 自动去重时出错，请检查！{ex}")
            if strict:
                raise RuntimeError(
                    f"{prefix} date-scoped duplicate deletion failed"
                ) from ex
            break
        total_deleted += deleted_rows
        logging.info(
            f"J21 database[去重]：{prefix} 已删除 "
            f"{total_deleted}/{expected_rows} 行重复数据"
        )
        if deleted_rows == 0:
            break
    if total_deleted != expected_rows:
        message = (
            f"{prefix} 重复数据删除数量不一致："
            f"实际 {total_deleted}，预期 {expected_rows}"
        )
        logging.warning(message)
        if strict:
            raise RuntimeError(message)
    return total_deleted


def deal_duplicate_in_hq_lost(params, prefix, pkey):
    """Remove duplicates while retaining the row with the greatest ``id``."""
    str_date = params.str_date
    end_date = params.end_date
    db_engine = params.db_engine
    strict_date_scope = bool(
        getattr(params, "deal_duplicate_strict_date_scope", False)
    )
    scope_filters = _scope_filters(params)
    logging.info(
        f"-----------------------------J21 database[去重]：重复数据自动整理 "
        f"{prefix}-----------------------------"
    )
    logging.info(
        f"J21 database[去重]：自动去重模块报告：{prefix} 开始查找重复数据"
    )
    if not have_table(db_engine, prefix):
        logging.warning(f"{prefix} 表不存在，无法启动自动去重")
        return None

    date_scope = (str_date, end_date)
    stats_sql = _duplicate_stats_query(
        prefix,
        pkey,
        date_scope,
        scope_filters,
    )
    try:
        stats = pd.read_sql_query(stats_sql, db_engine)
        d_row_count = int(stats.iloc[0, 0] or 0)
        d_row_sum = int(stats.iloc[0, 1] or 0)
    except Exception as exc:
        if strict_date_scope:
            raise RuntimeError(
                f"{prefix} date-scoped duplicate inspection failed"
            ) from exc
        date_scope = None
        stats_sql = _duplicate_stats_query(
            prefix,
            pkey,
            date_scope,
            scope_filters,
        )
        stats = pd.read_sql_query(stats_sql, db_engine)
        d_row_count = int(stats.iloc[0, 0] or 0)
        d_row_sum = int(stats.iloc[0, 1] or 0)
    d_row = d_row_sum - d_row_count
    if d_row <= 0:
        scope_text = (
            f"日期 {str_date} 到 {end_date} 内"
            if date_scope
            else "全表"
        )
        logging.info(
            f"J21 database[去重]：自动去重模块报告：{prefix} "
            f"{scope_text}无重复数据!"
        )
        return 0

    logging.warning(
        f"J21 database[去重]：自动去重模块报告：{prefix} "
        f"找到重复数据 {d_row_count} 行，共 {d_row_sum} 条，"
        f"需要删除 {d_row} 行"
    )

    try:
        db_engine.execute(f"alter table {prefix} add id int auto_increment primary key")
    except Exception:
        pass
    try:
        db_engine.execute(f"create index {prefix}_id_index on {prefix} (id)")
    except Exception:
        pass

    del_rows_one_time = ts2db_config.ts2db_config["run_config"].get(
        "del_duplicate_rows_one_time", 100
    )
    total_deleted = _delete_duplicate_batches(
        db_engine,
        prefix,
        pkey,
        date_scope,
        scope_filters,
        d_row,
        del_rows_one_time,
        strict_date_scope,
    )
    logging.success(
        f"J21 database[去重]：自动去重模块报告：{prefix} "
        f"删除 {total_deleted} 行重复数据（预期 {d_row} 行）"
    )
    return None


def del_d_rows(db_engine, prefix, sql_del, d_row):
    total_deleted = 0
    while True:
        try:
            result = db_engine.execute(sql_del)
            deleted_rows = int(result.rowcount)
        except Exception as ex:
            logging.error(f"{prefix} 自动去重时出错，请检查！{ex}")
            break
        total_deleted += deleted_rows
        if deleted_rows == 0 or total_deleted >= d_row:
            break
    logging.info(f"{prefix} 的重复数据清理，共删除重复数据 {total_deleted} 行")
    return total_deleted


def get_webservertime():
    legacy_authorization_removed("deal_data.deal_duplicatetData.get_webservertime")


class apier:
    def __init__(self):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier")

    def get_serial_number(self):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier.get_serial_number")

    def get_mac_address(self):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier.get_mac_address")

    def get_mac_address_like_cpu_id(self):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier.get_mac_address_like_cpu_id")

    def get_cpu_sn(self):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier.get_cpu_sn")

    def bes_Encrypt(self, O000O00OOOO0OOO0O):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier.bes_Encrypt")

    def bes_Decrypt(self, OO0O0OO0O000OO000):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier.bes_Decrypt")

    def get_time_code(self, O00OOOOOO000O000O):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier.get_time_code")

    def get_time_code_by_machine_and_exp_date(
        self, O0O0OO0OO00O00OOO, OOOO0O000O00OO00O
    ):
        legacy_authorization_removed(
            "deal_data.deal_duplicatetData.apier.get_time_code_by_machine_and_exp_date"
        )

    def check_date(self):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier.check_date")

    def api(self):
        legacy_authorization_removed("deal_data.deal_duplicatetData.apier.api")


def check_api():
    legacy_authorization_removed("deal_data.deal_duplicatetData.check_api")


def deal_duplicate_data(OO0OOO0OO00O0OOO0, OO00OOOOO00OOOO00):
    params = OO0OOO0OO00O0OOO0
    table_dictionary = OO00OOOOO00OOOO00
    for prefix, pkey in table_dictionary:
        deal_duplicate_in_hq_lost(params, prefix, pkey)
