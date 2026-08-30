"""Clean-room Python implementation of the public ``basis.tools`` framework."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
import calendar
import copy
import datetime
from functools import lru_cache
import hashlib
import inspect
import multiprocessing
import numbers
import time
from typing import Iterable

import pandas as pd

from basis.errors import legacy_authorization_removed
from basis.init_env import drop_table, init_db, init_ts, init_ts_pro
from basis.log_man import logging
from basis.params import _params


_MYSQL_IDENTIFIER_MAX_BYTES = 64
_INDEX_NAME_DIGEST_HEX_LENGTH = 32
_RUN_SEPARATOR = "=" * 108


def _bounded_mysql_index_name(name):
    encoded = name.encode("utf-8")
    if len(encoded) <= _MYSQL_IDENTIFIER_MAX_BYTES:
        return name
    digest = hashlib.sha256(encoded).hexdigest()[:_INDEX_NAME_DIGEST_HEX_LENGTH]
    suffix = f"_{digest}"
    prefix_budget = _MYSQL_IDENTIFIER_MAX_BYTES - len(suffix)
    prefix = encoded[:prefix_budget].decode("utf-8", errors="ignore")
    return f"{prefix}{suffix}"


def run_get_data_class(cls=None, params=None):
    if cls is None:
        return None
    try:
        cls(params).run()
    except Exception as ex:
        logging.error(f"报错接口：{getattr(cls, '__name__', cls)} 错误信息：{ex}")
        return None


def get_next_day_str(idate):
    stridate = datetime.datetime.strptime(idate, "%Y%m%d")
    return (stridate + datetime.timedelta(days=1)).strftime("%Y%m%d")


@lru_cache(maxsize=None)
def get_next_work_date_str(db_engine, idate, next_n, market="CN"):
    stridate = datetime.datetime.strptime(idate, "%Y%m%d")
    direction = 1 if next_n >= 0 else -1
    remaining = abs(next_n)
    while remaining:
        stridate += datetime.timedelta(days=direction)
        if is_working_date(db_engine, stridate.strftime("%Y%m%d"), market):
            remaining -= 1
    return stridate.strftime("%Y%m%d")


def get_last_work_date(db_engine, idate, market="CN"):
    return get_next_work_date_str(db_engine, idate, -1, market)


@lru_cache(maxsize=None)
def is_working_date(db_engine, idate, market="CN"):
    if market == "HK":
        sql = f"select is_open from hq_hk_trade_cal where cal_date = '{idate}'"
    elif market == "US":
        sql = f"select is_open from hq_us_trade_cal where cal_date = '{idate}'"
    elif market == "CN":
        sql = (
            "select is_open from hq_trade_cal where exchange = 'SSE' "
            f"and cal_date = '{idate}'"
        )
    else:
        return True
    try:
        df = pd.read_sql_query(sql, db_engine)
        if df.empty:
            return True
        return df.iloc[0, 0] == "1"
    except Exception as ex:
        logging.warning(f"检查交易日 {idate} 时出错：{ex}")
        return False


def get_ts_api_time():
    legacy_authorization_removed("basis.tools.get_ts_api_time")


def is_debugging():
    legacy_authorization_removed("basis.tools.is_debugging")


def is_virtual_machine():
    legacy_authorization_removed("basis.tools.is_virtual_machine")


def get_ts_api():
    """Return an official Tushare client configured with the user's own token."""
    return init_ts_pro()


def get_begin_end_date_of_next_month(today=datetime.date.today()):
    if today.month == 12:
        first = datetime.date(today.year + 1, 1, 1)
    else:
        first = datetime.date(today.year, today.month + 1, 1)
    last = datetime.date(
        first.year,
        first.month,
        calendar.monthrange(first.year, first.month)[1],
    )
    return first.strftime("%Y%m%d"), last.strftime("%Y%m%d")


def get_begin_end_date_of_month(today=datetime.date.today()):
    first = datetime.date(today.year, today.month, 1)
    last = datetime.date(
        today.year,
        today.month,
        calendar.monthrange(today.year, today.month)[1],
    )
    return first.strftime("%Y%m%d"), last.strftime("%Y%m%d")


