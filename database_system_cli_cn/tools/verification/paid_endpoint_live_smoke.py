"""Run one small real request for each independently paid endpoint.

The script writes successful responses to the normal replica tables.  It caps
each endpoint at one provider request and skips rows whose business keys are
already present, so it can be re-run without duplicating the smoke sample.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import create_engine, inspect, text


PRODUCT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PRODUCT_ROOT))

from basis.constant import ts2db_config  # noqa: E402
from basis.init_env import init_ts, init_ts_pro  # noqa: E402


TRADE_DATE = "20260810"
US_TRADE_DATE = "20260807"


ENDPOINTS = (
    "cctv_news",
    "fund_1min",
    "fut_1min",
    "fut_5min",
    "opt_1min",
    "hk_daily_adj",
    "us_daily",
    "us_daily_adj",
)


def _load_endpoint(relative_path: str, class_name: str):
    path = PRODUCT_ROOT / "get_ph_data_from_ts" / relative_path
    module_name = "_paid_live_" + relative_path.replace("/", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def _instance(endpoint_class, params):
    value = object.__new__(endpoint_class)
    value.params = params
    value.df = None
    return value


def _iso_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _one_request_ts(ts_module):
    return SimpleNamespace(
        pro_bar=lambda **kwargs: ts_module.pro_bar(
            retry_count=1,
            **kwargs,
        )
    )


def _build_cases(engine, pro, ts_module):
    cctv_class = _load_endpoint(
        "alt/Get_alt_cctv_news.py",
        "get_alt_cctv_news",
    )
    fund_class = _load_endpoint(
        "fund/Get_fund_1min.py",
        "get_fund_1min",
    )
    fut_1_class = _load_endpoint(
        "fut/Get_fut_1min.py",
        "get_fut_1min",
    )
    fut_5_class = _load_endpoint(
        "fut/Get_fut_5min.py",
        "get_fut_5min",
    )
    opt_class = _load_endpoint(
        "opt/Get_opt_1min.py",
        "get_opt_1min",
    )
    hk_class = _load_endpoint(
        "hk/Get_hk_daily_adj.py",
        "get_hk_daily_adj",
    )
    us_class = _load_endpoint(
        "us/Get_us_daily.py",
        "get_us_daily",
    )
    us_adj_class = _load_endpoint(
        "us/Get_us_daily_adj.py",
        "get_us_daily_adj",
    )

    cctv = _instance(
        cctv_class,
        SimpleNamespace(
            ts_api=pro.cctv_news,
            idate=TRADE_DATE,
            one_time_rows_limit=500,
            offset=0,
            table_name=cctv_class.table_name,
            db_engine=engine,
        ),
    )
    fund = _instance(
        fund_class,
        SimpleNamespace(
            ts=_one_request_ts(ts_module),
            code="510300.SH",
            freq="1min",
            get_idate_iso=lambda: _iso_date(TRADE_DATE),
            one_time_rows_limit=8000,
            offset=0,
            table_name=fund_class.table_name,
            db_engine=engine,
        ),
    )

    def future_instance(endpoint_class, frequency):
        return _instance(
            endpoint_class,
            SimpleNamespace(
                ts_pro=pro,
                code="IF2608.CFX",
                freq=frequency,
                get_idate_iso=lambda: _iso_date(TRADE_DATE),
                one_time_rows_limit=8000,
                offset=0,
                table_name=endpoint_class.table_name,
                db_engine=engine,
            ),
        )

    option = _instance(
        opt_class,
        SimpleNamespace(
            ts=_one_request_ts(ts_module),
            code="C2707-C-2400.DCE",
            freq="1min",
            get_idate_iso=lambda: _iso_date(TRADE_DATE),
            one_time_rows_limit=8000,
            offset=0,
            table_name=opt_class.table_name,
            db_engine=engine,
        ),
    )
    hk = _instance(
        hk_class,
        SimpleNamespace(
            ts_api=pro.hk_daily_adj,
            str_date=TRADE_DATE,
            end_date=TRADE_DATE,
            one_time_rows_limit=6000,
            offset=0,
            table_name=hk_class.table_name,
            db_engine=engine,
        ),
    )
    us = _instance(
        us_class,
        SimpleNamespace(
            ts_api=pro.us_daily,
            idate=US_TRADE_DATE,
            one_time_rows_limit=6000,
            offset=0,
            table_name=us_class.table_name,
            db_engine=engine,
        ),
    )
    us_adj = _instance(
        us_adj_class,
        SimpleNamespace(
            ts_api=pro.us_daily_adj,
            idate=US_TRADE_DATE,
            one_time_rows_limit=8000,
            offset=0,
            table_name=us_adj_class.table_name,
            db_engine=engine,
        ),
    )

    return {
        "cctv_news": (cctv, ("trade_date", "title")),
        "fund_1min": (
            fund,
            ("trade_date", "trade_time", "ts_code"),
        ),
        "fut_1min": (
            future_instance(fut_1_class, "1min"),
            ("trade_date", "trade_time", "ts_code"),
        ),
        "fut_5min": (
            future_instance(fut_5_class, "5min"),
            ("trade_date", "trade_time", "ts_code"),
        ),
        "opt_1min": (
            option,
            ("trade_date", "trade_time", "ts_code"),
        ),
        "hk_daily_adj": (hk, ("trade_date", "ts_code")),
        "us_daily": (us, ("trade_date", "ts_code")),
        "us_daily_adj": (us_adj, ("trade_date", "ts_code")),
    }


def _normalize_key(key, value):
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d") if key == "trade_date" else str(value)
    text_value = str(value)
    if key == "trade_date":
        return text_value.replace("-", "")
    return text_value


def _existing_keys(engine, table_name, keys, frame):
    if not inspect(engine).has_table(table_name):
        return set()
    dates = {
        _normalize_key("trade_date", value)
        for value in frame["trade_date"].tolist()
        if value is not None
    }
    if not dates:
        return set()
    placeholders = ",".join(f":date_{index}" for index in range(len(dates)))
    params = {
        f"date_{index}": value
        for index, value in enumerate(sorted(dates))
    }
    columns = ",".join(f"`{key}`" for key in keys)
    query = text(
        f"SELECT {columns} FROM `{table_name}` "
        f"WHERE REPLACE(CAST(`trade_date` AS CHAR), '-', '') "
        f"IN ({placeholders})"
    )
    with engine.connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return {
        tuple(_normalize_key(key, value) for key, value in zip(keys, row))
        for row in rows
    }


def _new_rows(engine, table_name, keys, frame):
    if frame.empty:
        return frame
    missing = [key for key in keys if key not in frame.columns]
    if missing:
        raise ValueError(f"provider response is missing business keys: {missing}")
    frame = frame.drop_duplicates(list(keys)).copy()
    existing = _existing_keys(engine, table_name, keys, frame)
    if not existing:
        return frame
    keep = [
        tuple(_normalize_key(key, row[key]) for key in keys) not in existing
        for _, row in frame.iterrows()
    ]
    return frame.loc[keep].reset_index(drop=True)


def _table_snapshot(engine, table_name):
    if not inspect(engine).has_table(table_name):
        return {"exists": False, "rows": 0, "columns": []}
    with engine.connect() as connection:
        rows = int(
            connection.execute(
                text(f"SELECT COUNT(*) FROM `{table_name}`")
            ).scalar()
        )
        columns = [
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=:schema AND table_name=:table "
                    "ORDER BY ordinal_position"
                ),
                {
                    "schema": engine.url.database,
                    "table": table_name,
                },
            ).fetchall()
        ]
    return {"exists": True, "rows": rows, "columns": columns}


def _configured_token():
    for item in ts2db_config.ts2db_config.get("server_config", []):
        if item.get("server") == "ts":
            return item.get("token") or ""
    return ""


def _safe_error(error):
    message = str(error)
    token = _configured_token()
    if token:
        message = message.replace(token, "[redacted]")
    return f"{type(error).__name__}: {message}"


def run(selected, *, execute):
    engine = create_engine(ts2db_config.dbPath, pool_pre_ping=True)
    pro = init_ts_pro()
    ts_module = init_ts()
    cases = _build_cases(engine, pro, ts_module)
    results = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        for name in selected:
            endpoint, keys = cases[name]
            table_name = endpoint.params.table_name
            try:
                frame = endpoint.ts2db_get_data()
                if frame is None:
                    frame = pd.DataFrame()
                if not isinstance(frame, pd.DataFrame):
                    raise TypeError(
                        f"provider returned {type(frame).__name__}, not DataFrame"
                    )
                endpoint.df = frame.copy()
                endpoint.ts2db_clean_data()
                provider_rows = len(endpoint.df)
                columns = list(endpoint.df.columns)
                pending = _new_rows(
                    engine,
                    table_name,
                    keys,
                    endpoint.df,
                )
                inserted = 0
                if execute and not pending.empty:
                    endpoint.df = pending
                    written = endpoint.ts2db_write_db()
                    inserted = len(pending) if written is None else int(written)
                results[name] = {
                    "status": "PASS" if provider_rows else "EMPTY",
                    "provider_rows": provider_rows,
                    "new_rows": len(pending),
                    "inserted_rows": inserted,
                    "columns": columns,
                    "table": table_name,
                    "database": engine.url.database,
                    "table_after": _table_snapshot(engine, table_name),
                }
            except Exception as error:
                results[name] = {
                    "status": "ERROR",
                    "error": _safe_error(error),
                    "table": table_name,
                    "database": engine.url.database,
                    "table_after": _table_snapshot(engine, table_name),
                }
    finally:
        engine.dispose()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="write successful provider responses to the replica database",
    )
    parser.add_argument(
        "--only",
        choices=ENDPOINTS,
        action="append",
        help="run only a named endpoint; may be repeated",
    )
    args = parser.parse_args()
    selected = tuple(args.only) if args.only else ENDPOINTS
    result = {
        "execute": args.execute,
        "provider_request_limit": len(selected),
        "results": run(selected, execute=args.execute),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return int(any(item["status"] == "ERROR" for item in result["results"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
