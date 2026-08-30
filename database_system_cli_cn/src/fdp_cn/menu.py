"""Dependency-light Chinese-first terminal Menu for the CN product."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Callable

from fdp_cn.contracts import ProgressEvent
from fdp_cn.tushare.catalog import get_endpoint_spec
from fdp_cn.tushare.index_pit import IndexPitJob, IndexPitRequest
from fdp_cn.tushare.service import IngestPlan, IngestService, list_endpoints


Input = Callable[[str], str]
Output = Callable[[str], None]

TEXT = {
    "zh": {
        "title": "J21 database 数据菜单",
        "main": (
            "1. 查看全部接口",
            "2. 运行一个接口",
            "3. 按类别运行接口",
            "4. 初始化基础数据",
            "5. 按日期运行普通积分接口",
            "6. 切换为 English",
            "7. 指数历史与 PIT 向导",
            "0. 退出",
        ),
        "choice": "请选择: ",
        "endpoint": "请输入接口 key: ",
        "category": "请输入类别（如 stk、idx、fin）: ",
        "from": "开始日期 YYYY-MM-DD: ",
        "to": "结束日期 YYYY-MM-DD: ",
        "codes": "代码（逗号分隔，可留空）: ",
        "confirm": "确认真实调用 API 并写入 a_share？输入 y 执行，其他取消: ",
        "cancelled": "已取消，没有调用 API 或写数据库。",
        "invalid": "输入无效，请重试。",
        "plan": "执行计划",
        "done": "运行结束",
        "pit_phase": (
            "指数阶段 basic/classify/sw-daily/sw-members/sw-pit/style/general/all，"
            "或输入 resume: "
        ),
        "months": "完整自然月数量（默认 6）: ",
        "weight_range_mode": (
            "权重范围：1. 最近 N 个完整自然月（默认） "
            "2. 精确完整自然月日期范围: "
        ),
        "all_months": "完整自然月数量（默认 6；all 阶段仅支持最近 N 月）: ",
        "run_id": "断点 run_id: ",
        "max_calls": "本次 API attempts 上限（可留空）: ",
    },
    "en": {
        "title": "J21 database data menu",
        "main": (
            "1. List all endpoints",
            "2. Run one endpoint",
            "3. Run one category",
            "4. Initialize reference data",
            "5. Run standard-point endpoints by date",
            "6. 切换为简体中文",
            "7. Index history and PIT wizard",
            "0. Exit",
        ),
        "choice": "Choose: ",
        "endpoint": "Endpoint key: ",
        "category": "Category (for example stk, idx, fin): ",
        "from": "Start date YYYY-MM-DD: ",
        "to": "End date YYYY-MM-DD: ",
        "codes": "Codes (comma-separated, optional): ",
        "confirm": "Call the API and write a_share? Enter y to run; anything else cancels: ",
        "cancelled": "Cancelled; no API or database write was performed.",
        "invalid": "Invalid input; try again.",
        "plan": "Plan",
        "done": "Finished",
        "pit_phase": (
            "Phase basic/classify/sw-daily/sw-members/sw-pit/style/general/all, "
            "or resume: "
        ),
        "months": "Complete calendar months (default 6): ",
        "weight_range_mode": (
            "Weight range: 1. Recent N complete calendar months (default) "
            "2. Exact complete-calendar-month date range: "
        ),
        "all_months": (
            "Complete calendar months (default 6; all supports recent N months only): "
        ),
        "run_id": "Checkpoint run_id: ",
        "max_calls": "API attempt budget for this invocation (optional): ",
    },
}


class MenuProgressReporter:
    def __init__(self, output: Output) -> None:
        self._output = output

    def on_event(self, event: ProgressEvent) -> None:
        if event.message:
            self._output(event.message)

    def on_api_event(self, event: object) -> None:
        return None


def run_menu(
    *,
    language: str = "zh",
    service: IngestService | None = None,
    index_pit_job: IndexPitJob | None = None,
    input_func: Input = input,
    output: Output = print,
) -> int:
    """Run the Menu; Chinese is the default and execution confirms to No."""
    current = language if language in TEXT else "zh"
    active_service = service or IngestService()
    active_index_pit_job = index_pit_job or IndexPitJob()
    while True:
        labels = TEXT[current]
        output("")
        output(labels["title"])
        for line in labels["main"]:
            output(line)
        choice = input_func(labels["choice"]).strip()
        if choice == "0":
            return 0
        if choice == "6":
            current = "en" if current == "zh" else "zh"
            continue
        try:
            if choice == "1":
                _show_endpoints(output)
                continue
            if choice == "7":
                request = _index_pit_request(input_func, labels)
                dry_run = active_index_pit_job.run(request)
                _show_index_pit_plan(dry_run, output, labels["plan"])
                if input_func(labels["confirm"]).strip().casefold() != "y":
                    output(labels["cancelled"])
                    continue
                result = active_index_pit_job.run(
                    replace(request, execute=True),
                    reporter=MenuProgressReporter(output),
                )
                output(
                    f"{labels['done']}: status={result.status} "
                    f"run_id={result.run_id or '-'} "
                    f"units={result.work_units_completed}/{result.work_units_total} "
                    f"failed={result.work_units_failed}"
                )
                continue
            if choice == "2":
                plan = _single_plan(active_service, input_func, labels)
            elif choice == "3":
                category = input_func(str(labels["category"])).strip()
                start, end = _date_range(input_func, labels, optional=False)
                codes = _codes(input_func, labels)
                plan = active_service.plan_category(
                    category,
                    date_from=start,
                    date_to=end,
                    codes=codes,
                )
            elif choice == "4":
                start, end = _date_range(input_func, labels, optional=True)
                plan = active_service.plan_init(date_from=start, date_to=end)
            elif choice == "5":
                start, end = _date_range(input_func, labels, optional=False)
                codes = _codes(input_func, labels)
                plan = active_service.plan_all(
                    date_from=start,
                    date_to=end,
                    codes=codes,
                )
            else:
                output(labels["invalid"])
                continue
            _show_plan(plan, output, labels["plan"])
            if input_func(labels["confirm"]).strip().casefold() != "y":
                output(labels["cancelled"])
                continue
            result = active_service.run(
                plan,
                execute=True,
                confirmed=True,
                reporter=MenuProgressReporter(output),
            )
            output(
                f"{labels['done']}: status={result.status} "
                f"endpoints={result.endpoints_completed}/{result.endpoints_total} "
                f"failed={result.endpoints_failed}"
            )
        except (ValueError, RuntimeError) as error:
            output(f"{labels['invalid']} {error}")


def _single_plan(
    service: IngestService,
    input_func: Input,
    labels: dict[str, object],
) -> IngestPlan:
    endpoint = input_func(str(labels["endpoint"])).strip()
    spec = get_endpoint_spec(endpoint)
    today = date.today()
    if spec.scope_kind in {"date_range", "code_date_range"}:
        start, end = _date_range(input_func, labels, optional=False)
    else:
        start = end = today
    codes: tuple[str, ...] = ()
    if spec.scope_kind in {"code_list", "code_date_range"}:
        codes = _codes(input_func, labels)
    return service.plan_endpoint(
        endpoint,
        date_from=start,
        date_to=end,
        codes=codes,
    )


def _codes(
    input_func: Input,
    labels: dict[str, object],
) -> tuple[str, ...]:
    raw = input_func(str(labels["codes"]))
    return tuple(value.strip() for value in raw.split(",") if value.strip())


def _index_pit_request(
    input_func: Input,
    labels: dict[str, object],
) -> IndexPitRequest:
    phase = input_func(str(labels["pit_phase"])).strip().casefold()
    raw_max_calls = input_func(str(labels["max_calls"])).strip()
    max_calls = _optional_positive_int(raw_max_calls, label="API attempts")
    if phase == "resume":
        raw_run_id = input_func(str(labels["run_id"])).strip()
        return IndexPitRequest(
            resume_run_id=_required_positive_int(raw_run_id, label="run_id"),
            max_api_calls=max_calls,
            override_source="menu",
        )
    if phase not in {
        "basic",
        "classify",
        "sw-daily",
        "sw-members",
        "sw-pit",
        "style",
        "general",
        "all",
    }:
        raise ValueError("未知指数 PIT 阶段")
    date_from = date_to = None
    if phase in {"sw-daily", "sw-pit", "all"}:
        date_from, date_to = _optional_date_range(input_func, labels)
    months = None
    if phase in {"style", "general"}:
        range_mode = input_func(str(labels["weight_range_mode"])).strip().casefold()
        if range_mode in {"", "1", "months"}:
            raw_months = input_func(str(labels["months"])).strip()
            months = _optional_positive_int(raw_months, label="months") or 6
        elif range_mode in {"2", "exact"}:
            date_from, date_to = _optional_date_range(input_func, labels)
            if date_from is None or date_to is None:
                raise ValueError("精确范围必须同时填写开始和结束日期")
        else:
            raise ValueError("权重范围模式必须是 1 或 2")
    elif phase == "all":
        raw_months = input_func(str(labels["all_months"])).strip()
        months = _optional_positive_int(raw_months, label="months") or 6
    codes: tuple[str, ...] = ()
    if phase in {"style", "general", "all"}:
        raw_codes = input_func(str(labels["codes"])).strip()
        codes = tuple(value.strip() for value in raw_codes.split(",") if value.strip())
    return IndexPitRequest(
        phase=phase,  # type: ignore[arg-type]
        date_from=date_from,
        date_to=date_to,
        months=months,
        codes=codes,
        max_api_calls=max_calls,
        override_source="menu",
    )


def _date_range(
    input_func: Input,
    labels: dict[str, object],
    *,
    optional: bool,
) -> tuple[date, date]:
    today = date.today()
    raw_from = input_func(str(labels["from"])).strip()
    raw_to = input_func(str(labels["to"])).strip()
    if optional and not raw_from and not raw_to:
        return today, today
    if not raw_from or not raw_to:
        raise ValueError("起止日期必须同时填写")
    return _parse_date(raw_from), _parse_date(raw_to)


def _optional_date_range(
    input_func: Input,
    labels: dict[str, object],
) -> tuple[date | None, date | None]:
    raw_from = input_func(str(labels["from"])).strip()
    raw_to = input_func(str(labels["to"])).strip()
    if not raw_from and not raw_to:
        return None, None
    if not raw_from or not raw_to:
        raise ValueError("起止日期必须同时填写")
    return _parse_date(raw_from), _parse_date(raw_to)


def _optional_positive_int(value: str, *, label: str) -> int | None:
    if not value:
        return None
    return _required_positive_int(value, label=label)


def _required_positive_int(value: str, *, label: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"{label} 必须是正整数") from error
    if result <= 0:
        raise ValueError(f"{label} 必须是正整数")
    return result


def _parse_date(value: str) -> date:
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise ValueError("日期必须是 YYYY-MM-DD 或 YYYYMMDD")


def _show_endpoints(output: Output) -> None:
    rows = list_endpoints()
    for row in rows:
        enabled = "可运行" if row["enabled"] else "不可运行"
        points_tier = row["points_tier"] or "-"
        output(
            f"{row['key']} | {row['category']} | {row['table']} | "
            f"{row['backend']} | {row['access']} | points={points_tier} | {enabled}"
        )
    output(f"共 {len(rows)} 个接口")


def _show_plan(plan: IngestPlan, output: Output, title: object) -> None:
    output(
        f"{title}: mode={plan.mode} from={plan.date_from.isoformat()} "
        f"to={plan.date_to.isoformat()} endpoints={len(plan.items)}"
    )
    for item in plan.items:
        output(
            f"- {item.key} -> a_share.{item.table} "
            f"backend={item.backend} points={item.points_tier or '-'} "
            f"page_limit={item.page_limit or '-'}"
        )
    for warning in plan.warnings:
        output(f"! {warning}")


def _show_index_pit_plan(result: object, output: Output, title: object) -> None:
    preflight = getattr(result, "preflight", None)
    if preflight is None:
        raise ValueError("指数 PIT 没有生成执行计划")
    output(
        f"{title}: job={preflight.job} units={preflight.work_units} "
        f"estimated_api_calls={preflight.estimated_api_calls}"
    )
    for table in preflight.target_tables:
        output(f"- a_share.{table}")
    for warning in preflight.warnings:
        output(f"! {warning}")