class ts2db_father_template(metaclass=ABCMeta):
    table_name = None
    table_name_cn = ""

    def __init__(self, params=None):
        self.df = None
        self.df_get_count_all = 0
        self.df_clean_count_all = 0
        self.df_write_count_all = 0
        self.df_cache = None
        self.df_cache_count_all = 0
        self.ts_api_call_count_all = 0
        self._pagination_page_number = 0
        self._last_df_get_count = 0
        self._last_df_clean_count = 0
        self.params = _params() if params is None else copy.copy(params)
        self.params.db_engine = init_db()
        if getattr(self.params, "server", None) != "xc":
            self.params.ts_pro = init_ts_pro()
            self.params.ts = init_ts()
        self.params.table_name = getattr(self, "table_name", None)
        self.params.table_name_cn = getattr(self, "table_name_cn", "")
        self.ts2db_init_before()
        self.ts2db_init()
        self.ts2db_init_after()
        self._configured_one_time_rows_limit = max(
            int(self.params.one_time_rows_limit or 1),
            1,
        )
        codelist = getattr(self.params, "codelist", None)
        if codelist is not None:
            self.params.codelist = codelist.sort_values(
                by="ts_code"
            ).reset_index(drop=True)

    def ts2db_init_before(self):
        return None

    def ts2db_init(self):
        return None

    def ts2db_init_after(self):
        return None

    def ts2db_get_data(self):
        return None

    def ts2db_get_data_agent(self):
        self._last_df_get_count = 0
        try:
            max_attempts = max(int(getattr(self.params, "retry_times", 2)), 1)
        except (TypeError, ValueError):
            max_attempts = 2
        retry_sleep = max(
            float(getattr(self.params, "retry_sleep_time", 0) or 0),
            0,
        )
        for attempt in range(1, max_attempts + 1):
            self.df = None
            try:
                self.df = self.ts2db_get_data()
                df_get_count = 0 if self.df is None else len(self.df)
                self.df_get_count_all += df_get_count
                self._last_df_get_count = df_get_count
                return df_get_count
            except Exception as ex:
                if attempt >= max_attempts:
                    logging.error(
                        f"J21 database：{self.params.table_name} 连续失败 "
                        f"{max_attempts} 次，停止当前接口并退出！ {ex}"
                    )
                    raise
                logging.warning(
                    f"J21 database[自动重试]：{self.params.table_name} "
                    f"服务器返回错误（第 {attempt}/{max_attempts} 次），"
                    f"框架将等待 {retry_sleep:g} 秒后重试；"
                    f"达到上限会停止当前接口。{ex}"
                )
                if retry_sleep:
                    time.sleep(retry_sleep)

    def ts2db_clean_data(self):
        return None

    def ts2db_clean_data_agent(self):
        try:
            self.ts2db_clean_data()
            df_clean_count = 0 if self.df is None else len(self.df)
            self.df_clean_count_all += df_clean_count
            self._last_df_clean_count = df_clean_count
            return df_clean_count
        except Exception as ex:
            logging.error(f"{getattr(self.params, 'msg_title', '')} 数据清理时报错：{ex}")
            raise

    def ts2db_write_db(self):
        return None

    def ts2db_write_db_agent(self):
        if self.df is None or len(self.df) == 0:
            df_write_count = 0
        else:
            try:
                df_write_count = self.ts2db_write_db()
                if df_write_count is None:
                    df_write_count = 0
                df_write_count = int(df_write_count)
                self.df_write_count_all += df_write_count
            except Exception as ex:
                logging.error(
                    f"{getattr(self.params, 'msg_title', '')} "
                    f"写入数据库时报错：{ex}"
                )
                raise
        self._log_call_result(
            getattr(self, "_last_df_get_count", 0),
            getattr(self, "_last_df_clean_count", 0),
            df_write_count,
        )
        return df_write_count

    def ts2db_check_data_is_ok(self):
        return None

    def ts2db_should_we_end(self, df_get_count):
        df_get_count = max(int(df_get_count or 0), 0)
        limit = max(int(self.params.one_time_rows_limit or 1), 1)
        self._pagination_page_number = (
            getattr(self, "_pagination_page_number", 0) + 1
        )
        if df_get_count == 0:
            return True
        if self._pagination_page_number == 1 and df_get_count < limit:
            self.params.one_time_rows_limit = df_get_count
            logging.info(
                "J21 database[接口检测]：检测到该接口限制为 "
                f"{df_get_count} 每次，框架启动自适应！"
            )
            return False
        if df_get_count > limit:
            self.params.one_time_rows_limit = df_get_count
            logging.info(
                "J21 database[接口检测]：接口返回量超过当前设置，限制可能为 "
                f"{df_get_count} 每次，框架启动自适应！"
            )
            return False
        return df_get_count < limit

    @abstractmethod
    def _run(self):
        raise NotImplementedError

    def run(self):
        engine = getattr(self.params, "db_engine", None)
        table_name = getattr(self.params, "table_name", self.table_name)
        table_name_cn = getattr(
            self.params,
            "table_name_cn",
            self.table_name_cn,
        )
        logging.info(_RUN_SEPARATOR)
        logging.success(
            f"数据表 {table_name} ({table_name_cn}) 开始同步数据"
        )
        logging.info(_RUN_SEPARATOR)
        try:
            detect_type = getattr(self.params, "auto_detect__break_point_type", 0)
            if detect_type == 1:
                logging.success(
                    f"{getattr(self.params, 'msg_title', '')} "
                    "自动增量抓取模式已开启，框架将自动识别数据下载情况，"
                    "仅拉取增量数据！"
                )
                self.ts2db_auto_detect__check_downloaded_db_data()
                result = self.ts2db_auto_detect__get_datas_need_to_get()
            elif detect_type == 2:
                sqlstr_today_already_got_data = (
                    "select count(*) from ss_data_status where table_name = "
                    f"'{self.params.table_name}' and trade_date = current_date"
                )
                has_got_data = pd.read_sql_query(
                    sqlstr_today_already_got_data, self.params.db_engine
                ).iloc[0, 0]
                if has_got_data:
                    self.params.data_already_ok = True
                    return None
                result = self._run()
            elif getattr(self.params, "data_already_ok", False):
                result = None
            else:
                result = self._run()
            self._log_run_summary()
            self.ts2db_set_db_index()
            self.ts2db_clean_up_data()
            self.ts2db_after_run()
            if detect_type == 2:
                str_insert_data_status = (
                    "INSERT INTO ss_data_status "
                    "(table_name, trade_date, row_count, refresh_date) VALUES ("
                    f"'{self.params.table_name}', current_date, "
                    f"{self.df_write_count_all}, current_time)"
                )
                self.params.db_engine.execute(str_insert_data_status)
            return result
        except Exception as ex:
            logging.error(
                f"数据表 {table_name} ({table_name_cn}) "
                f"同步失败，进程将返回错误：{ex}"
            )
            raise
        finally:
            if engine is not None and callable(getattr(engine, "dispose", None)):
                engine.dispose()
            self.params.db_engine = None
            self.params.ts = None
            self.params.ts_pro = None
            self.params.ts_api = None

    def _log_run_summary(self):
        msg_title = getattr(self.params, "msg_title", "")
        fetched = int(getattr(self, "df_get_count_all", 0) or 0)
        cleaned = int(getattr(self, "df_clean_count_all", 0) or 0)
        written = int(getattr(self, "df_write_count_all", 0) or 0)
        if fetched:
            logging.info(
                f"{msg_title} 本次总共抓取数据 {fetched} 条，"
                f"清洗后 {cleaned} 最终入库 {written}！"
            )
            return
        logging.warning(
            f"{msg_title} 总抓取数据 0 条，可能是不在工作日或当前时间段"
            "没有数据，也可能当前账户对该接口没有权限！"
        )

    def run_no_wait(self, target):
        process = multiprocessing.Process(target=target)
        process.start()
        return None

    def ts2db_times_sleep(self, itimes):
        times_limit = self.params.times_limit_in_1min
        if times_limit and itimes % times_limit == 0:
            seconds = self.params.sleep_time
            for _ in range(seconds):
                time.sleep(1)

    def ts2db_rt__gap_sleep(self):
        seconds = getattr(self.params, "time_gap", 0)
        for _ in range(max(int(seconds * 100), 0)):
            time.sleep(0.01)

    def ts2db_rt__get_add_data(self):
        if self.df is None:
            return 0
        if not getattr(self.params, "rt_deal_duplicate_data", False):
            return len(self.df)
        if self.df_cache is None:
            self.df_cache = self.df.copy()
            return len(self.df)
        if len(self.df) == 0:
            return 0
        columns = list(self.df.columns)
        known = self.df_cache.drop_duplicates()
        merged = self.df.merge(known, how="left", on=columns, indicator=True)
        df_add = merged.loc[merged["_merge"] == "left_only", columns]
        self.df = df_add
        if len(df_add):
            self.df_cache = pd.concat([df_add, self.df_cache], ignore_index=True)
        return len(df_add)

    def ts2db_set_db_index(self):
        index_keys = getattr(self.params, "db_indexes", None) or []
        if not index_keys:
            return None
        index_tools = db_utils()
        if not index_tools.has_table(self, self.params.table_name):
            logging.warning(
                f"数据表 {self.params.table_name} 不存在，无法建立索引"
            )
            return None
        for index_key in index_keys:
            index_tools.create_index_if_not_exists(self, index_key)
        return None

    def ts2db_clean_up_data(self):
        keys = getattr(self.params, "deal_data__duplicate_data_key", None)
        self.ts2db_deal_duplicate_datas(keys)

    def ts2db_deal_duplicate_datas(self, keys):
        if keys is None:
            return None
        from deal_data.deal_duplicatetData import deal_duplicate_data

        deal_duplicate_data(self.params, [[self.params.table_name, keys]])
        return None

    def _ts2db_repair_scope(self, *, code=None, str_date=None, end_date=None):
        is_code_scope = code is not None
        is_date_scope = str_date is not None or end_date is not None
        if is_code_scope == is_date_scope:
            raise ValueError("repair scope must be exactly one code or date range")
        if is_code_scope and (not isinstance(code, str) or not code):
            raise ValueError("repair code must be a non-empty string")
        if is_date_scope and (
            not isinstance(str_date, str)
            or not str_date
            or not isinstance(end_date, str)
            or not end_date
        ):
            raise ValueError("repair dates must be non-empty strings")

        params = self.params
        engine = getattr(params, "db_engine", None)
        if engine is None or not callable(getattr(engine, "begin", None)):
            raise RuntimeError(
                "lost-data repair requires a transactional database engine"
            )

        state_names = (
            "str_date",
            "end_date",
            "idate",
            "code",
            "offset",
            "one_time_rows_limit",
        )
        absent = object()
        saved_state = {
            name: getattr(params, name, absent) for name in state_names
        }
        saved_counters = {
            "df_get_count_all": self.df_get_count_all,
            "df_clean_count_all": self.df_clean_count_all,
            "df_write_count_all": self.df_write_count_all,
        }
        saved_runtime_state = {}
        for name in ("df", "df_cache", "df_cache_count_all"):
            value = getattr(self, name, absent)
            saved_runtime_state[name] = (
                value if value is absent else copy.deepcopy(value)
            )
        try:
            params.offset = 0
            if is_code_scope:
                params.code = code
            else:
                params.str_date = str_date
                params.end_date = end_date
                params.idate = str_date
                # A date-scoped receipt acknowledges the aggregate date
                # marker.  Never let a stale code selector narrow the fetch
                # while still emitting that aggregate acknowledgement.
                params.code = ""

            committed_rows = 0
            marker_keys = set()
            try:
                transaction = engine.begin()
                with transaction as connection:
                    if connection is None:
                        raise RuntimeError(
                            "repair transaction returned no connection"
                        )
                    params.db_engine = connection
                    while True:
                        df_get_count = self.ts2db_get_data_agent()
                        self.ts2db_clean_data_agent()
                        df_write_count = 0
                        page_marker_keys = set()
                        if self.df is not None and len(self.df) > 0:
                            if "trade_date" not in self.df.columns:
                                raise RuntimeError(
                                    "repair cleaned page is missing trade_date"
                                )
                            if (
                                is_code_scope
                                and "ts_code" not in self.df.columns
                            ):
                                raise RuntimeError(
                                    "code repair cleaned page is missing ts_code"
                                )
                            trade_values = self.df["trade_date"].tolist()
                            code_values = (
                                self.df["ts_code"].tolist()
                                if "ts_code" in self.df.columns
                                else [None] * len(self.df)
                            )
                            for trade_value, code_value in zip(
                                trade_values, code_values
                            ):
                                if trade_value is None or pd.isna(trade_value):
                                    trade_marker = None
                                elif isinstance(
                                    trade_value,
                                    (datetime.date, datetime.datetime),
                                ):
                                    trade_marker = trade_value.strftime("%Y%m%d")
                                else:
                                    trade_marker = str(trade_value)
                                    if (
                                        len(trade_marker) == 10
                                        and trade_marker[4] in "-/"
                                        and trade_marker[7] in "-/"
                                    ):
                                        trade_marker = (
                                            trade_marker[:4]
                                            + trade_marker[5:7]
                                            + trade_marker[8:]
                                        )
                                try:
                                    parsed_trade_date = (
                                        datetime.datetime.strptime(
                                            trade_marker, "%Y%m%d"
                                        )
                                    )
                                except (TypeError, ValueError) as exc:
                                    raise RuntimeError(
                                        "repair cleaned page contains an "
                                        "invalid trade_date"
                                    ) from exc
                                trade_marker = parsed_trade_date.strftime(
                                    "%Y%m%d"
                                )
                                if code_value is None or pd.isna(code_value):
                                    code_marker = None
                                else:
                                    code_marker = str(code_value)
                                if is_code_scope:
                                    if code_marker != code:
                                        raise RuntimeError(
                                            "code repair cleaned page contains "
                                            "an out-of-scope ts_code"
                                        )
                                    page_marker_keys.add(
                                        (trade_marker, code_marker)
                                    )
                                elif not (
                                    str_date <= trade_marker <= end_date
                                ):
                                    raise RuntimeError(
                                        "date repair cleaned page contains "
                                        "an out-of-scope trade_date"
                                    )
                                else:
                                    page_marker_keys.add((trade_marker, None))

                            try:
                                raw_write_count = self.ts2db_write_db()
                            except Exception as ex:
                                logging.error(
                                    f"{getattr(self.params, 'msg_title', '')} "
                                    f"写入数据库时报错：{ex}"
                                )
                                raise
                            if not (
                                isinstance(raw_write_count, numbers.Integral)
                                and not isinstance(raw_write_count, bool)
                                and raw_write_count == len(self.df)
                            ):
                                raise RuntimeError(
                                    "repair write count must exactly match "
                                    "the cleaned page row count"
                                )
                            df_write_count = int(raw_write_count)
                            self.df_write_count_all += df_write_count
                            marker_keys.update(page_marker_keys)
                        committed_rows += df_write_count
                        if self.ts2db_should_we_end(df_get_count):
                            break
                        params.offset += params.one_time_rows_limit

                    if committed_rows <= 0 or not marker_keys:
                        raise RuntimeError(
                            "repair scope produced no exact committed marker keys"
                        )
                    receipt = {
                        "schema_version": 1,
                        "scope": "code" if is_code_scope else "date",
                        "committed_rows": committed_rows,
                        "marker_keys": [
                            list(marker_key)
                            for marker_key in sorted(
                                marker_keys,
                                key=lambda value: (
                                    value[0] or "",
                                    value[1] or "",
                                ),
                            )
                        ],
                    }
            except Exception:
                for name, value in saved_counters.items():
                    setattr(self, name, value)
                raise
            return receipt
        finally:
            params.db_engine = engine
            for name, value in saved_state.items():
                if value is absent:
                    try:
                        delattr(params, name)
                    except AttributeError:
                        pass
                else:
                    setattr(params, name, value)
            for name, value in saved_runtime_state.items():
                if value is absent:
                    try:
                        delattr(self, name)
                    except AttributeError:
                        pass
                else:
                    setattr(self, name, value)

    def _ts2db_repair_by_code(self, ts_code):
        return self._ts2db_repair_scope(code=ts_code)

    def _ts2db_repair_by_date(self, str_date, end_date):
        return self._ts2db_repair_scope(
            str_date=str_date,
            end_date=end_date,
        )

    def ts2db_deal_lost_datas(self, keys):
        from deal_data.deal_lostData import deal_lost_data

        if keys is None:
            return None
        if isinstance(keys, str):
            raw_keys = keys.split(",")
        else:
            try:
                raw_keys = list(keys)
            except TypeError as exc:
                raise ValueError(
                    "lost-data repair keys must be a string or iterable"
                ) from exc
        if not raw_keys:
            return None
        if any(not isinstance(key, str) for key in raw_keys):
            raise ValueError("lost-data repair keys must be strings")
        normalized_keys = {
            key.strip().casefold() for key in raw_keys if key.strip()
        }
        unsupported_keys = normalized_keys - {"trade_date", "ts_code"}
        if not normalized_keys:
            return None
        if unsupported_keys:
            raise ValueError(
                "unsupported lost-data repair keys: "
                + ", ".join(sorted(unsupported_keys))
            )

        date_handlers = (
            {self.params.table_name: self._ts2db_repair_by_date}
            if "trade_date" in normalized_keys
            else {}
        )
        code_handlers = (
            {self.params.table_name: self._ts2db_repair_by_code}
            if "ts_code" in normalized_keys
            else {}
        )
        try:
            signature = inspect.signature(deal_lost_data)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "cannot verify the missing-data dispatcher signature"
            ) from exc
        parameters = tuple(signature.parameters.values())
        positional_count = sum(
            parameter.kind
            in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
            for parameter in parameters
        )
        has_varargs = any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL
            for parameter in parameters
        )
        if has_varargs or positional_count >= 5:
            # Preserve the supplied native tools module's observable five-arg
            # adapter when the dispatcher explicitly supports that shape.
            deal_lost_data(
                self.params.db_engine,
                code_handlers,
                date_handlers,
                self.params.str_date,
                self.params.end_date,
            )
        elif positional_count == 3:
            deal_lost_data(self.params, date_handlers, code_handlers)
        else:
            raise RuntimeError(
                "unsupported missing-data dispatcher signature"
            )
        return None

    def ts2db_deal_exception(self, ex):
        logging.error(
            f"J21 database：{self.params.table_name} 重试失败，将跳过该操作，"
            f"继续抓取后续数据！ {ex}"
        )

    def ts2db_auto_detect__tag_bad_data(self, data_status):
        if data_status is None or len(data_status) < 2:
            return data_status
        frame = data_status.copy()
        threshold = self.params.auto_detect__break_point_chg_pct
        count_column = "count" if "count" in frame.columns else frame.columns[1]
        bad_indexes = []
        pre_count = frame.iloc[0][count_column]
        for position in range(1, len(frame)):
            cur_count = frame.iloc[position][count_column]
            if pre_count:
                chg_pct = abs(cur_count - pre_count) / pre_count
            else:
                chg_pct = 1 if cur_count else 0
            if chg_pct > threshold:
                bad_indexes.append(frame.index[position])
                message_row = frame.iloc[min(position + 1, len(frame) - 1)]
                logging.warning(
                    f"数据表 {self.params.table_name} "
                    f"({self.params.table_name_cn}) 在日期 "
                    f"{message_row.iloc[0]} 上只有 "
                    f"{message_row[count_column]} 条数据，疑似抓残，将重新抓取。"
                )
            pre_count = cur_count
        return frame.drop(index=bad_indexes)

    def ts2db_auto_detect__check_downloaded_db_data(self):
        bp_key = getattr(self.params, "auto_detect__break_point_key", "trade_date")
        try:
            table_tools = db_tools(self.params)
            if not table_tools.has_table(self.params.table_name) or not table_tools.has_column(
                self.params.table_name, bp_key
            ):
                raise LookupError("table or breakpoint column is unavailable")
            sqlstr_count = (
                f"select {bp_key}, count(*) as count from {self.params.table_name} "
                f"where {bp_key} between '{self.params.str_date}' and "
                f"'{self.params.end_date}' group by {bp_key} order by {bp_key} asc"
            )
            data_status = pd.read_sql_query(sqlstr_count, self.params.db_engine)
            data_status = self.ts2db_auto_detect__tag_bad_data(data_status)
            downloaded = {
                value.strftime("%Y%m%d")
                if hasattr(value, "strftime")
                else str(value).replace("-", "")
                for value in data_status[bp_key]
            }
            first_missing = None
            idate = self.params.str_date
            while idate <= self.params.end_date:
                if (
                    is_working_date(self.params.db_engine, idate, self.params.market)
                    and idate not in downloaded
                ):
                    first_missing = idate
                    break
                idate = get_next_day_str(idate)
            if first_missing is None:
                data_need = pd.DataFrame(columns=["str_date", "end_date"])
            else:
                data_need = pd.DataFrame(
                    [{"str_date": first_missing, "end_date": self.params.end_date}]
                )
        except Exception as ex:
            logging.warning(
                f"数据表 {self.params.table_name} ({self.params.table_name_cn}) "
                f"在断点续作时报错，框架将继续处理。{ex}"
            )
            data_need = pd.DataFrame(
                [{"str_date": self.params.str_date, "end_date": self.params.end_date}]
            )
        self.params.auto_detect__datas_need_to_get = data_need
        return data_need

    def ts2db_auto_detect__get_datas_need_to_get(self):
        str_date = self.params.str_date
        end_date = self.params.end_date
        try:
            data_need = getattr(self.params, "auto_detect__datas_need_to_get", None)
            if data_need is None:
                data_need = self.ts2db_auto_detect__check_downloaded_db_data()
            completed = 0
            for _, row in data_need.iterrows():
                self.params.str_date = row["str_date"]
                self.params.end_date = row["end_date"]
                self._run()
                completed += 1
            return completed
        except Exception as ex:
            logging.warning(
                f"数据表 {self.params.table_name} ({self.params.table_name_cn}) "
                f"在断点续作时报错，框架将继续处理。{ex}"
            )
            raise
        finally:
            self.params.str_date = str_date
            self.params.end_date = end_date

    def ts2db_after_run(self):
        return None

    def _run_one_page(self):
        df_get_count = self.ts2db_get_data_agent()
        df_clean_count = self.ts2db_clean_data_agent()
        df_write_count = self.ts2db_write_db_agent()
        return df_get_count, df_clean_count, df_write_count

    def _log_call_result(
        self,
        df_get_count,
        df_clean_count,
        df_write_count,
    ):
        self.ts_api_call_count_all = (
            getattr(self, "ts_api_call_count_all", 0) + 1
        )
        scope = self._page_scope_description()
        logging.info(
            f"{getattr(self.params, 'msg_title', '')} 对应的接口已调用 "
            f"{self.ts_api_call_count_all}次，{scope}"
            f"抓取条数 {df_get_count} 清洗后 {df_clean_count} "
            f"最终入库 {df_write_count}"
        )
        return None

    def _page_scope_description(self):
        title = getattr(self.params, "msg_title", "")
        str_date = getattr(self.params, "str_date", "")
        end_date = getattr(self.params, "end_date", "")
        idate = getattr(self.params, "idate", "")
        code = str(getattr(self.params, "code", "") or "")
        code_values = [item for item in code.split(",") if item]
        batch_number = getattr(self, "_code_batch_number", 1)
        batch_total = getattr(self, "_code_batch_total", 1)
        src = str(getattr(self.params, "src", "") or "")
        if code_values:
            code_scope = (
                f"从 {code_values[0]} 到 {code_values[-1]} "
                f"共 {len(code_values)} 个代码的数据，"
                f"第 {batch_number}/{batch_total} 轮，"
            )
        else:
            code_scope = ""
        if "日期段+代码列表模式" in title:
            return f"在日期段 {str_date} 到 {end_date} 上，{code_scope}"
        if "逐日+代码模式" in title:
            return f"在日期 {idate} 上，{code_scope}"
        if "逐日模式" in title:
            return f"抓取日期 {idate} "
        if "日期段模式" in title:
            return f"抓取日期 {str_date} 到 {end_date} "
        if "代码列表模式" in title:
            return code_scope
        if "实时模式_按数据源+代码列表" in title:
            return f"数据源 {src}，{code_scope}"
        if "实时模式_按数据源" in title:
            return f"数据源 {src}，"
        return ""

    def _run_paginated(self, itimes=0, sleep_after_last=False):
        configured_limit = getattr(
            self,
            "_configured_one_time_rows_limit",
            None,
        )
        if configured_limit is not None:
            self.params.one_time_rows_limit = configured_limit
        self.params.offset = 0
        self._pagination_page_number = 0
        while True:
            df_get_count, _, _ = self._run_one_page()
            itimes += 1
            if sleep_after_last:
                self.ts2db_times_sleep(itimes)
            if self.ts2db_should_we_end(df_get_count):
                return df_get_count, itimes
            if not sleep_after_last:
                self.ts2db_times_sleep(itimes)
            self.params.offset += self.params.one_time_rows_limit

    def _code_values(self):
        codelist = self.params.codelist
        if codelist is None:
            return []
        if hasattr(codelist, "__array__"):
            return [row[0] for row in codelist.__array__()]
        return list(codelist)

    def _iter_code_batches(self) -> Iterable[str]:
        values = self._code_values()
        size = max(int(self.params.how_many_codes_onetime), 1)
        for start in range(0, len(values), size):
            yield ",".join(str(value) for value in values[start : start + size])

    def _iter_complete_code_batches(self) -> Iterable[tuple[str, bool]]:
        """Yield the original combined-template batching state.

        The native implementation only submits complete batches.  It leaves an
        incomplete final batch in ``params.code`` without fetching it.
        """
        values = self._code_values()
        size = max(int(self.params.how_many_codes_onetime), 1)
        for start in range(0, len(values), size):
            batch = values[start : start + size]
            yield ",".join(str(value) for value in batch), len(batch) == size


