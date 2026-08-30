#!/usr/bin/env python3
"""Run the purchased original package one endpoint at a time and retain its logs.

This helper lives in the replica workspace.  It only imports and executes the
original package named by ``--original-root``; it never edits that package.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


DEFAULT_ORIGINAL_ROOT = Path(
    "/Users/boqingxin/tandon MSCS/My_Own/tushare2db_pro_v7_0_for_mac_on_python3_11_3"
)
PRODUCT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_DIR = (
    PRODUCT_ROOT / "reports" / "original_framework_logs_20260812"
)
MAX_DATABASE_BYTES = 5_000_000_000
CHILD_ENVIRONMENT_KEYS = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "NO_PROXY",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SHELL",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
        "TZ",
        "USER",
    }
)


def _endpoint(
    name: str,
    table: str,
    group: str,
    *,
    no_params: bool = False,
    function: bool = False,
    sample_code: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "table": table,
        "group": group,
        "no_params": no_params,
        "function": function,
        "sample_code": sample_code,
    }


# This is the exact 67-entry inventory of the original master list.  Excluded
# entries stay visible so the plan explains why they are not silently run.
ENDPOINTS = (
    # Existing five-endpoint baseline.
    _endpoint("get_tradeCal", "hq_trade_cal", "baseline", no_params=True),
    _endpoint("get_hk_tradeCal", "hq_hk_trade_cal", "baseline", no_params=True),
    _endpoint("get_us_tradeCal", "hq_us_trade_cal", "baseline", no_params=True),
    _endpoint("get_stk_basic", "hq_stk_basic", "baseline", no_params=True),
    _endpoint("get_stk_daily", "hq_stk_daily", "baseline"),
    # Small reload/basic/prerequisite endpoints, then ordinary date endpoints.
    _endpoint("get_stk_basic_all", "hq_stk_basic_all", "short", no_params=True),
    _endpoint("get_cb_basic", "hq_cb_basic", "short", no_params=True),
    _endpoint("get_fund_basic", "hq_fund_basic", "short", no_params=True),
    _endpoint("get_fut_basic", "hq_fut_basic", "short", no_params=True),
    _endpoint("get_hk_basic", "hq_hk_basic", "short", no_params=True),
    _endpoint("get_idx_basic", "hq_idx_basic", "short", no_params=True),
    _endpoint("get_ths_index", "hq_ths_index", "short", no_params=True),
    _endpoint("get_opt_basic", "hq_opt_basic", "short", no_params=True),
    _endpoint("get_us_basic", "hq_us_basic", "short", no_params=True),
    _endpoint("get_fx_obasic", "hq_fx_obasic", "short", no_params=True),
    _endpoint("get_idx_sw_classify", "hq_idx_sw_classify", "short", no_params=True),
    _endpoint(
        "get_idx_sw_member",
        "hq_idx_sw_member",
        "short",
        sample_code="801010.SI",
    ),
    _endpoint("get_fut_mapping", "hq_fut_mapping", "short", no_params=True),
    _endpoint("get_macro_cn_cpi", "hq_macro_cn_cpi", "short", no_params=True),
    _endpoint("get_macro_cn_gdp", "hq_macro_cn_gdp", "short", no_params=True),
    _endpoint(
        "get_alt_stk_factor",
        "hq_alt_stk_factor",
        "short",
        sample_code="000001.SZ",
    ),
    _endpoint("get_fund_adj_factor", "hq_fund_adj_factor", "short"),
    _endpoint("get_fut_holding", "hq_fut_holding", "short"),
    _endpoint("get_fut_wsr", "hq_fut_wsr", "short"),
    _endpoint("get_fx_daily", "hq_fx_daily", "short"),
    _endpoint(
        "get_hk_ccass_hold_detail_run",
        "hq_hk_ccass_hold_detail",
        "short",
        function=True,
    ),
    _endpoint("get_idx_daily_basic", "hq_idx_daily_basic", "short"),
    _endpoint("get_opt_daily", "hq_opt_daily", "short"),
    _endpoint("get_stk_bak_daily", "hq_stk_bak_daily", "short"),
    _endpoint(
        "get_stk_cyq_perf",
        "hq_stk_cyq_perf",
        "short",
        sample_code="000001.SZ",
    ),
    _endpoint("get_stk_kpl_concept", "hq_stk_kpl_concept", "short"),
    _endpoint("get_stk_kpl_concept_cons", "hq_stk_kpl_concept_cons", "short"),
    _endpoint("get_stk_kpl_list", "hq_stk_kpl_list", "short"),
    _endpoint("get_stk_limit_cpt_list", "hq_stk_limit_cpt_list", "short"),
    _endpoint(
        "get_ths_member",
        "hq_ths_member",
        "short",
        sample_code="883300.TI",
    ),
    _endpoint(
        "get_ths_member_all",
        "hq_ths_member_all",
        "short",
        sample_code="883300.TI",
    ),
    _endpoint(
        "get_idx_daily",
        "hq_idx_daily",
        "short",
        sample_code="000300.SH",
    ),
    _endpoint("get_stk_adj_factor", "hq_stk_adj_factor", "short"),
    _endpoint("get_alt_eco_cal", "hq_alt_eco_cal", "short"),
    _endpoint("get_cb_daily", "hq_cb_daily", "short"),
    _endpoint(
        "get_fund_daily",
        "hq_fund_daily",
        "short",
        sample_code="510300.SH",
    ),
    _endpoint("get_fund_share", "hq_fund_share", "short"),
    _endpoint("get_fut_daily", "hq_fut_daily", "short"),
    _endpoint("get_hk_daily", "hq_hk_daily", "short"),
    _endpoint("get_ref_topinst", "hq_ref_topinst", "short"),
    _endpoint("get_ref_toplist", "hq_ref_toplist", "short"),
    _endpoint("get_stk_daily_basic", "hq_stk_daily_basic", "short"),
    _endpoint("get_stk_limit_list_d", "hq_stk_limit_list_d", "short"),
    _endpoint("get_stk_moneyflow", "hq_stk_moneyflow", "short"),
    _endpoint(
        "get_ths_daily",
        "hq_ths_daily",
        "short",
        sample_code="883300.TI",
    ),
    # Expensive high-fanout endpoint: one representative stock, longer window.
    _endpoint(
        "get_stk_cyq_chips",
        "hq_stk_cyq_chips",
        "cyq",
        sample_code="000001.SZ",
    ),
    # Quarterly/annual data is deliberately run after the ordinary batch.
    _endpoint(
        "get_fin_balancesheet_vip_run",
        "hq_fin_balancesheet",
        "financial",
        function=True,
    ),
    _endpoint(
        "get_fin_cashflow_vip_run",
        "hq_fin_cashflow_all",
        "financial",
        function=True,
    ),
    _endpoint(
        "get_fin_income_all_vip_run",
        "hq_fin_income",
        "financial",
        function=True,
    ),
    _endpoint(
        "get_fin_income_daily",
        "hq_fin_income",
        "financial",
        sample_code="000001.SZ",
    ),
    _endpoint(
        "get_fund_portfolio",
        "hq_fund_portfolio",
        "financial",
        sample_code="001753.OF",
    ),
    # Not guaranteed by a 10,000-point account or not a valid current mapping.
    _endpoint("get_cb_1min", "hq_cb_1min", "excluded"),
    _endpoint("get_cb_5min", "hq_cb_5min", "excluded"),
    _endpoint("get_fund_1min", "hq_fund_1min", "excluded"),
    _endpoint("get_fut_1min", "hq_fut_1min", "excluded"),
    _endpoint("get_idx_1min", "hq_idx_1min", "excluded"),
    _endpoint("get_opt_1min", "hq_opt_1min", "excluded"),
    _endpoint("get_stk_1min", "hq_stk_1min", "excluded"),
    _endpoint("get_us_daily", "hq_us_daily", "excluded"),
    _endpoint("get_alt_cctv_news", "hq_alt_cctv_news", "excluded"),
    _endpoint("get_cb_daily_basic", "hq_cb_daily_basic", "excluded"),
    _endpoint("get_stk_limit_list", "hq_stk_limit_list", "excluded"),
)

ENDPOINT_BY_NAME = {str(item["name"]): item for item in ENDPOINTS}

FINANCIAL_SAMPLE_CLASSES = {
    "get_fin_balancesheet_vip_run": (
        "get_ph_data_from_ts.fin.Get_fin_balancesheet_vip",
        "get_fin_balancesheet_vip",
    ),
    "get_fin_cashflow_vip_run": (
        "get_ph_data_from_ts.fin.Get_fin_cashflow_vip",
        "get_fin_cashflow_vip",
    ),
    "get_fin_income_all_vip_run": (
        "get_ph_data_from_ts.fin.Get_fin_income_all_vip",
        "get_fin_income_all_vip",
    ),
}


def _redact(line: str) -> str:
    line = re.sub(
        r"([a-z][a-z0-9+.-]*://[^:/@\s]+:)[^@\s]+(@)",
        r"\1***\2",
        line,
        flags=re.IGNORECASE,
    )
    line = re.sub(
        r"(?i)(\b(?:token|password|passwd|api_key|access_token|secret)"
        r"\b[\"']?\s*[:=]\s*[\"']?)[^\"',;\s&]+",
        r"\1=***",
        line,
    )
    line = re.sub(
        r"(?i)(\bauthorization\b\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+",
        r"\1***",
        line,
    )
    line = re.sub(
        r"(?i)([?&](?:token|api_key|access_token|secret)=)[^&#\s]+",
        r"\1***",
        line,
    )
    return line


def _child_environment(
    original_root: Path,
    source: dict[str, str] | None = None,
) -> dict[str, str]:
    current = os.environ if source is None else source
    environment = {
        key: value for key, value in current.items() if key in CHILD_ENVIRONMENT_KEYS
    }
    environment["PYTHONPATH"] = str(original_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def _prior_result_is_resumable(prior: object) -> bool:
    if not isinstance(prior, dict):
        return False
    final_snapshot = prior.get("final_database_snapshot")
    return bool(
        prior.get("returncode") == 0
        and prior.get("saw_error") is False
        and prior.get("saw_warning") is False
        and isinstance(final_snapshot, dict)
        and final_snapshot.get("table_exists") is True
    )


def _load_original(original_root: Path):
    root = str(original_root.resolve())
    sys.path[:] = [item for item in sys.path if item != root]
    sys.path.insert(0, root)
    return importlib.import_module("主控程序.盘后__串行抓取接口列表")


def _db_snapshot(original_root: Path, table: str) -> dict[str, object]:
    _load_original(original_root)
    from basis import init_db  # type: ignore
    from sqlalchemy import text

    engine = init_db(False)
    try:
        with engine.connect() as connection:
            database = connection.execute(text("SELECT DATABASE()")).scalar()
            if database != "qtdb_pro":
                raise RuntimeError(f"expected qtdb_pro, got {database!r}")
            size = connection.execute(
                text(
                    "SELECT COALESCE(SUM(data_length + index_length), 0) "
                    "FROM information_schema.tables WHERE table_schema=:db"
                ),
                {"db": database},
            ).scalar()
            innodb_file_size = connection.execute(
                text(
                    "SELECT COALESCE(SUM(FILE_SIZE), 0) "
                    "FROM information_schema.INNODB_TABLESPACES "
                    "WHERE NAME LIKE :database_prefix"
                ),
                {"database_prefix": f"{database}/%"},
            ).scalar()
            table_row = connection.execute(
                text(
                    "SELECT table_rows, data_length + index_length AS bytes "
                    "FROM information_schema.tables "
                    "WHERE table_schema=:db AND table_name=:table"
                ),
                {"db": database, "table": table},
            ).first()
        return {
            "database": database,
            "database_bytes": max(int(size or 0), int(innodb_file_size or 0)),
            "information_schema_table_bytes": int(size or 0),
            "innodb_file_bytes": int(innodb_file_size or 0),
            "table": table,
            "table_exists": table_row is not None,
            "table_rows_estimate": (int(table_row[0] or 0) if table_row else None),
            "table_bytes": int(table_row[1] or 0) if table_row else None,
        }
    finally:
        engine.dispose()


def _run_child(args: argparse.Namespace) -> int:
    endpoint = ENDPOINT_BY_NAME[args.child]
    original_root = Path(args.original_root).resolve()
    before = _db_snapshot(original_root, str(endpoint["table"]))
    print("RUNNER_DB_BEFORE=" + json.dumps(before, ensure_ascii=False), flush=True)
    if int(before["database_bytes"]) >= MAX_DATABASE_BYTES:
        raise RuntimeError("qtdb_pro is already at or above the 5 GB limit")

    module = _load_original(original_root)
    from basis import _params, pd  # type: ignore

    target = getattr(module, str(endpoint["name"]))
    params = _params(str_date=args.start, end_date=args.end)
    print(
        "RUNNER_ENDPOINT="
        + json.dumps(
            {
                "name": endpoint["name"],
                "table": endpoint["table"],
                "group": endpoint["group"],
                "start": args.start,
                "end": args.end,
                "sample_code": endpoint["sample_code"],
                "sample_report_type": (
                    1 if args.child in FINANCIAL_SAMPLE_CLASSES else None
                ),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.child in FINANCIAL_SAMPLE_CLASSES:
        params.report_type = 1
        module_name, class_name = FINANCIAL_SAMPLE_CLASSES[args.child]
        sample_module = importlib.import_module(module_name)
        sample_class = getattr(sample_module, class_name)
        sample_class(params).run()
    elif endpoint["function"]:
        target(params)
    else:
        obj = target() if endpoint["no_params"] else target(params)
        sample_code = endpoint["sample_code"]
        if sample_code:
            obj.params.codelist = pd.DataFrame({"ts_code": [sample_code]})
            obj.params.code = sample_code
        obj.run()
    return 0


def _snapshot_command(args: argparse.Namespace) -> int:
    snapshot = _db_snapshot(Path(args.original_root), args.snapshot)
    print("RUNNER_SNAPSHOT=" + json.dumps(snapshot, ensure_ascii=False))
    return 0


def _result_path(report_dir: Path, endpoint_name: str) -> Path:
    return report_dir / "results" / f"{endpoint_name}.json"


def _read_final_snapshot(output: str) -> dict[str, object] | None:
    for line in reversed(output.splitlines()):
        if line.startswith("RUNNER_SNAPSHOT="):
            return json.loads(line.split("=", 1)[1])
    return None


def _run_parent(args: argparse.Namespace) -> int:
    original_root = Path(args.original_root).resolve()
    report_dir = Path(args.report_dir).resolve()
    logs_dir = report_dir / "logs"
    results_dir = report_dir / "results"
    logs_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(report_dir, 0o700)
    os.chmod(logs_dir, 0o700)
    os.chmod(results_dir, 0o700)

    selected = [item for item in ENDPOINTS if item["group"] == args.group]
    if args.only:
        requested = set(args.only)
        selected = [item for item in selected if item["name"] in requested]
        missing = requested - {str(item["name"]) for item in selected}
        if missing:
            raise SystemExit(f"not in group {args.group}: {sorted(missing)}")

    summary: list[dict[str, object]] = []
    failures = 0
    for position, endpoint in enumerate(selected, start=1):
        name = str(endpoint["name"])
        result_path = _result_path(report_dir, name)
        if args.resume and result_path.exists():
            prior = json.loads(result_path.read_text(encoding="utf-8"))
            if _prior_result_is_resumable(prior):
                print(f"[{position}/{len(selected)}] SKIP {name} (already complete)")
                summary.append(prior)
                continue
            print(
                f"[{position}/{len(selected)}] REVIEW {name} "
                "(prior result is not a warning-free complete result)",
                flush=True,
            )

        print(f"[{position}/{len(selected)}] START {name}", flush=True)
        log_path = logs_dir / f"{position:03d}_{name}.log"
        started = time.time()
        command = [
            sys.executable,
            "-B",
            "-u",
            str(Path(__file__).resolve()),
            "--child",
            name,
            "--original-root",
            str(original_root),
            "--start",
            args.start,
            "--end",
            args.end,
        ]
        environment = _child_environment(original_root)
        process = subprocess.Popen(
            command,
            cwd=original_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        saw_warning = False
        saw_error = False
        with log_path.open("w", encoding="utf-8") as log_handle:
            os.chmod(log_path, 0o600)
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = _redact(raw_line)
                log_handle.write(line)
                log_handle.flush()
                print(line, end="", flush=True)
                saw_warning = saw_warning or "| WARNING" in line
                saw_error = saw_error or any(
                    marker in line
                    for marker in ("| ERROR", "Traceback", "服务器返回错误")
                )
        returncode = process.wait()

        snapshot_process = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--snapshot",
                str(endpoint["table"]),
                "--original-root",
                str(original_root),
            ],
            cwd=original_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        final_snapshot = _read_final_snapshot(snapshot_process.stdout)
        if final_snapshot is None:
            saw_error = True
            print(
                f"[{position}/{len(selected)}] ERROR {name} "
                "(final database snapshot unavailable)",
                flush=True,
            )
        elif int(final_snapshot.get("database_bytes") or 0) >= MAX_DATABASE_BYTES:
            saw_error = True
            print(
                f"[{position}/{len(selected)}] ERROR {name} "
                "(database is at or above the 5 GB limit)",
                flush=True,
            )
        result = {
            "name": name,
            "table": endpoint["table"],
            "group": endpoint["group"],
            "start": args.start,
            "end": args.end,
            "sample_code": endpoint["sample_code"],
            "returncode": returncode,
            "saw_warning": saw_warning,
            "saw_error": saw_error,
            "duration_seconds": round(time.time() - started, 3),
            "log": str(log_path),
            "final_database_snapshot": final_snapshot,
        }
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(result_path, 0o600)
        summary.append(result)
        if returncode != 0 or saw_error:
            failures += 1
        print(
            f"[{position}/{len(selected)}] END {name} "
            f"rc={returncode} warning={saw_warning} error={saw_error}",
            flush=True,
        )

    summary_path = report_dir / f"summary_{args.group}.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(summary_path, 0o600)
    print(f"summary={summary_path} failures={failures}")
    return 1 if failures else 0


def _print_plan() -> int:
    counts: dict[str, int] = {}
    for endpoint in ENDPOINTS:
        group = str(endpoint["group"])
        counts[group] = counts.get(group, 0) + 1
        print(f"{group:10} {endpoint['name']:36} {endpoint['table']}")
    print("counts=" + json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-root", default=str(DEFAULT_ORIGINAL_ROOT))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--group", choices=("baseline", "short", "cyq", "financial"))
    parser.add_argument("--start", default="20260801")
    parser.add_argument("--end", default="20260812")
    parser.add_argument("--only", action="append")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--child", choices=tuple(ENDPOINT_BY_NAME))
    parser.add_argument("--snapshot")
    args = parser.parse_args()
    if args.plan:
        return _print_plan()
    if args.child:
        return _run_child(args)
    if args.snapshot:
        return _snapshot_command(args)
    if not args.group:
        parser.error("--group is required unless --plan/--child/--snapshot is used")
    return _run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
