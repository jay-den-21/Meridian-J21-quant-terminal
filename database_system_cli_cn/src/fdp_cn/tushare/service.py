"""Shared command/Menu orchestration for direct and compatibility endpoints."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable, Literal, Mapping

from fdp_cn.contracts import (
    JobFailure,
    NullProgressReporter,
    ProgressEvent,
    ProgressKind,
    ProgressReporter,
)
from fdp_cn.tushare.bootstrap import ensure_control_schema
from fdp_cn.tushare.catalog import (
    CATALOG,
    catalog_summary,
    get_endpoint_spec,
    is_standard_points_eligible,
    standard_points_endpoint_specs,
)
from fdp_cn.tushare.errors import (
    TushareAuthenticationError,
    TushareCapabilityError,
    TushareStorageError,
    safe_error_message,
)
from fdp_cn.tushare.job import TushareEndpointJob, TushareJobRequest
from fdp_cn.tushare.legacy import LegacyEndpointRunner
from fdp_cn.tushare.models import EndpointSpec
from fdp_cn.tushare.runtime import TushareJobRuntime


Backend = Literal["direct", "legacy_compat"]
PlanMode = Literal["endpoint", "category", "init", "all"]
RequestedBackend = Literal["auto", "direct", "legacy"]

INIT_ENDPOINT_KEYS = (
    "trade_cal",
    "hk.hk_trade_cal",
    "us.us_tradecal",
    "stock_basic",
    "stock_basic_all",
    "cb.cb_basic",
    "fund.fund_basic",
    "fut.fut_basic",
    "hk.hk_basic",
    "idx.idx_basic",
    "index_classify",
    "ths_dc.ths_index",
    "opt.opt_basic",
    "us.us_basic",
    "fx.fx_obasic",
)


@dataclass(frozen=True)
class EndpointPlanItem:
    key: str
    category: str
    table: str
    api_name: str
    backend: Backend
    access: str
    points_tier: int | None
    page_limit: int | None
    description: str


@dataclass(frozen=True)
class IngestPlan:
    mode: PlanMode
    items: tuple[EndpointPlanItem, ...]
    date_from: date
    date_to: date
    codes: tuple[str, ...] = ()
    params: Mapping[str, object] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class BatchResult:
    status: str
    mode: str
    endpoints_total: int
    endpoints_completed: int
    endpoints_failed: int
    rows_fetched: int
    rows_cleaned: int
    rows_inserted: int
    rows_updated: int
    api_calls: int
    failures: tuple[JobFailure, ...]
    plan: IngestPlan

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "failures": [asdict(value) for value in self.failures],
            "plan": self.plan.to_dict(),
        }


class IngestService:
    """One orchestration owner used by CLI and Menu."""

    def __init__(
        self,
        *,
        direct_job: TushareEndpointJob | None = None,
        legacy_runner: LegacyEndpointRunner | None = None,
        runtime_factory: Callable[[], TushareJobRuntime] = TushareJobRuntime.from_env,
        control_initializer: Callable[[object], None] = ensure_control_schema,
    ) -> None:
        self._direct_job = direct_job or TushareEndpointJob()
        self._legacy_runner = legacy_runner or LegacyEndpointRunner()
        self._runtime_factory = runtime_factory
        self._control_initializer = control_initializer

    def plan_endpoint(
        self,
        endpoint: str,
        *,
        date_from: date,
        date_to: date,
        codes: tuple[str, ...] = (),
        params: Mapping[str, object] | None = None,
        backend: RequestedBackend = "auto",
    ) -> IngestPlan:
        spec = get_endpoint_spec(endpoint)
        item = _plan_item(spec, backend=backend)
        _validate_dates(date_from, date_to)
        _validate_required_scope(
            spec, date_from=date_from, date_to=date_to, codes=codes
        )
        return IngestPlan(
            mode="endpoint",
            items=(item,),
            date_from=date_from,
            date_to=date_to,
            codes=tuple(codes),
            params=dict(params or {}),
        )

    def plan_category(
        self,
        category: str,
        *,
        date_from: date,
        date_to: date,
        codes: tuple[str, ...] = (),
        params: Mapping[str, object] | None = None,
        include_separate: bool = False,
    ) -> IngestPlan:
        normalized = category.strip().casefold()
        specs = tuple(
            spec
            for spec in CATALOG
            if spec.category.casefold() == normalized
            and _default_batch_eligible(spec, include_separate=include_separate)
        )
        if not specs:
            raise ValueError(f"没有可运行的接口类别: {category}")
        return self._batch_plan(
            "category",
            specs,
            date_from=date_from,
            date_to=date_to,
            codes=codes,
            params=params,
        )

    def plan_init(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> IngestPlan:
        specs = tuple(get_endpoint_spec(key) for key in INIT_ENDPOINT_KEYS)
        return self._batch_plan(
            "init",
            specs,
            date_from=date_from,
            date_to=date_to,
            backend="legacy",
            warnings=(
                "init 使用保留的 getter 建立/刷新基础表；它不是 direct upsert。",
                "执行时同时建立 system_cn 断点和 API 记录表。",
            ),
        )

    def plan_all(
        self,
        *,
        date_from: date,
        date_to: date,
        codes: tuple[str, ...] = (),
    ) -> IngestPlan:
        specs = standard_points_endpoint_specs()
        return self._batch_plan(
            "all",
            specs,
            date_from=date_from,
            date_to=date_to,
            codes=codes,
            warnings=(
                "默认 all 排除实时、单独购买、废弃、当前账号无权限接口。",
                "尚未完成 direct 字段契约的接口使用隔离 legacy_compat 后端。",
            ),
        )

    def _batch_plan(
        self,
        mode: PlanMode,
        specs: tuple[EndpointSpec, ...],
        *,
        date_from: date,
        date_to: date,
        codes: tuple[str, ...] = (),
        params: Mapping[str, object] | None = None,
        backend: RequestedBackend = "auto",
        warnings: tuple[str, ...] = (),
    ) -> IngestPlan:
        _validate_dates(date_from, date_to)
        batch_params = dict(params or {})
        if batch_params:
            raise ValueError("--param 仅支持单接口模式，不能应用到批量接口")
        return IngestPlan(
            mode=mode,
            items=tuple(
                _plan_batch_item(spec, backend=backend, codes=codes) for spec in specs
            ),
            date_from=date_from,
            date_to=date_to,
            codes=tuple(codes),
            params=batch_params,
            warnings=warnings,
        )

    def run(
        self,
        plan: IngestPlan,
        *,
        execute: bool,
        confirmed: bool,
        reporter: ProgressReporter | None = None,
        max_retries: int | None = None,
        max_api_calls: int | None = None,
        timeout_seconds: int = 3600,
    ) -> BatchResult:
        if execute != confirmed:
            raise ValueError("真实执行必须同时提供 --execute 和 --yes")
        if not execute:
            return BatchResult(
                status="dry_run",
                mode=plan.mode,
                endpoints_total=len(plan.items),
                endpoints_completed=0,
                endpoints_failed=0,
                rows_fetched=0,
                rows_cleaned=0,
                rows_inserted=0,
                rows_updated=0,
                api_calls=0,
                failures=(),
                plan=plan,
            )
        active_reporter = reporter or NullProgressReporter()
        runtime: TushareJobRuntime | None = None
        if plan.mode == "init" or any(item.backend == "direct" for item in plan.items):
            runtime = self._runtime_factory()
            self._control_initializer(runtime.engine)

        completed = 0
        failures: list[JobFailure] = []
        failed_endpoints: set[str] = set()
        global_failure = False
        fetched = cleaned = inserted = updated = api_calls = 0
        _report(
            active_reporter, "start", 0, len(plan.items), message=f"mode={plan.mode}"
        )
        for item in plan.items:
            spec = get_endpoint_spec(item.key)
            endpoint_codes = _endpoint_codes(plan, spec)
            endpoint_params = _endpoint_params(plan)
            scope = _scope_message(plan, item, codes=endpoint_codes)
            _report(
                active_reporter,
                "unit_started",
                completed,
                len(plan.items),
                unit=item.key,
                message=scope,
            )
            if item.backend == "legacy_compat":
                try:
                    legacy = self._legacy_runner.run(
                        spec,
                        date_from=plan.date_from,
                        date_to=plan.date_to,
                        codes=endpoint_codes,
                        params=endpoint_params,
                        timeout_seconds=timeout_seconds,
                    )
                except Exception as error:
                    completed += 1
                    message = (
                        "兼容 getter 调度失败: "
                        f"{safe_error_message(error)}"
                    )
                    failures.append(JobFailure(item.key, "legacy_compat", message))
                    failed_endpoints.add(item.key)
                    _report(
                        active_reporter,
                        "unit_failed",
                        completed,
                        len(plan.items),
                        unit=item.key,
                        message=f"{scope} error={message}",
                    )
                    continue
                completed += 1
                if legacy.status != "success":
                    failures.append(
                        JobFailure(item.key, "legacy_compat", legacy.message)
                    )
                    failed_endpoints.add(item.key)
                    _report(
                        active_reporter,
                        "unit_failed",
                        completed,
                        len(plan.items),
                        unit=item.key,
                        message=f"{scope} error={legacy.message}",
                    )
                else:
                    _report(
                        active_reporter,
                        "unit_completed",
                        completed,
                        len(plan.items),
                        unit=item.key,
                        message=f"{scope} status=success",
                    )
                continue

            assert runtime is not None
            try:
                result = self._direct_job.run(
                    TushareJobRequest(
                        endpoint=item.key,
                        date_from=plan.date_from,
                        date_to=plan.date_to,
                        codes=endpoint_codes,
                        params=endpoint_params,
                        max_retries=max_retries,
                        max_api_calls=max_api_calls,
                        execute=True,
                        override_source="fdp_cn",
                    ),
                    runtime=runtime,
                    reporter=active_reporter,
                )
            except (TushareAuthenticationError, TushareStorageError) as error:
                message = safe_error_message(error)
                failures.append(JobFailure(item.key, error.kind, message))
                failed_endpoints.add(item.key)
                global_failure = True
                completed += 1
                _report(
                    active_reporter,
                    "unit_failed",
                    completed,
                    len(plan.items),
                    unit=item.key,
                    message=f"{scope} error={message}",
                )
                break
            except (TushareCapabilityError, ValueError) as error:
                completed += 1
                category = str(getattr(error, "kind", "parameter"))
                message = safe_error_message(error)
                failures.append(JobFailure(item.key, category, message))
                failed_endpoints.add(item.key)
                _report(
                    active_reporter,
                    "unit_failed",
                    completed,
                    len(plan.items),
                    unit=item.key,
                    message=f"{scope} error={message}",
                )
                continue
            completed += 1
            fetched += result.rows_fetched
            cleaned += result.rows_matched
            inserted += result.rows_inserted
            updated += int(result.metrics.get("rows_updated", 0))
            api_calls += result.api_calls
            if result.status not in {"success", "dry_run"}:
                failures.extend(result.failures)
                failed_endpoints.add(item.key)
                if _has_global_failure(result.failures):
                    global_failure = True
            _report(
                active_reporter,
                "unit_completed" if result.status == "success" else "unit_failed",
                completed,
                len(plan.items),
                unit=item.key,
                message=(
                    f"{scope} fetched={result.rows_fetched} cleaned={result.rows_matched} "
                    f"written={result.rows_inserted + int(result.metrics.get('rows_updated', 0))} "
                    f"attempts={result.api_calls} status={result.status}"
                ),
            )
            if global_failure:
                break

        failed = len(failed_endpoints)
        if global_failure:
            status = "failed"
        elif failed:
            status = "partial_failed"
        else:
            status = "success"
        _report(
            active_reporter,
            "finish",
            completed,
            len(plan.items),
            message=f"status={status} failed={failed}",
        )
        return BatchResult(
            status=status,
            mode=plan.mode,
            endpoints_total=len(plan.items),
            endpoints_completed=completed,
            endpoints_failed=failed,
            rows_fetched=fetched,
            rows_cleaned=cleaned,
            rows_inserted=inserted,
            rows_updated=updated,
            api_calls=api_calls,
            failures=tuple(failures),
            plan=plan,
        )


def list_endpoints() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for spec in CATALOG:
        rows.append(
            {
                **catalog_summary(spec),
                "backend": "direct" if spec.executable else "legacy_compat",
                "description": spec.description,
                "enabled": spec.capability.kind
                not in {"disabled_realtime", "disabled_unsupported"},
            }
        )
    return tuple(rows)


def _default_batch_eligible(spec: EndpointSpec, *, include_separate: bool) -> bool:
    if is_standard_points_eligible(spec):
        return True
    return (
        include_separate
        and spec.category != "realtime"
        and spec.capability.kind
        not in {"disabled_realtime", "disabled_unsupported"}
        and spec.access.kind == "separate_purchase"
    )


def _plan_batch_item(
    spec: EndpointSpec,
    *,
    backend: RequestedBackend,
    codes: tuple[str, ...],
) -> EndpointPlanItem:
    resolved_backend = backend
    if (
        backend == "auto"
        and spec.executable
        and spec.scope_kind == "code_date_range"
        and not codes
    ):
        resolved_backend = "legacy"
    return _plan_item(spec, backend=resolved_backend)


def _plan_item(spec: EndpointSpec, *, backend: RequestedBackend) -> EndpointPlanItem:
    if spec.capability.kind in {"disabled_realtime", "disabled_unsupported"}:
        reason = spec.capability.reason or "接口当前不可运行"
        raise ValueError(f"{spec.key} 当前不可运行: {reason}")
    if backend == "direct" and not spec.executable:
        raise ValueError(f"{spec.key} 尚未完成 direct 字段和写库契约")
    resolved: Backend
    if backend == "legacy":
        resolved = "legacy_compat"
    elif backend == "direct" or spec.executable:
        resolved = "direct"
    else:
        resolved = "legacy_compat"
    return EndpointPlanItem(
        key=spec.key,
        category=spec.category,
        table=spec.target_table,
        api_name=spec.api_name,
        backend=resolved,
        access=spec.access.kind,
        points_tier=spec.access.points_tier,
        page_limit=spec.page_limit,
        description=spec.description,
    )


def _validate_dates(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise ValueError("结束日期不能早于开始日期")


def _validate_required_scope(
    spec: EndpointSpec,
    *,
    date_from: date,
    date_to: date,
    codes: tuple[str, ...],
) -> None:
    _validate_dates(date_from, date_to)
    if spec.scope_kind == "code_date_range" and spec.executable and not codes:
        raise ValueError(f"{spec.key} 需要至少一个 --codes")


def _endpoint_codes(plan: IngestPlan, spec: EndpointSpec) -> tuple[str, ...]:
    if plan.mode == "endpoint" or spec.scope_kind in {
        "code_list",
        "code_date_range",
    }:
        return plan.codes
    return ()


def _endpoint_params(plan: IngestPlan) -> Mapping[str, object]:
    return plan.params if plan.mode == "endpoint" else {}


def _has_global_failure(failures: list[JobFailure]) -> bool:
    return any(
        failure.category
        in {"authentication", "storage", "storage_post_commit", "run_lease_cleanup"}
        for failure in failures
    )


def _scope_message(
    plan: IngestPlan,
    item: EndpointPlanItem,
    *,
    codes: tuple[str, ...],
) -> str:
    code_scope = ",".join(codes) if codes else "-"
    return (
        f"endpoint={item.key} table=a_share.{item.table} backend={item.backend} "
        f"code={code_scope} from={plan.date_from.isoformat()} "
        f"to={plan.date_to.isoformat()} "
        "offset=0"
    )


def _report(
    reporter: ProgressReporter,
    kind: ProgressKind,
    completed: int,
    total: int,
    *,
    unit: str | None = None,
    message: str | None = None,
) -> None:
    try:
        reporter.on_event(
            ProgressEvent(
                kind=kind,
                job="ingest.cn_tushare",
                completed=completed,
                total=total,
                unit=unit,
                message=message,
            )
        )
    except Exception:
        return
