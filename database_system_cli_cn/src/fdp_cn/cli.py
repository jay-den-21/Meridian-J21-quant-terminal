"""Project-local j21 command for Chinese Tushare ingestion."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import sys
from typing import Mapping, Sequence, TextIO

from fdp_cn.contracts import JobResult, ProgressEvent
from fdp_cn.menu import run_menu
from fdp_cn.tushare.errors import TushareError, safe_error_message
from fdp_cn.tushare.index_pit import IndexPitJob, IndexPitRequest
from fdp_cn.tushare.service import BatchResult, IngestService, list_endpoints


class LineProgressReporter:
    """Stable one-line progress for terminals and redirected logs."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def on_event(self, event: ProgressEvent) -> None:
        if event.message:
            print(event.message, file=self._stream, flush=True)

    def on_api_event(self, event: object) -> None:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="j21",
        description="J21 database：中文优先的 Tushare 数据工具",
    )
    parser.add_argument("--lang", choices=("zh", "en"), default="zh", help="界面语言")
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser("ingest", help="抓取并写入 A 股数据")
    ingest_commands = ingest.add_subparsers(dest="ingest_command", required=True)

    listing = ingest_commands.add_parser("list", help="查看全部 93 个接口")
    listing.add_argument("--category", help="仅显示一个类别")
    listing.add_argument("--output", choices=("text", "json"), default="text")

    tushare = ingest_commands.add_parser("tushare", help="运行单接口或单类别")
    selector = tushare.add_mutually_exclusive_group(required=True)
    selector.add_argument("--endpoint", help="接口 key 或 getter 别名")
    selector.add_argument("--category", help="接口类别")
    selector.add_argument("--all", action="store_true", help="等价于 ingest all")
    _add_run_options(tushare, dates_required=False)
    tushare.add_argument(
        "--backend",
        choices=("auto", "direct", "legacy"),
        default="auto",
        help="auto 优先使用 direct，未迁移接口使用 legacy",
    )
    tushare.add_argument(
        "--include-separate",
        action="store_true",
        help="类别模式中包含单独购买权限的接口",
    )

    init = ingest_commands.add_parser("init", help="初始化基础/依赖表和 CN 运行记录表")
    _add_run_options(init, dates_required=False)

    all_command = ingest_commands.add_parser(
        "all",
        help="按安全顺序运行普通积分历史接口",
    )
    _add_run_options(all_command, dates_required=True)

    index_pit = ingest_commands.add_parser(
        "index-pit",
        help="刷新指数来源并构建申万/风格/普通指数 PIT",
    )
    index_pit_selector = index_pit.add_mutually_exclusive_group(required=True)
    index_pit_selector.add_argument(
        "--phase",
        choices=(
            "basic",
            "classify",
            "sw-daily",
            "sw-members",
            "sw-pit",
            "style",
            "general",
            "all",
        ),
        help="执行一个新阶段",
    )
    index_pit_selector.add_argument(
        "--resume-run-id",
        type=_positive_int,
        help="从 system_cn 中的断点继续",
    )
    index_pit.add_argument("--from", dest="date_from", help="开始日期")
    index_pit.add_argument("--to", dest="date_to", help="结束日期")
    index_pit.add_argument(
        "--months",
        type=_positive_int,
        help="风格/普通指数的完整自然月数量；烟测建议 6，扩展建议 60",
    )
    index_pit.add_argument("--codes", default="", help="逗号分隔的指数代码")
    index_pit.add_argument(
        "--max-retries", type=int, default=None, help="失败后的重试次数"
    )
    index_pit.add_argument(
        "--max-api-calls",
        type=_positive_int,
        default=None,
        help="本次运行最多消耗的 API attempts",
    )
    index_pit.add_argument("--execute", action="store_true", help="执行 API 和数据库写入")
    index_pit.add_argument(
        "--yes", action="store_true", help="确认真实执行；必须与 --execute 同用"
    )
    index_pit.add_argument("--output", choices=("text", "json"), default="text")

    menu = subcommands.add_parser("menu", help="打开中文交互菜单")
    menu.add_argument("--language", choices=("zh", "en"), default=None)
    return parser


def _add_run_options(parser: argparse.ArgumentParser, *, dates_required: bool) -> None:
    parser.add_argument(
        "--from", dest="date_from", required=dates_required, help="开始日期"
    )
    parser.add_argument(
        "--to", dest="date_to", required=dates_required, help="结束日期"
    )
    parser.add_argument("--codes", default="", help="逗号分隔的股票/指数代码")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="可重复的 KEY=VALUE 接口参数",
    )
    parser.add_argument(
        "--max-retries", type=int, default=None, help="失败后的重试次数"
    )
    parser.add_argument(
        "--max-api-calls",
        type=int,
        default=None,
        help="direct 后端本次 API attempt 上限",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=3600,
        help="每个 legacy 子进程最长运行秒数",
    )
    parser.add_argument("--execute", action="store_true", help="执行 API 和数据库写入")
    parser.add_argument(
        "--yes", action="store_true", help="确认真实执行；必须与 --execute 同用"
    )
    parser.add_argument("--output", choices=("text", "json"), default="text")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "menu":
        return run_menu(language=args.language or args.lang)
    if args.ingest_command == "list":
        return _list_command(args)
    if args.ingest_command == "index-pit":
        return _index_pit_command(args)

    service = IngestService()
    try:
        plan = _build_plan(args, service)
        reporter_stream = sys.stderr if args.output == "json" else sys.stdout
        result = service.run(
            plan,
            execute=args.execute,
            confirmed=args.yes,
            reporter=LineProgressReporter(reporter_stream),
            max_retries=args.max_retries,
            max_api_calls=args.max_api_calls,
            timeout_seconds=args.timeout_seconds,
        )
    except (ValueError, TushareError) as error:
        message = (
            safe_error_message(error) if isinstance(error, TushareError) else str(error)
        )
        print(f"错误: {message}", file=sys.stderr)
        return 2
    _emit_result(result, output=args.output)
    return 0 if result.status in {"dry_run", "success"} else 2


