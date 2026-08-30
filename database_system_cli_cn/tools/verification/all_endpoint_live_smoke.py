"""Run one bounded live sample through every replica endpoint.

Each selected endpoint performs its normal request, cleanup, and database write.
The runner supplies one representative code/date, removes rows already present by
the endpoint's business key, and records permission, empty-data, schema, and other
failures separately.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import datetime as dt
from decimal import Decimal, InvalidOperation
import importlib
from io import StringIO
import json
from numbers import Number
from pathlib import Path
import re
import sys
import time

import pandas as pd
from sqlalchemy import inspect, text


PRODUCT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PRODUCT_ROOT.parent
MANIFEST_PATH = (
    WORKSPACE_ROOT / "playground" / "tushare2db_so_reverse" / "contracts" / "live_endpoints.json"
)
DEFAULT_REPORT = PRODUCT_ROOT / "reports" / "all_endpoint_live_smoke.json"
sys.path.insert(0, str(PRODUCT_ROOT))

from basis.constant import ts2db_config  # noqa: E402
from basis.init_env import init_db, init_ts, init_ts_pro  # noqa: E402
from basis.params import _params  # noqa: E402


TRADE_DATE = "20260810"
US_TRADE_DATE = "20260807"
FIN_START_DATE = "20250101"
FIN_END_DATE = "20251231"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EXPECTED_DATABASE = "a_share"


SAMPLE_CODES = {
    "alt": "000001.SZ",
    "cb": "117103.SZ",
    "fin": "000001.SZ",
    "fund": "000001.OF",
    "fut": "L2508.DCE",
    "fx": "AUDCAD.FXCM",
    "hk": "00001.HK",
    "idx": "000300.SH",
    "opt": "B2707-C-3200.DCE",
    "realtime": "000001.SZ",
    "ref": "000001.SZ",
    "stk": "000001.SZ",
    "stk_limit": "000001.SZ",
    "ths_dc": "883300.TI",
    "us": "AAPL",
}

SPECIAL_DATES = {
    "balancesheet_vip": ("20250630", "20250630"),
    "ccass_hold_detail": ("20211101", "20211101"),
    "fund_portfolio": ("20180101", "20181231"),
    "fx_daily": ("20190501", "20190524"),
    "kpl_list": ("20240927", "20240927"),
}


class ProviderCallLimitError(RuntimeError):
    """Raised before a sample can exceed its per-entry provider-call cap."""


class _CountingProxy:
    def __init__(self, target, *, limit: int, add_retry_count: bool = False):
        self._target = target
        self._limit = limit
        self._add_retry_count = add_retry_count
        self.calls = []
        self.messages = []

    def __getattr__(self, name):
        value = getattr(self._target, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            if len(self.calls) >= self._limit:
                raise ProviderCallLimitError(
                    f"provider call cap {self._limit} reached before {name}"
                )
            self.calls.append(name)
            if self._add_retry_count and name == "pro_bar":
                kwargs.setdefault("retry_count", 1)
            output = StringIO()
            try:
                with redirect_stdout(output), redirect_stderr(output):
                    return value(*args, **kwargs)
            finally:
                message = output.getvalue().strip()
                if message:
                    self.messages.append(message)

        return call


def _load_entries():
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != 93:
        raise RuntimeError("live endpoint manifest must contain exactly 93 entries")
    return entries


def _identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return value


def _sample_dates(entry):
    if entry["endpoint"] in SPECIAL_DATES:
        return SPECIAL_DATES[entry["endpoint"]]
    if entry["category"] == "fin":
        return FIN_START_DATE, FIN_END_DATE
    date = US_TRADE_DATE if entry["category"] == "us" else TRADE_DATE
    return date, date


def _sample_code(entry):
    endpoint = entry["endpoint"]
    if endpoint == "fund_portfolio":
        return "001753.OF"
    if endpoint in {"fund_daily", "fund_adj", "fund_share", "pro_bar"} and (
        entry["category"] == "fund"
    ):
        return "510300.SH"
    if endpoint == "fut_mapping":
        return "IF.CFX"
    if endpoint in {"index_member", "index_member_all", "sw_daily"}:
        return "801010.SI"
    if endpoint in {"ths_daily", "ths_member"}:
        return "883300.TI"
    return SAMPLE_CODES.get(entry["category"], "000001.SZ")


def _new_endpoint(entry, engine, raw_pro, raw_ts, *, call_limit):
    module = importlib.import_module(entry["module"])
    endpoint_class = getattr(module, entry["class"])
    start_date, end_date = _sample_dates(entry)
    code = _sample_code(entry)
    params = _params(str_date=start_date, end_date=end_date)
    params.idate = start_date
    params.str_time = "09:30:00"
    params.end_time = "09:30:01"
    params.offset = 0
    params.report_type = ""
    params.code = code
    params.codelist = pd.DataFrame({"ts_code": [code]})
    params.db_engine = engine
    pro = _CountingProxy(raw_pro, limit=call_limit)
    ts_module = _CountingProxy(
        raw_ts,
        limit=call_limit,
        add_retry_count=True,
    )
    params.ts_pro = pro
    params.ts = ts_module
    params.table_name = entry["table"]
    params.table_name_cn = entry["description"]

    endpoint = object.__new__(endpoint_class)
    endpoint.df = None
    endpoint.df_get_count_all = 0
    endpoint.df_clean_count_all = 0
    endpoint.df_write_count_all = 0
    endpoint.df_cache = None
    endpoint.df_cache_count_all = 0
    endpoint.params = params
    endpoint.ts2db_init_before()
    endpoint.ts2db_init()
    endpoint.ts2db_init_after()

    # Endpoint initialization may load a full database code list.  This smoke
    # intentionally exercises exactly one representative code.
    endpoint.params.str_date = start_date
    endpoint.params.end_date = end_date
    endpoint.params.idate = start_date
    endpoint.params.code = code
    endpoint.params.codelist = pd.DataFrame({"ts_code": [code]})
    endpoint.params.offset = 0
    endpoint.params.retry_times = 1
    endpoint.params.retry_sleep_time = 0
    if entry["endpoint"] == "index_classify":
        endpoint.params.level = "L1"
    if entry["endpoint"] == "fut_basic":
        endpoint.params.exchange = "DCE"
    if entry["id"].endswith("Get_stk_basic_all.get_stk_basic_all"):
        endpoint.params.list_status = "L"
    endpoint.params.one_time_rows_limit = min(
        max(int(endpoint.params.one_time_rows_limit or 5000), 1),
        5000,
    )
    endpoint.params.db_engine = engine

    table_name = endpoint.params.table_name
    if table_name != entry["table"]:
        raise ValueError(
            f"endpoint table {table_name!r} does not match manifest {entry['table']!r}"
        )
    return endpoint, pro, ts_module, code, start_date, end_date


def _normalize_key(key, value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dt.datetime, dt.date, pd.Timestamp)):
        return value.strftime("%Y%m%d") if "date" in key else str(value)
    if isinstance(value, Number) and not isinstance(value, bool):
        try:
            return str(Decimal(str(value)).normalize())
        except InvalidOperation:
            return str(value)
    result = str(value)
    if "date" in key:
        result = result.replace("-", "")
    return result


def _table_columns(engine, table_name):
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def _existing_keys(engine, table_name, keys, frame):
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return set()
    missing = set(keys) - _table_columns(engine, table_name)
    if missing:
        raise ValueError(f"existing table is missing business keys: {sorted(missing)}")

    names = ",".join(_identifier(key) for key in keys)
    date_key = next((key for key in keys if "date" in key), None)
    params = {}
    where = ""
    if date_key and date_key in frame:
        values = sorted(
            {
                _normalize_key(date_key, value)
                for value in frame[date_key].tolist()
                if _normalize_key(date_key, value) is not None
            }
        )
        if values:
            markers = ",".join(f":value_{index}" for index in range(len(values)))
            params = {f"value_{index}": value for index, value in enumerate(values)}
            where = f" WHERE REPLACE(CAST({_identifier(date_key)} AS CHAR), '-', '') IN ({markers})"
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT {names} FROM {_identifier(table_name)}{where}"),
            params,
        ).fetchall()
    return {tuple(_normalize_key(key, value) for key, value in zip(keys, row)) for row in rows}


def _new_rows(engine, table_name, keys, frame):
    missing = [key for key in keys if key not in frame.columns]
    if missing:
        raise ValueError(f"provider response is missing business keys: {missing}")
    unique = frame.drop_duplicates(list(keys)).copy()
    existing = _existing_keys(engine, table_name, keys, unique)
    if not existing:
        return unique.reset_index(drop=True)
    keep = [
        tuple(_normalize_key(key, row[key]) for key in keys) not in existing
        for _, row in unique.iterrows()
    ]
    return unique.loc[keep].reset_index(drop=True)


def _row_count(engine, table_name):
    if not inspect(engine).has_table(table_name):
        return 0
    with engine.connect() as connection:
        return int(
            connection.execute(text(f"SELECT COUNT(*) FROM {_identifier(table_name)}")).scalar()
        )


def _secret_values():
    found = set()

    def visit(value, label=""):
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, str(key).lower())
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item, label)
        elif any(word in label for word in ("token", "password", "passwd")):
            if isinstance(value, str) and len(value) >= 4:
                found.add(value)

    visit(ts2db_config.ts2db_config)
    return tuple(sorted(found, key=len, reverse=True))


def _safe_error(error):
    message = str(error)
    for secret in _secret_values():
        message = message.replace(secret, "[redacted]")
    return f"{type(error).__name__}: {message}"


def _failure_status(error, provider_messages="", endpoint=""):
    message = f"{error}\n{provider_messages}".lower()
    if "unsupported" in type(error).__name__.lower():
        return "UNSUPPORTED"
    if endpoint == "limit_list" and "正确的接口名" in message:
        return "REPLACED"
    if "outsidesession" in type(error).__name__.lower() or ("outside one continuous" in message):
        return "OUTSIDE_SESSION"
    if any(
        text_value in message
        for text_value in (
            "没有访问该接口的权限",
            "没有接口(",
            "无权限",
            "permission denied",
            "not have permission",
        )
    ):
        return "NO_PERMISSION"
    if any(text_value in message for text_value in ("每分钟", "rate limit", "频率", "最多访问")):
        return "RATE_LIMIT"
    if isinstance(error, (KeyError, ValueError, TypeError)):
        return "LOGIC_ERROR"
    return "ERROR"


def _run_entry(entry, engine, raw_pro, raw_ts, *, execute, call_limit):
    table_name = entry["table"]
    before_rows = _row_count(engine, table_name)
    pro = ts_module = None
    code = start_date = end_date = None
    try:
        endpoint, pro, ts_module, code, start_date, end_date = _new_endpoint(
            entry,
            engine,
            raw_pro,
            raw_ts,
            call_limit=call_limit,
        )
        frame = endpoint.ts2db_get_data()
        if frame is None:
            frame = pd.DataFrame()
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"provider returned {type(frame).__name__}, not DataFrame")
        endpoint.df = frame.copy()
        endpoint.ts2db_clean_data()
        if endpoint.df is None:
            endpoint.df = pd.DataFrame()
        if not isinstance(endpoint.df, pd.DataFrame):
            raise TypeError("cleaner did not leave a DataFrame")
        provider_rows = len(frame)
        cleaned_rows = len(endpoint.df)
        duplicate_key = (
            getattr(endpoint.params, "deal_data__duplicate_data_key", None)
            or entry["duplicate_key"]
        )
        keys = tuple(key.strip() for key in duplicate_key.split(",") if key.strip())
        pending = _new_rows(engine, table_name, keys, endpoint.df) if cleaned_rows else endpoint.df
        if execute and not pending.empty:
            endpoint.df = pending
            endpoint.ts2db_write_db()
        after_rows = _row_count(engine, table_name)
        inserted_rows = after_rows - before_rows
        if execute and inserted_rows != len(pending):
            raise RuntimeError(
                f"write count mismatch: expected {len(pending)}, got {inserted_rows}"
            )
        return {
            "status": "PASS" if cleaned_rows else "EMPTY",
            "category": entry["category"],
            "endpoint": entry["endpoint"],
            "table": table_name,
            "sample_code": code,
            "sample_start_date": start_date,
            "sample_end_date": end_date,
            "provider_calls": len(pro.calls) + len(ts_module.calls),
            "provider_methods": pro.calls + ts_module.calls,
            "provider_rows": provider_rows,
            "cleaned_rows": cleaned_rows,
            "new_rows": len(pending),
            "inserted_rows": inserted_rows,
            "table_rows_before": before_rows,
            "table_rows_after": after_rows,
            "columns": list(endpoint.df.columns),
        }
    except Exception as error:
        after_rows = _row_count(engine, table_name)
        provider_messages = (
            "" if pro is None or ts_module is None else "\n".join(pro.messages + ts_module.messages)
        )
        return {
            "status": _failure_status(
                error,
                provider_messages,
                endpoint=entry["endpoint"],
            ),
            "category": entry["category"],
            "endpoint": entry["endpoint"],
            "table": table_name,
            "sample_code": code,
            "sample_start_date": start_date,
            "sample_end_date": end_date,
            "provider_calls": (
                0 if pro is None or ts_module is None else len(pro.calls) + len(ts_module.calls)
            ),
            "provider_methods": (
                [] if pro is None or ts_module is None else pro.calls + ts_module.calls
            ),
            "inserted_rows": after_rows - before_rows,
            "table_rows_before": before_rows,
            "table_rows_after": after_rows,
            "error": _safe_error(error),
            "provider_message": _safe_error(Exception(provider_messages))
            if provider_messages
            else None,
        }


def run(entries, *, execute, call_limit, delay_seconds):
    engine = init_db()
    results = {}
    try:
        with engine.connect() as connection:
            selected_database = connection.execute(text("SELECT DATABASE()"))
            selected_database = selected_database.scalar()
        if engine.url.database != EXPECTED_DATABASE or selected_database != EXPECTED_DATABASE:
            raise RuntimeError("live smoke requires the configured a_share database")
        raw_pro = init_ts_pro()
        raw_ts = init_ts()
        for index, entry in enumerate(entries, start=1):
            result = _run_entry(
                entry,
                engine,
                raw_pro,
                raw_ts,
                execute=execute,
                call_limit=call_limit,
            )
            results[entry["id"]] = result
            print(
                f"[{index:02d}/{len(entries):02d}] {result['status']:<13} "
                f"{entry['category']}/{entry['endpoint']} "
                f"calls={result['provider_calls']} "
                f"rows={result.get('provider_rows', 0)} "
                f"inserted={result['inserted_rows']}",
                flush=True,
            )
            if delay_seconds and index != len(entries):
                time.sleep(delay_seconds)
    finally:
        engine.dispose()
    counts = Counter(item["status"] for item in results.values())
    return {
        "database": EXPECTED_DATABASE,
        "execute": execute,
        "entry_count": len(entries),
        "provider_call_cap_per_entry": call_limit,
        "status_counts": dict(sorted(counts.items())),
        "provider_calls": sum(item["provider_calls"] for item in results.values()),
        "inserted_rows": sum(item["inserted_rows"] for item in results.values()),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--category", action="append")
    parser.add_argument("--only", action="append", help="exact manifest entry id")
    parser.add_argument("--max-entries", type=int)
    parser.add_argument("--call-limit", type=int, default=8)
    parser.add_argument("--delay-seconds", type=float, default=0.35)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    entries = _load_entries()
    if args.category:
        categories = set(args.category)
        entries = [entry for entry in entries if entry["category"] in categories]
    if args.only:
        ids = set(args.only)
        entries = [entry for entry in entries if entry["id"] in ids]
    if args.max_entries is not None:
        entries = entries[: max(args.max_entries, 0)]
    if not entries:
        parser.error("no endpoints selected")

    result = run(
        entries,
        execute=args.execute,
        call_limit=max(args.call_limit, 1),
        delay_seconds=max(args.delay_seconds, 0),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "results"},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    print(f"report={args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