class ts2db_by_limit_template(ts2db_father_template):
    def ts2db_init_before(self):
        self.params.auto_detect__break_point_type = 2

    def ts2db_init_after(self):
        self.params.msg_title = f"J21 database[全加载模式][{self.params.table_name}]："

    def ts2db_get_data(self):
        return self.params.ts_api(
            limit=self.params.one_time_rows_limit, offset=self.params.offset
        )

    def _run(self):
        result, _ = self._run_paginated()
        return result


class ts2db_by_date_template(ts2db_father_template):
    def ts2db_init_before(self):
        self.params.auto_detect__break_point_type = 1

    def ts2db_init_after(self):
        self.params.msg_title = f"J21 database[逐日模式][{self.params.table_name}]："

    def ts2db_get_data(self):
        return self.params.ts_api(
            trade_date=self.params.idate,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    def ts2db_check_data_is_ok(self):
        last_t1_date = get_last_work_date(
            self.params.db_engine, self.params.idate, self.params.market
        )
        sql = (
            f"select count(*) from {self.params.table_name} where trade_date = "
            f"'{last_t1_date}'"
        )
        return pd.read_sql_query(sql, self.params.db_engine)

    def _run(self):
        self.params.idate = self.params.str_date
        itimes = 0
        result = 0
        while self.params.idate <= self.params.end_date:
            if is_working_date(
                self.params.db_engine, self.params.idate, self.params.market
            ):
                result, itimes = self._run_paginated(itimes, sleep_after_last=True)
            self.params.idate = get_next_day_str(self.params.idate)
        return result


class ts2db_by_period_template(ts2db_father_template):
    def ts2db_init_before(self):
        self.params.auto_detect__break_point_type = 1

    def ts2db_init_after(self):
        self.params.msg_title = f"J21 database[日期段模式][{self.params.table_name}]："

    def ts2db_get_data(self):
        return self.params.ts_api(
            start_date=self.params.str_date,
            end_date=self.params.end_date,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    def _run(self):
        result, _ = self._run_paginated(sleep_after_last=True)
        return result


class ts2db_by_codelist_template(ts2db_father_template):
    def ts2db_init_before(self):
        self.params.auto_detect__break_point_type = 2

    def ts2db_init_after(self):
        self.params.msg_title = f"J21 database[代码列表模式][{self.params.table_name}]："

    def ts2db_get_data(self):
        return self.params.ts_api(
            ts_code=self.params.code,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    def _run(self):
        itimes = 0
        result = 0
        code_batches = list(self._iter_code_batches())
        self._code_batch_total = len(code_batches)
        for batch_number, code_str in enumerate(code_batches, start=1):
            self._code_batch_number = batch_number
            self.params.code = code_str
            result, itimes = self._run_paginated(itimes, sleep_after_last=True)
        self.params.code = ""
        return result


class ts2db_by_period_and_codelist_template(ts2db_father_template):
    def ts2db_init_before(self):
        self.params.auto_detect__break_point_type = 1

    def ts2db_init_after(self):
        self.params.msg_title = (
            f"J21 database[日期段+代码列表模式][{self.params.table_name}]："
        )

    def ts2db_get_data(self):
        return self.params.ts_api(
            ts_code=self.params.code,
            start_date=self.params.str_date,
            end_date=self.params.end_date,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    def _run(self):
        itimes = 0
        result = 1
        code_batches = list(self._iter_code_batches())
        self._code_batch_total = len(code_batches)
        for batch_number, code_str in enumerate(code_batches, start=1):
            self._code_batch_number = batch_number
            self.params.code = code_str
            result, itimes = self._run_paginated(itimes, sleep_after_last=True)
        self.params.code = ""
        return result


class ts2db_by_date_and_codelist_template(ts2db_father_template):
    def ts2db_init_before(self):
        self.params.auto_detect__break_point_type = 1

    def ts2db_init_after(self):
        self.params.msg_title = f"J21 database[逐日+代码模式][{self.params.table_name}]："

    def ts2db_get_data(self):
        return self.params.ts_api(
            ts_code=self.params.code,
            start_date=self.params.str_date,
            end_date=self.params.end_date,
            limit=self.params.one_time_rows_limit,
            offset=self.params.offset,
        )

    def _run(self):
        self.params.idate = self.params.str_date
        itimes = 0
        result = 1
        while self.params.idate <= self.params.end_date:
            if is_working_date(
                self.params.db_engine, self.params.idate, self.params.market
            ):
                for code_str in self._iter_code_batches():
                    self._code_batch_number = 1
                    self._code_batch_total = 1
                    self.params.code = code_str
                    result, itimes = self._run_paginated(
                        itimes, sleep_after_last=True
                    )
                    self.params.code = ""
            self.params.idate = get_next_day_str(self.params.idate)
        self.params.code = ""
        return result


class ts2db_rt_by_src_template(ts2db_father_template):
    def ts2db_init_before(self):
        self.params.auto_detect__break_point_type = 0
        self.params.rt_deal_duplicate_data = True
        self.df_all_cache_count = 0

    def ts2db_init_after(self):
        self.params.msg_title = f"J21 database[实时模式_按数据源][{self.params.table_name}]："

    def ts2db_get_data(self):
        return self.params.ts_api(src=self.params.src)

    def _run(self):
        i_times = 0
        while datetime.datetime.now().strftime("%H:%M:%S") <= self.params.end_time:
            if datetime.datetime.now().strftime("%H:%M:%S") >= self.params.str_time:
                self.ts2db_get_data_agent()
                self.ts2db_clean_data_agent()
                self.ts2db_rt__get_add_data()
                self.ts2db_write_db_agent()
                i_times += 1
            self.ts2db_rt__gap_sleep()
        return i_times


class ts2db_rt_by_src_and_codelist_template(ts2db_father_template):
    def ts2db_init_before(self):
        self.params.auto_detect__break_point_type = 0
        self.params.rt_deal_duplicate_data = True
        self.df_all_cache_count = 0

    def ts2db_init_after(self):
        self.params.msg_title = (
            f"J21 database[实时模式_按数据源+代码列表][{self.params.table_name}]："
        )

    def ts2db_get_data(self):
        return self.params.ts_api(ts_code=self.params.code, src=self.params.src)

    def _run(self):
        i_times = 0
        while datetime.datetime.now().strftime("%H:%M:%S") <= self.params.end_time:
            if datetime.datetime.now().strftime("%H:%M:%S") >= self.params.str_time:
                code_batches = list(self._iter_code_batches())
                self._code_batch_total = len(code_batches)
                for batch_number, code_str in enumerate(
                    code_batches,
                    start=1,
                ):
                    self._code_batch_number = batch_number
                    self.params.code = code_str
                    self.ts2db_get_data_agent()
                    self.ts2db_clean_data_agent()
                    self.ts2db_rt__get_add_data()
                    self.ts2db_write_db_agent()
                self.params.code = ""
                i_times += 1
            self.ts2db_rt__gap_sleep()
        return i_times


class ts_api:
    def __init__(self):
        legacy_authorization_removed("basis.tools.ts_api")

    def get_time(self):
        legacy_authorization_removed("basis.tools.ts_api.get_time")

    def get_serial_number(self):
        legacy_authorization_removed("basis.tools.ts_api.get_serial_number")

    def get_sn__default(self):
        legacy_authorization_removed("basis.tools.ts_api.get_sn__default")

    def get_sn__win(self):
        legacy_authorization_removed("basis.tools.ts_api.get_sn__win")

    def _get_sn__win__cpu_id(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__win__cpu_id")

    def _get_sn__win__baseboard_id(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__win__baseboard_id")

    def get_sn__mac(self):
        legacy_authorization_removed("basis.tools.ts_api.get_sn__mac")

    def _get_sn__mac__hardware_serial(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__mac__hardware_serial")

    def _get_sn__mac__board_id(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__mac__board_id")

    def get_sn__linux(self):
        legacy_authorization_removed("basis.tools.ts_api.get_sn__linux")

    def _get_sn__linux__cpu_info(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__linux__cpu_info")

    def _get_sn__linux__machine_id(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__linux__machine_id")

    def _get_sn__linux__host_name(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__linux__host_name")

    def _get_sn__linux__board_id(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__linux__board_id")

    def _get_sn__linux__disk_id(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__linux__disk_id")

    def _get_sn__linux__mac_addr(self):
        legacy_authorization_removed("basis.tools.ts_api._get_sn__linux__mac_addr")

    def AES_Encrypt(self, O0OO0000OOO0OOOOO):
        legacy_authorization_removed("basis.tools.ts_api.AES_Encrypt")

    def AES_Decrypt(self, O00OO000000000OO0):
        legacy_authorization_removed("basis.tools.ts_api.AES_Decrypt")

    def _ensure_key_length(self, OOOOO0O00O0OO0O0O, O0O00O0000OOO00OO):
        legacy_authorization_removed("basis.tools.ts_api._ensure_key_length")

    def get_ts_token(self, O0OO0O0OO0000000O):
        legacy_authorization_removed("basis.tools.ts_api.get_ts_token")

    def get_ts_api_exp_date(self, O00O0OO0OO0OO0O00, O00O00000OO000000):
        legacy_authorization_removed("basis.tools.ts_api.get_ts_api_exp_date")

    def re_check_ts_api(self):
        legacy_authorization_removed("basis.tools.ts_api.re_check_ts_api")

    def check_ts_pro_api(self):
        legacy_authorization_removed("basis.tools.ts_api.check_ts_pro_api")


class get_ts_api_params:
    def __init__(self):
        legacy_authorization_removed("basis.tools.get_ts_api_params")

    def get_web_content(self):
        legacy_authorization_removed("basis.tools.get_ts_api_params.get_web_content")

    def is_ts_api_ok(self):
        legacy_authorization_removed("basis.tools.get_ts_api_params.is_ts_api_ok")


class get_web_params:
    def __init__(self):
        legacy_authorization_removed("basis.tools.get_web_params")

    def get_web_content(self):
        legacy_authorization_removed("basis.tools.get_web_params.get_web_content")

    def get_ts_api_b(self):
        legacy_authorization_removed("basis.tools.get_web_params.get_ts_api_b")


class db_utils:
    def has_table(self, obj, table_name):
        db_schema = obj.params.db_engine.url.database
        sql = (
            "SELECT count(*) FROM information_schema.TABLES WHERE "
            f"TABLE_SCHEMA = '{db_schema}' and TABLE_NAME = '{table_name}'"
        )
        try:
            df = pd.read_sql_query(sql, obj.params.db_engine)
            return bool(df.iloc[0, 0] > 0)
        except Exception as ex:
            logging.warning(f"检查数据表 {table_name} 时出错：{ex}")
            raise

    def create_index_if_not_exists(self, obj, keys):
        prefix = obj.params.table_name
        db_engine = obj.params.db_engine
        sql_name_keys = "_".join(keys)
        index_name = _bounded_mysql_index_name(
            f"{prefix}_{sql_name_keys}_index"
        )
        try:
            if self.has_index(obj, prefix, index_name):
                sql_keys = ", ".join(keys)
                logging.info(
                    f"数据表 {prefix} ({obj.params.table_name_cn}) 上，"
                    f"已有键字组合为：{sql_keys} 的索引 "
                    f"{index_name} 的索引，无需重建！"
                )
                return None
            sql_keys = ", ".join(keys)
            index_sql = f"create index {index_name} on {prefix} ({sql_keys})"
            db_engine.execute(index_sql)
            logging.info(f"在数据表 {prefix} 上建立索引 {index_name}")
        except Exception as ex:
            logging.warning(f"在数据表 {prefix} 上建立索引时出错：{ex}")
            raise
        return None

    def has_index(self, obj, table_name, index_name):
        db_schema = obj.params.db_engine.url.database
        sql = (
            "SELECT count(*) FROM information_schema.STATISTICS WHERE "
            f"TABLE_SCHEMA = '{db_schema}' and TABLE_NAME = '{table_name}' "
            f"AND INDEX_NAME = '{index_name}'"
        )
        try:
            df = pd.read_sql_query(sql, obj.params.db_engine)
            return bool(df.iloc[0, 0] > 0)
        except Exception as ex:
            logging.warning(
                f"检查数据表 {table_name} 上的索引 {index_name} 时出错：{ex}"
            )
            raise


class db_tools:
    def __init__(self, params=None):
        self.params = params
        if self.params.db_engine is None:
            self.params.db_engine = init_db()

    def drop_table(self):
        return drop_table(
            self.params.db_engine,
            self.params.table_name,
            getattr(self.params, "table_name_cn", self.params.table_name),
        )

    def truncate_table(self):
        self.params.db_engine.execute(f"truncate table {self.params.table_name}")

    @lru_cache(maxsize=None)
    def has_column(self, table_name=None, column_name=None):
        sql = f"select * from {table_name} limit 0"
        frame = pd.read_sql_query(sql, self.params.db_engine)
        return column_name in frame

    def has_table(self, table_name=None):
        db_schema = self.params.db_engine.url.database
        sql = (
            "SELECT count(*) from INFORMATION_SCHEMA.TABLES where "
            f"TABLE_SCHEMA = '{db_schema}' and "
            f"TABLE_NAME = '{table_name}'"
        )
        try:
            return bool(pd.read_sql_query(sql, self.params.db_engine).iloc[0, 0] > 0)
        except Exception:
            return False