def _list_command(args: argparse.Namespace) -> int:
    rows = tuple(
        row
        for row in list_endpoints()
        if not args.category or row["category"].casefold() == args.category.casefold()
    )
    if args.output == "json":
        print(json.dumps(rows, ensure_ascii=False, default=str))
        return 0
    print("接口 key | 类别 | API | 目标表 | 后端 | 权限 | 积分档位 | 状态 | 单页上限")
    for row in rows:
        state = "可运行" if row["enabled"] else "不可运行"
        points_tier = row["points_tier"] or "-"
        print(
            f"{row['key']} | {row['category']} | {row['api_name']} | {row['table']} | "
            f"{row['backend']} | {row['access']} | {points_tier} | {state} | "
            f"{row['page_limit'] or '-'}"
        )
    print(f"共 {len(rows)} 个接口")
    return 0


def _build_plan(args: argparse.Namespace, service: IngestService):
    today = date.today()
    date_from = _parse_date(args.date_from, name="--from") if args.date_from else today
    date_to = _parse_date(args.date_to, name="--to") if args.date_to else today
    if (args.date_from is None) != (args.date_to is None):
        raise ValueError("--from 和 --to 必须同时提供")
    codes = tuple(value.strip() for value in args.codes.split(",") if value.strip())
    params = _parse_params(args.param)
    if args.ingest_command == "init":
        if params:
            raise ValueError("--param 仅支持单接口模式")
        return service.plan_init(date_from=date_from, date_to=date_to)
    if args.ingest_command == "all" or getattr(args, "all", False):
        if params:
            raise ValueError("--param 仅支持单接口模式")
        return service.plan_all(date_from=date_from, date_to=date_to, codes=codes)
    if args.endpoint:
        return service.plan_endpoint(
            args.endpoint,
            date_from=date_from,
            date_to=date_to,
            codes=codes,
            params=params,
            backend=args.backend,
        )
    return service.plan_category(
        args.category,
        date_from=date_from,
        date_to=date_to,
        codes=codes,
        params=params,
        include_separate=args.include_separate,
    )


def _parse_date(value: str, *, name: str) -> date:
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise ValueError(f"{name} 必须是 YYYY-MM-DD 或 YYYYMMDD")


def _positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("必须是正整数") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return result


def _index_pit_command(args: argparse.Namespace) -> int:
    try:
        if args.execute != args.yes:
            raise ValueError("真实执行必须同时提供 --execute 和 --yes")
        if (args.date_from is None) != (args.date_to is None):
            raise ValueError("--from 和 --to 必须同时提供")
        date_from = (
            _parse_date(args.date_from, name="--from") if args.date_from else None
        )
        date_to = _parse_date(args.date_to, name="--to") if args.date_to else None
        request = IndexPitRequest(
            phase=args.phase,
            date_from=date_from,
            date_to=date_to,
            months=args.months,
            codes=tuple(
                value.strip() for value in args.codes.split(",") if value.strip()
            ),
            resume_run_id=args.resume_run_id,
            max_retries=args.max_retries,
            max_api_calls=args.max_api_calls,
            execute=args.execute,
            override_source="cli",
        )
        reporter_stream = sys.stderr if args.output == "json" else sys.stdout
        result = IndexPitJob().run(
            request,
            reporter=LineProgressReporter(reporter_stream),
        )
    except (ValueError, TushareError) as error:
        message = (
            safe_error_message(error) if isinstance(error, TushareError) else str(error)
        )
        print(f"错误: {message}", file=sys.stderr)
        return 2
    _emit_index_pit_result(result, output=args.output)
    return 0 if result.status in {"dry_run", "success"} else 2


def _parse_params(values: Sequence[str]) -> Mapping[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, raw = value.partition("=")
        key = key.strip()
        raw = raw.strip()
        if not separator or not key or not raw:
            raise ValueError("--param 必须使用非空 KEY=VALUE")
        if key in result:
            raise ValueError(f"重复参数: {key}")
        result[key] = raw
    return result


def _emit_result(result: BatchResult, *, output: str) -> None:
    if output == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, default=str))
        return
    print(
        f"结果: status={result.status} mode={result.mode} "
        f"endpoints={result.endpoints_completed}/{result.endpoints_total} "
        f"failed={result.endpoints_failed} fetched={result.rows_fetched} "
        f"cleaned={result.rows_cleaned} inserted={result.rows_inserted} "
        f"updated={result.rows_updated} api_calls={result.api_calls}"
    )
    for failure in result.failures:
        print(f"失败: {failure.unit} [{failure.category}] {failure.message}")


def _emit_index_pit_result(result: JobResult, *, output: str) -> None:
    if output == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, default=str))
        return
    print(
        f"结果: status={result.status} run_id={result.run_id or '-'} "
        f"units={result.work_units_completed}/{result.work_units_total} "
        f"failed={result.work_units_failed} fetched={result.rows_fetched} "
        f"cleaned={result.rows_matched} written={result.rows_inserted} "
        f"updated={result.metrics.get('rows_updated', 0)} api_calls={result.api_calls}"
    )
    if result.error_message:
        print(f"错误: {result.error_message}")
    for failure in result.failures:
        print(f"失败: {failure.unit} [{failure.category}] {failure.message}")


if __name__ == "__main__":
    raise SystemExit(main())
