"""Resumable source refresh and PIT jobs for index membership history."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Mapping, Sequence

from sqlalchemy import select, text, update
from sqlalchemy.engine import Engine

from fdp_cn.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
)
from fdp_cn.tushare.bootstrap import ensure_control_schema
from fdp_cn.tushare.cleaning import clean_page
from fdp_cn.tushare.errors import (
    TushareAuthenticationError,
    TushareDataError,
    TushareError,
    TushareNoDataError,
    TusharePermissionError,
    TushareRateLimitError,
    TushareRunLeaseCleanupError,
    TushareStorageError,
    TushareTransportError,
    safe_error_message,
)
from fdp_cn.tushare.index_pit_specs import (
    INDEX_BASIC_SPEC,
    INDEX_CLASSIFY_SPEC,
    INDEX_MEMBER_ALL_SPEC,
    INDEX_MEMBER_SPEC,
    INDEX_WEIGHT_SPEC,
    SW_DAILY_SPEC,
)
from fdp_cn.tushare.index_pit_storage import (
    GENERAL_PIT_TABLE,
    STYLE_PIT_TABLE,
    SW_PIT_STAGE_TABLE,
    SW_PIT_TABLE,
    IndexMetadata,
    clear_weight_stage,
    ensure_index_pit_tables,
    ensure_source_unique_keys,
    index_pit_page_transaction,
    insert_sw_pit_partition,
    load_index_metadata,
    load_sw_codes,
    prepare_sw_pit_staging,
    publish_weight_unit,
    swap_sw_pit_staging,
    sw_pit_workflow_lease,
    sw_pit_table_state,
    upsert_weight_stage,
    validate_sw_pit_staging,
    validate_sw_pit_final,
    weight_unit_metrics,
)
from fdp_cn.tushare.models import EndpointSpec, EndpointUnit, TushareResponse
from fdp_cn.tushare.planning import next_page_offset
from fdp_cn.tushare.runtime import TushareJobRuntime
from fdp_cn.tushare.storage import (
    external_table_page_transaction,
    tushare_run_lease,
    verify_external_table,
    write_business_rows,
)
from fdp_cn.tushare.system_tables import api_call_log, ingestion_task_run


IndexPitPhase = Literal[
    "basic",
    "classify",
    "sw-daily",
    "sw-members",
    "sw-pit",
    "style",
    "general",
    "all",
]
_PHASES = frozenset(
    {"basic", "classify", "sw-daily", "sw-members", "sw-pit", "style", "general", "all"}
)
_CHECKPOINT_VERSION = 1
_JOB_KEY = "ingest.index_pit"
_JOB_MODULE = "fdp_cn.tushare.index_pit"
_SW_DAILY_START = date(2013, 1, 1)
_SW2014_START = date(2014, 2, 21)
_SW2014_END = date(2021, 12, 10)
_SW2021_START = date(2021, 12, 13)
_SW_PIT_COLUMNS = (
    ("trade_date", "date", "NO"),
    ("industry_version", "varchar(8)", "NO"),
    ("level", "varchar(2)", "NO"),
    ("index_code", "varchar(20)", "NO"),
    ("con_code", "varchar(20)", "NO"),
    ("in_date", "date", "NO"),
    ("out_date", "date", "YES"),
    ("is_new", "varchar(2)", "NO"),
    ("source_endpoint", "varchar(32)", "NO"),
)
_SW_PIT_PRIMARY_KEY = (
    "trade_date",
    "industry_version",
    "level",
    "index_code",
    "con_code",
)
_PROVIDER_SPECS = {
    spec.key: spec
    for spec in (
        INDEX_BASIC_SPEC,
        INDEX_CLASSIFY_SPEC,
        SW_DAILY_SPEC,
        INDEX_MEMBER_SPEC,
        INDEX_MEMBER_ALL_SPEC,
        INDEX_WEIGHT_SPEC,
    )
}


@dataclass(frozen=True)
class IndexPitRequest:
    """UI-neutral request for one index source/PIT phase or one resume."""

    phase: IndexPitPhase | None = None
    date_from: date | None = None
    date_to: date | None = None
    months: int | None = None
    codes: tuple[str, ...] = ()
    resume_run_id: int | None = None
    max_retries: int | None = None
    max_api_calls: int | None = None
    execute: bool = False
    override_source: str = "python"

    def __post_init__(self) -> None:
        object.__setattr__(self, "codes", _normalize_codes(self.codes))
        if (self.phase is None) == (self.resume_run_id is None):
            raise ValueError("choose exactly one phase or resume_run_id")
        if self.phase is not None and self.phase not in _PHASES:
            raise ValueError(f"unsupported index PIT phase: {self.phase}")
        if self.resume_run_id is not None:
            if self.resume_run_id <= 0:
                raise ValueError("resume_run_id must be positive")
            if self.date_from or self.date_to or self.months or self.codes:
                raise ValueError("resume restores dates, months, and codes from checkpoint")
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("date_from and date_to must be supplied together")
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise ValueError("date_to must not be before date_from")
        if self.months is not None and (
            isinstance(self.months, bool) or self.months <= 0
        ):
            raise ValueError("months must be a positive integer")
        if (
            self.phase in {"style", "general"}
            and self.months is not None
            and self.date_from is not None
        ):
            raise ValueError("weight phases accept either months or an exact date range")
        if self.max_retries is not None and (
            isinstance(self.max_retries, bool) or self.max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if self.max_api_calls is not None and (
            isinstance(self.max_api_calls, bool) or self.max_api_calls <= 0
        ):
            raise ValueError("max_api_calls must be a positive integer")
        if self.phase == "general" and not self.codes:
            raise ValueError("general phase requires at least one index code")


@dataclass(frozen=True)
class _WeightUnit:
    unit_key: str
    table_name: str
    metadata: IndexMetadata
    month_start: date
    month_end: date

    def endpoint_unit(self) -> EndpointUnit:
        return EndpointUnit(
            endpoint_key=INDEX_WEIGHT_SPEC.key,
            scope_key=self.unit_key,
            params={
                "index_code": self.metadata.index_code,
                "start_date": self.month_start.strftime("%Y%m%d"),
                "end_date": self.month_end.strftime("%Y%m%d"),
            },
            page_limit=INDEX_WEIGHT_SPEC.page_limit or 5_000,
        )


class IndexPitJob:
    """One Job shared by CLI/Menu for source, SW PIT, and monthly weight phases."""

    job_key = _JOB_KEY
    job_module = _JOB_MODULE

    def preflight(
        self,
        request: IndexPitRequest,
        *,
        runtime: TushareJobRuntime | None = None,
    ) -> JobPreflight:
        if request.resume_run_id is not None:
            active_runtime = runtime or TushareJobRuntime.from_env()
            checkpoint = _load_checkpoint(active_runtime.engine, request.resume_run_id)
            return _preflight_from_checkpoint(checkpoint)
        assert request.phase is not None
        if request.phase == "all":
            return self._all_preflight(request, runtime=runtime)
        if request.phase in {"basic", "classify", "sw-daily", "sw-members"}:
            units = _provider_units(request, runtime=runtime)
            specs = _unique_specs(units)
            return _provider_preflight(request, units, specs)
        if request.phase == "sw-pit":
            units = _sw_pit_units(request)
            parameters = _request_parameters(request)
            return JobPreflight(
                job=_JOB_KEY,
                job_module=_JOB_MODULE,
                target_tables=[SW_PIT_TABLE],
                work_units=len(units),
                estimated_api_calls=0,
                estimated_rows=None,
                estimated_gb=None,
                parameters=parameters,
                parameter_sources={key: request.override_source for key in parameters},
                warnings=[
                    "out_date is inclusive; SW2014 ends 2021-12-10 and SW2021 starts 2021-12-13",
                    "the validated staging table is published with one atomic RENAME TABLE",
                ],
            )
        units = _weight_units(request, runtime=runtime)
        parameters = _request_parameters(request)
        return JobPreflight(
            job=_JOB_KEY,
            job_module=_JOB_MODULE,
            target_tables=sorted({unit.table_name for unit in units}),
            work_units=len(units),
            estimated_api_calls=len(units),
            parameters=parameters,
            parameter_sources={key: request.override_source for key in parameters},
            warnings=[
                "index_weight is a monthly snapshot; provider trade_date is preserved",
                "official documentation recommends one natural month per request but does not publish a numeric page cap",
                "index metadata is current metadata from hq_idx_basic, not historical PIT metadata",
            ],
        )

    def run(
        self,
        request: IndexPitRequest,
        *,
        runtime: TushareJobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        preflight: JobPreflight | None = None,
    ) -> JobResult:
        active_runtime = runtime or TushareJobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()
        active_preflight = preflight or self.preflight(request, runtime=active_runtime)
        if not request.execute:
            return _dry_run(request, active_preflight)
        ensure_control_schema(active_runtime.engine)
        if request.resume_run_id is not None:
            return self._resume(
                request,
                runtime=active_runtime,
                reporter=active_reporter,
                preflight=active_preflight,
            )
        assert request.phase is not None
        if request.phase == "all":
            return self._run_all(request, active_runtime, active_reporter, active_preflight)
        if request.phase in {"basic", "classify", "sw-daily", "sw-members"}:
            return _run_provider_new(
                request,
                runtime=active_runtime,
                reporter=active_reporter,
                preflight=active_preflight,
            )
        if request.phase == "sw-pit":
            return _run_sw_pit_new(
                request,
                runtime=active_runtime,
                reporter=active_reporter,
                preflight=active_preflight,
            )
        return _run_weight_new(
            request,
            runtime=active_runtime,
            reporter=active_reporter,
            preflight=active_preflight,
        )

    def _resume(
        self,
        request: IndexPitRequest,
        *,
        runtime: TushareJobRuntime,
        reporter: ProgressReporter,
        preflight: JobPreflight,
    ) -> JobResult:
        assert request.resume_run_id is not None
        checkpoint = _load_checkpoint(runtime.engine, request.resume_run_id)
        kind = str(checkpoint.get("kind", ""))
        if kind == "provider":
            return _run_provider_checkpoint(
                request,
                runtime=runtime,
                reporter=reporter,
                preflight=preflight,
                run_id=request.resume_run_id,
                checkpoint=checkpoint,
            )
        if kind == "sw_pit":
            return _run_sw_pit_checkpoint(
                request,
                runtime=runtime,
                reporter=reporter,
                preflight=preflight,
                run_id=request.resume_run_id,
                checkpoint=checkpoint,
            )
        if kind == "weight":
            return _run_weight_checkpoint(
                request,
                runtime=runtime,
                reporter=reporter,
                preflight=preflight,
                run_id=request.resume_run_id,
                checkpoint=checkpoint,
            )
        raise TushareStorageError("run_id is not an index PIT run")

    def _all_preflight(
        self,
        request: IndexPitRequest,
        *,
        runtime: TushareJobRuntime | None,
    ) -> JobPreflight:
        active_runtime = runtime or TushareJobRuntime.from_env()
        phases = _all_phase_requests(request)
        plans = [self.preflight(phase, runtime=active_runtime) for phase in phases]
        parameters = _request_parameters(request)
        return JobPreflight(
            job=_JOB_KEY,
            job_module=_JOB_MODULE,
            target_tables=sorted(
                {table for plan in plans for table in plan.target_tables}
            ),
            work_units=sum(plan.work_units for plan in plans),
            estimated_api_calls=sum(plan.estimated_api_calls for plan in plans),
            parameters=parameters,
            parameter_sources={key: request.override_source for key in parameters},
            warnings=[
                "all runs independent resumable phase runs in dependency order",
                *(
                    []
                    if request.codes
                    else ["general index weights are skipped because no explicit codes were supplied"]
                ),
            ],
        )

    def _run_all(
        self,
        request: IndexPitRequest,
        runtime: TushareJobRuntime,
        reporter: ProgressReporter,
        preflight: JobPreflight,
    ) -> JobResult:
        results: list[JobResult] = []
        failures: list[JobFailure] = []
        exception_failures = 0
        fatal_error: str | None = None
        remaining_calls = request.max_api_calls
        phase_requests = _all_phase_requests(request)
        for phase_request in phase_requests:
            phase_uses_api = phase_request.phase != "sw-pit"
            if phase_uses_api and remaining_calls is not None and remaining_calls <= 0:
                fatal_error = "max_api_calls reached before the next phase"
                failures.append(
                    JobFailure(
                        phase_request.phase or "unknown",
                        "api_budget",
                        fatal_error,
                    )
                )
                exception_failures += 1
                break
            effective_request = replace(
                phase_request,
                execute=True,
                max_api_calls=(remaining_calls if phase_uses_api else None),
            )
            try:
                result = self.run(
                    effective_request,
                    runtime=runtime,
                    reporter=reporter,
                )
            except (TushareError, ValueError) as error:
                failure = JobFailure(
                    phase_request.phase or "unknown",
                    getattr(error, "kind", "phase"),
                    safe_error_message(error),
                )
                failures.append(failure)
                exception_failures += 1
                fatal_error = failure.message
                break
            except Exception as error:
                failure = JobFailure(
                    phase_request.phase or "unknown",
                    "unexpected",
                    safe_error_message(error),
                )
                failures.append(failure)
                exception_failures += 1
                fatal_error = failure.message
                break
            results.append(result)
            failures.extend(result.failures)
            if remaining_calls is not None:
                remaining_calls = max(0, remaining_calls - result.api_calls)
            if result.status == "failed" or result.error_message:
                fatal_error = result.error_message or (
                    result.failures[0].message
                    if result.failures
                    else f"phase {phase_request.phase} failed"
                )
                if result.work_units_failed == 0:
                    exception_failures += 1
                if not result.failures:
                    failures.append(
                        JobFailure(
                            phase_request.phase or "unknown",
                            "phase",
                            fatal_error,
                        )
                    )
                break
        completed = sum(result.work_units_completed for result in results)
        failed = sum(result.work_units_failed for result in results)
        all_phases_completed = len(results) == len(phase_requests)
        if all_phases_completed and all(result.status == "success" for result in results):
            status = "success"
        elif completed or any(
            result.status in {"success", "partial_failed"} for result in results
        ):
            status = "partial_failed"
        else:
            status = "failed"
        return JobResult(
            job=_JOB_KEY,
            status=status,
            run_id=None,
            parameters=preflight.parameters,
            parameter_sources=preflight.parameter_sources,
            rows_fetched=sum(result.rows_fetched for result in results),
            rows_matched=sum(result.rows_matched for result in results),
            rows_inserted=sum(result.rows_inserted for result in results),
            rows_rejected=sum(result.rows_rejected for result in results),
            api_calls=sum(result.api_calls for result in results),
            work_units_total=preflight.work_units,
            work_units_completed=completed,
            work_units_failed=failed + exception_failures,
            failures=failures,
            metrics={
                "phase_run_ids": {
                    str(result.parameters.get("phase")): result.run_id
                    for result in results
                },
                "rows_updated": sum(
                    int(result.metrics.get("rows_updated", 0)) for result in results
                ),
                "remaining_api_calls": remaining_calls,
            },
            error_message=fatal_error,
            preflight=preflight,
        )


def _provider_units(
    request: IndexPitRequest,
    *,
    runtime: TushareJobRuntime | None,
) -> tuple[EndpointUnit, ...]:
    phase = request.phase
    if phase == "basic":
        return (_unit(INDEX_BASIC_SPEC, "all", {}),)
    if phase == "classify":
        return tuple(
            _unit(
                INDEX_CLASSIFY_SPEC,
                f"src={src},level={level}",
                {"src": src, "level": level},
            )
            for src in ("SW2014", "SW2021")
            for level in ("L1", "L2", "L3")
        )
    if phase == "sw-daily":
        start, end = _resolved_dates(request, default_from=_SW_DAILY_START)
        return tuple(
            _unit(
                SW_DAILY_SPEC,
                f"{month_start:%Y%m%d}..{month_end:%Y%m%d}",
                {
                    "start_date": month_start.strftime("%Y%m%d"),
                    "end_date": month_end.strftime("%Y%m%d"),
                },
            )
            for month_start, month_end in _month_windows(start, end)
        )
    if phase != "sw-members":
        raise ValueError(f"phase {phase} is not a provider source phase")
    active_runtime = runtime or TushareJobRuntime.from_env()
    codes = load_sw_codes(active_runtime.engine)
    units: list[EndpointUnit] = []
    for src, code in codes:
        spec = INDEX_MEMBER_SPEC if src == "SW2014" else INDEX_MEMBER_ALL_SPEC
        parameter_name = "index_code" if src == "SW2014" else "l1_code"
        for is_new in ("N", "Y"):
            units.append(
                _unit(
                    spec,
                    f"src={src},{parameter_name}={code},is_new={is_new}",
                    {parameter_name: code, "is_new": is_new},
                )
            )
    return tuple(units)


def _provider_preflight(
    request: IndexPitRequest,
    units: tuple[EndpointUnit, ...],
    specs: tuple[EndpointSpec, ...],
) -> JobPreflight:
    parameters = _request_parameters(request)
    return JobPreflight(
        job=_JOB_KEY,
        job_module=_JOB_MODULE,
        target_tables=sorted({spec.target_table for spec in specs}),
        work_units=len(units),
        estimated_api_calls=len(units),
        parameters=parameters,
        parameter_sources={key: request.override_source for key in parameters},
        warnings=[
            "full pages continue by offset; the estimate is a lower bound",
            "source pages, API audit, and checkpoint commit in one transaction",
        ],
    )


def _run_provider_new(
    request: IndexPitRequest,
    *,
    runtime: TushareJobRuntime,
    reporter: ProgressReporter,
    preflight: JobPreflight,
) -> JobResult:
    units = _provider_units(request, runtime=runtime)
    specs = _unique_specs(units)
    ensure_source_unique_keys(runtime.engine, specs)
    contracts = _source_contracts(runtime.engine, specs)
    client = runtime.client(max_retries=request.max_retries)
    checkpoint = _new_checkpoint(
        kind="provider",
        request=request,
        preflight=preflight,
        units=[_endpoint_unit_json(unit) for unit in units],
    )
    checkpoint["contracts"] = sorted(contracts)
    run_id = _create_run(runtime.engine, checkpoint, preflight)
    return _run_provider_checkpoint(
        request,
        runtime=runtime,
        reporter=reporter,
        preflight=preflight,
        run_id=run_id,
        checkpoint=checkpoint,
        client=client,
        contracts=contracts,
    )


def _run_provider_checkpoint(
    request: IndexPitRequest,
    *,
    runtime: TushareJobRuntime,
    reporter: ProgressReporter,
    preflight: JobPreflight,
    run_id: int,
    checkpoint: dict[str, Any],
    client: Any | None = None,
    contracts: Mapping[str, Any] | None = None,
) -> JobResult:
    units = tuple(_endpoint_unit_from_json(value) for value in checkpoint["units"])
    specs = _unique_specs(units)
    ensure_source_unique_keys(runtime.engine, specs)
    active_contracts = contracts or _source_contracts(runtime.engine, specs)
    active_client = client or runtime.client(max_retries=request.max_retries)
    checkpoint = _mark_running(runtime.engine, run_id, checkpoint)
    invocation_calls = 0
    global_error: str | None = None
    _report(reporter, "start", checkpoint, len(units), message=f"run_id={run_id}")
    while int(checkpoint["cursor"]["unit_index"]) < len(units):
        unit_index = int(checkpoint["cursor"]["unit_index"])
        unit = units[unit_index]
        spec = _PROVIDER_SPECS[unit.endpoint_key]
        offset = int(checkpoint["cursor"]["offset"])
        response: TushareResponse | None = None
        cleaned_rows = 0
        candidate: dict[str, Any] | None = None
        lease_expected_checkpoint: dict[str, Any] | None = None
        page_error: BaseException | None = None
        page_committed = False
        advance = False
        if _budget_exhausted(request, active_client, invocation_calls):
            global_error = "max_api_calls reached before the next safe request"
            break
        try:
            with tushare_run_lease(runtime.engine, run_id):
                _assert_durable_checkpoint(runtime.engine, run_id, checkpoint)
                try:
                    response = active_client.fetch_page(
                        unit.page_request(spec, offset=offset)
                    )
                    invocation_calls += response.attempts
                    cleaned = clean_page(spec, response)
                    cleaned_rows = cleaned.cleaned_rows
                    _validate_source_scope(spec, unit, cleaned.rows)
                    signature = _page_signature(response)
                    _assert_page_progress(checkpoint, unit_index, offset, signature)
                    next_offset = next_page_offset(
                        spec,
                        current_offset=offset,
                        rows_returned=response.rows_returned,
                    )
                    candidate = _provider_success_checkpoint(
                        checkpoint,
                        response=response,
                        cleaned_rows=cleaned.cleaned_rows,
                        next_offset=next_offset,
                        signature=signature,
                    )
                    with external_table_page_transaction(
                        runtime.engine, spec
                    ) as connection:
                        write_result = write_business_rows(
                            connection,
                            spec,
                            cleaned.rows,
                            contract=active_contracts[spec.key],
                        )
                        candidate["counters"]["rows_inserted"] += (
                            write_result.inserted_rows
                        )
                        candidate["counters"]["rows_updated"] += (
                            write_result.updated_rows
                        )
                        _record_api_call(
                            connection,
                            run_id=run_id,
                            spec=spec,
                            unit=unit,
                            response=response,
                            error=None,
                        )
                        _save_checkpoint(
                            connection, run_id, candidate, status="running"
                        )
                    checkpoint = candidate
                    lease_expected_checkpoint = checkpoint
                except TushareStorageError as error:
                    checkpoint, page_committed = _reconcile_page_failure_locked(
                        runtime.engine,
                        run_id=run_id,
                        checkpoint=checkpoint,
                        candidate=candidate,
                        spec=spec,
                        unit=unit,
                        response=response,
                        cleaned_rows=cleaned_rows,
                        error=error,
                    )
                    lease_expected_checkpoint = checkpoint
                    page_error = error
                except TushareError as error:
                    if response is None:
                        invocation_calls += int(error.attempts or 1)
                    else:
                        error.endpoint = spec.key
                        error.attempts = response.attempts
                        error.status_code = response.status_code
                    advance = _is_terminal_unit_failure(error, response=response)
                    checkpoint = _persist_provider_failure_locked(
                        runtime.engine,
                        run_id=run_id,
                        checkpoint=checkpoint,
                        spec=spec,
                        unit=unit,
                        error=error,
                        response=response,
                        cleaned_rows=cleaned_rows,
                        advance=advance,
                    )
                    lease_expected_checkpoint = checkpoint
                    page_error = error
                except Exception as error:
                    checkpoint, page_committed = _reconcile_page_failure_locked(
                        runtime.engine,
                        run_id=run_id,
                        checkpoint=checkpoint,
                        candidate=candidate,
                        spec=spec,
                        unit=unit,
                        response=response,
                        cleaned_rows=cleaned_rows,
                        error=error,
                    )
                    lease_expected_checkpoint = checkpoint
                    page_error = error
        except TushareRunLeaseCleanupError as error:
            durable = _load_checkpoint(runtime.engine, run_id)
            if lease_expected_checkpoint is None or durable != lease_expected_checkpoint:
                raise TushareStorageError(
                    "Index PIT page could not be reconciled after run-lease cleanup"
                ) from error
            checkpoint = durable
            page_committed = candidate is not None and durable == candidate
            if page_error is None:
                page_error = error
        if page_error is not None:
            _report(
                reporter,
                "unit_failed",
                checkpoint,
                len(units),
                unit=unit.scope_key,
                message=_provider_log_message(
                    spec,
                    unit,
                    offset=offset,
                    fetched=response.rows_returned if response is not None else 0,
                    cleaned=cleaned_rows,
                    written=(
                        write_result.written_rows
                        if page_committed and response is not None
                        else 0
                    ),
                    calls=int(checkpoint["counters"]["api_calls"]),
                    status=(
                        "committed_with_warning"
                        if page_committed
                        else f"failed:{getattr(page_error, 'kind', 'unexpected')}"
                    ),
                ),
            )
            if not advance:
                global_error = safe_error_message(page_error)
                break
            continue
        _report(
            reporter,
            "unit_completed" if next_offset is None else "message",
            checkpoint,
            len(units),
            unit=unit.scope_key,
            message=_provider_log_message(
                spec,
                unit,
                offset=offset,
                fetched=response.rows_returned,
                cleaned=cleaned.cleaned_rows,
                written=write_result.written_rows,
                calls=int(checkpoint["counters"]["api_calls"]),
                status="committed",
            ),
        )
    checkpoint = _finish_run(
        runtime.engine,
        run_id,
        checkpoint,
        total_units=len(units),
        error_message=global_error,
    )
    result = _result_from_checkpoint(run_id, checkpoint, preflight, global_error)
    _report(reporter, "finish", checkpoint, len(units), message=f"status={result.status}")
    return result


def _sw_pit_units(request: IndexPitRequest) -> tuple[dict[str, str], ...]:
    start, end = _resolved_dates(request, default_from=_SW2014_START)
    start = max(start, _SW2014_START)
    units: list[dict[str, str]] = []
    for version, version_start, version_end in (
        ("SW2014", _SW2014_START, _SW2014_END),
        ("SW2021", _SW2021_START, end),
    ):
        part_start = max(start, version_start)
        part_end = min(end, version_end)
        if part_end < part_start:
            continue
        for month_start, month_end in _month_windows(part_start, part_end):
            units.append(
                {
                    "version": version,
                    "date_from": month_start.isoformat(),
                    "date_to": month_end.isoformat(),
                    "scope_key": f"{version}:{month_start:%Y%m%d}..{month_end:%Y%m%d}",
                }
            )
    if not units:
        raise ValueError("SW PIT date range contains no supported version dates")
    return tuple(units)


def _run_sw_pit_new(
    request: IndexPitRequest,
    *,
    runtime: TushareJobRuntime,
    reporter: ProgressReporter,
    preflight: JobPreflight,
) -> JobResult:
    ensure_index_pit_tables(runtime.engine)
    units = _sw_pit_units(request)
    checkpoint = _new_checkpoint(
        kind="sw_pit",
        request=request,
        preflight=preflight,
        units=list(units),
    )
    checkpoint["stage_ready"] = False
    checkpoint["published"] = False
    run_id = _create_run(runtime.engine, checkpoint, preflight)
    return _run_sw_pit_checkpoint(
        request,
        runtime=runtime,
        reporter=reporter,
        preflight=preflight,
        run_id=run_id,
        checkpoint=checkpoint,
    )


def _run_sw_pit_checkpoint(
    request: IndexPitRequest,
    *,
    runtime: TushareJobRuntime,
    reporter: ProgressReporter,
    preflight: JobPreflight,
    run_id: int,
    checkpoint: dict[str, Any],
) -> JobResult:
    with sw_pit_workflow_lease(runtime.engine):
        return _run_sw_pit_checkpoint_locked(
            request,
            runtime=runtime,
            reporter=reporter,
            preflight=preflight,
            run_id=run_id,
            checkpoint=checkpoint,
        )


def _run_sw_pit_checkpoint_locked(
    request: IndexPitRequest,
    *,
    runtime: TushareJobRuntime,
    reporter: ProgressReporter,
    preflight: JobPreflight,
    run_id: int,
    checkpoint: dict[str, Any],
) -> JobResult:
    units = tuple(checkpoint["units"])
    checkpoint = _mark_running(runtime.engine, run_id, checkpoint)
    if not checkpoint.get("stage_ready"):
        if int(checkpoint["cursor"]["unit_index"]) != 0 or int(
            checkpoint["cursor"]["offset"]
        ) != 0:
            raise TushareStorageError(
                "SW PIT staging is not ready but the materialization cursor advanced"
            )
        stage_candidate: dict[str, Any] | None = None
        try:
            with tushare_run_lease(runtime.engine, run_id):
                _assert_durable_checkpoint(runtime.engine, run_id, checkpoint)
                prepare_sw_pit_staging(
                    runtime.engine,
                    reset=True,
                    owner_run_id=run_id,
                )
                stage_candidate = deepcopy(checkpoint)
                stage_candidate["stage_ready"] = True
                stage_candidate["sw_schema_fingerprint"] = _sw_pit_schema_fingerprint(
                    runtime.engine, SW_PIT_STAGE_TABLE
                )
                try:
                    _save_checkpoint_engine(
                        runtime.engine, run_id, stage_candidate, status="running"
                    )
                except Exception as commit_error:
                    durable = _load_checkpoint(runtime.engine, run_id)
                    if durable == stage_candidate:
                        checkpoint = durable
                    elif durable != checkpoint:
                        raise TushareStorageError(
                            "SW PIT checkpoint changed while staging was prepared"
                        ) from commit_error
                    else:
                        raise TushareStorageError(
                            "SW PIT staging state could not be persisted"
                        ) from commit_error
                else:
                    checkpoint = stage_candidate
        except TushareRunLeaseCleanupError as cleanup_error:
            durable = _load_checkpoint(runtime.engine, run_id)
            if stage_candidate is None or durable != stage_candidate:
                raise TushareStorageError(
                    "SW PIT staging state could not be reconciled after run-lease cleanup"
                ) from cleanup_error
            checkpoint = durable
    table_state = sw_pit_table_state(runtime.engine)
    owner = f"j21_sw_pit_run:{run_id}"
    cursor_done = int(checkpoint["cursor"]["unit_index"]) >= len(units)
    recovery_ready = bool(
        cursor_done
        and checkpoint.get("validation")
        and table_state["final"]
        and table_state["final_owner"] == owner
        and not table_state["staging"]
    )
    if not recovery_ready and (
        not table_state["staging"] or table_state["staging_owner"] != owner
    ):
        raise TushareStorageError(
            "SW PIT staging is missing or belongs to another run"
        )
    expected_schema = checkpoint.get("sw_schema_fingerprint")
    if table_state["staging"]:
        stage_schema = _sw_pit_schema_fingerprint(runtime.engine, SW_PIT_STAGE_TABLE)
        if expected_schema is not None and stage_schema != expected_schema:
            raise TushareStorageError("SW PIT staging schema fingerprint changed")
        expected_schema = stage_schema
    elif recovery_ready:
        final_schema = _sw_pit_schema_fingerprint(runtime.engine, SW_PIT_TABLE)
        if expected_schema is not None and final_schema != expected_schema:
            raise TushareStorageError("Published SW PIT schema fingerprint changed")
        expected_schema = final_schema
    global_error: str | None = None
    _report(reporter, "start", checkpoint, len(units), message=f"run_id={run_id}")
    while int(checkpoint["cursor"]["unit_index"]) < len(units):
        unit = units[int(checkpoint["cursor"]["unit_index"])]
        scope_key = str(unit["scope_key"])
        candidate: dict[str, Any] | None = None
        lease_expected_checkpoint: dict[str, Any] | None = None
        page_error: BaseException | None = None
        page_committed = False
        try:
            with tushare_run_lease(runtime.engine, run_id):
                _assert_durable_checkpoint(runtime.engine, run_id, checkpoint)
                try:
                    candidate = deepcopy(checkpoint)
                    with index_pit_page_transaction(
                        runtime.engine, SW_PIT_STAGE_TABLE
                    ) as connection:
                        inserted = insert_sw_pit_partition(
                            connection,
                            version=str(unit["version"]),
                            date_from=date.fromisoformat(str(unit["date_from"])),
                            date_to=date.fromisoformat(str(unit["date_to"])),
                        )
                        candidate["cursor"]["unit_index"] += 1
                        candidate["counters"]["units_completed"] += 1
                        candidate["counters"]["rows_inserted"] += inserted
                        candidate["counters"]["pages_committed"] += 1
                        _save_checkpoint(
                            connection, run_id, candidate, status="running"
                        )
                    checkpoint = candidate
                    lease_expected_checkpoint = checkpoint
                except Exception as error:
                    durable = _load_checkpoint(runtime.engine, run_id)
                    if candidate is not None and durable == candidate:
                        checkpoint = durable
                        page_committed = True
                        lease_expected_checkpoint = checkpoint
                    elif durable == checkpoint:
                        checkpoint = _append_local_failure_locked(
                            runtime.engine,
                            run_id,
                            durable,
                            scope_key,
                            "storage"
                            if isinstance(error, TushareStorageError)
                            else "data",
                            safe_error_message(error),
                        )
                        lease_expected_checkpoint = checkpoint
                    else:
                        raise TushareStorageError(
                            "SW PIT checkpoint changed while a partition commit was reconciled"
                        ) from error
                    page_error = error
        except TushareRunLeaseCleanupError as error:
            durable = _load_checkpoint(runtime.engine, run_id)
            if lease_expected_checkpoint is None or durable != lease_expected_checkpoint:
                raise TushareStorageError(
                    "SW PIT partition could not be reconciled after run-lease cleanup"
                ) from error
            checkpoint = durable
            page_committed = candidate is not None and durable == candidate
            if page_error is None:
                page_error = error
        if page_error is not None:
            global_error = safe_error_message(page_error)
            break
        _report(
            reporter,
            "unit_completed",
            checkpoint,
            len(units),
            unit=scope_key,
            message=(
                f"phase=sw-pit table={SW_PIT_STAGE_TABLE} partition={scope_key} "
                f"written={inserted} status={'committed_with_warning' if page_committed else 'committed'} "
                "cumulative_partitions="
                f"{checkpoint['counters']['units_completed']}"
            ),
        )
    if int(checkpoint["cursor"]["unit_index"]) >= len(units) and not global_error:
        try:
            first = date.fromisoformat(str(units[0]["date_from"]))
            last = date.fromisoformat(str(units[-1]["date_to"]))
            if not checkpoint.get("published"):
                publish_expected: dict[str, Any] | None = None
                try:
                    with tushare_run_lease(runtime.engine, run_id):
                        _assert_durable_checkpoint(runtime.engine, run_id, checkpoint)
                        table_state = sw_pit_table_state(runtime.engine)
                        publish_already_committed = bool(
                            checkpoint.get("validation")
                            and table_state["final"]
                            and table_state["final_owner"] == owner
                            and not table_state["staging"]
                        )
                        if publish_already_committed:
                            final_validation = validate_sw_pit_final(
                                runtime.engine, date_from=first, date_to=last
                            )
                            if final_validation != checkpoint["validation"]:
                                raise TushareDataError(
                                    "Published SW PIT fingerprint differs from validated staging"
                                )
                            swap_sw_pit_staging(
                                runtime.engine, owner_run_id=run_id
                            )
                        else:
                            if (
                                not table_state["staging"]
                                or table_state["staging_owner"] != owner
                            ):
                                raise TushareStorageError(
                                    "SW PIT staging is missing or belongs to another run"
                                )
                            validation = validate_sw_pit_staging(
                                runtime.engine, date_from=first, date_to=last
                            )
                            validated = deepcopy(checkpoint)
                            validated["validation"] = validation
                            try:
                                _save_checkpoint_engine(
                                    runtime.engine, run_id, validated, status="running"
                                )
                            except Exception as commit_error:
                                durable = _load_checkpoint(runtime.engine, run_id)
                                if durable != validated:
                                    raise TushareStorageError(
                                        "SW PIT validation state could not be persisted"
                                    ) from commit_error
                                validated = durable
                            checkpoint = validated
                            swap_sw_pit_staging(
                                runtime.engine, owner_run_id=run_id
                            )
                        final_schema = _sw_pit_schema_fingerprint(
                            runtime.engine, SW_PIT_TABLE
                        )
                        if expected_schema is not None and final_schema != expected_schema:
                            raise TushareStorageError(
                                "Published SW PIT schema differs from validated staging"
                            )
                        published = deepcopy(checkpoint)
                        published["published"] = True
                        try:
                            _save_checkpoint_engine(
                                runtime.engine, run_id, published, status="running"
                            )
                        except Exception as commit_error:
                            durable = _load_checkpoint(runtime.engine, run_id)
                            if durable != published:
                                raise TushareStorageError(
                                    "SW PIT publish state could not be persisted"
                                ) from commit_error
                            published = durable
                        checkpoint = published
                        publish_expected = checkpoint
                except TushareRunLeaseCleanupError as cleanup_error:
                    durable = _load_checkpoint(runtime.engine, run_id)
                    if publish_expected is None or durable != publish_expected:
                        raise TushareStorageError(
                            "SW PIT publish could not be reconciled after run-lease cleanup"
                        ) from cleanup_error
                    checkpoint = durable
        except Exception as error:
            global_error = safe_error_message(error)
            checkpoint = _append_local_failure(
                runtime.engine,
                run_id,
                checkpoint,
                "publish",
                "storage" if isinstance(error, TushareStorageError) else "data",
                global_error,
            )
    checkpoint = _finish_run(
        runtime.engine,
        run_id,
        checkpoint,
        total_units=len(units),
        error_message=global_error,
        require_published=True,
    )
    result = _result_from_checkpoint(run_id, checkpoint, preflight, global_error)
    _report(reporter, "finish", checkpoint, len(units), message=f"status={result.status}")
    return result


def _sw_pit_schema_fingerprint(engine: Engine, table_name: str) -> str:
    """Validate the compact SW PIT schema before stage resume or publish."""
    if table_name not in {SW_PIT_STAGE_TABLE, SW_PIT_TABLE}:
        raise ValueError("unsupported SW PIT schema target")
    with engine.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT column_name, column_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema='a_share' AND table_name=:table_name "
                "ORDER BY ordinal_position"
            ),
            {"table_name": table_name},
        ).mappings().all()
        indexes = connection.execute(
            text(
                "SELECT index_name, non_unique, seq_in_index, column_name "
                "FROM information_schema.statistics "
                "WHERE table_schema='a_share' AND table_name=:table_name "
                "ORDER BY index_name, seq_in_index"
            ),
            {"table_name": table_name},
        ).mappings().all()
    actual_columns = tuple(
        (
            str(row["column_name"]),
            str(row["column_type"]).casefold(),
            str(row["is_nullable"]).upper(),
        )
        for row in columns
    )
    if actual_columns != _SW_PIT_COLUMNS:
        raise TushareStorageError(
            f"{table_name} columns do not match the compact SW PIT contract"
        )
    actual_indexes = tuple(
        (
            str(row["index_name"]),
            int(row["non_unique"]),
            int(row["seq_in_index"]),
            str(row["column_name"]),
        )
        for row in indexes
    )
    expected_indexes = tuple(
        ("PRIMARY", 0, sequence, column_name)
        for sequence, column_name in enumerate(_SW_PIT_PRIMARY_KEY, start=1)
    )
    if actual_indexes != expected_indexes:
        raise TushareStorageError(
            f"{table_name} must have only the exact date-first primary key"
        )
    return hashlib.sha256(
        json.dumps(
            {"columns": actual_columns, "indexes": actual_indexes},
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _weight_units(
    request: IndexPitRequest,
    *,
    runtime: TushareJobRuntime | None,
) -> tuple[_WeightUnit, ...]:
    active_runtime = runtime or TushareJobRuntime.from_env()
    metadata = load_index_metadata(active_runtime.engine)
    by_code = {value.index_code: value for value in metadata}
    if request.date_from is not None and request.date_to is not None:
        first_day = date(request.date_to.year, request.date_to.month, 1)
        last_day = _next_month(first_day) - timedelta(days=1)
        current_month = date(date.today().year, date.today().month, 1)
        if request.date_from.day != 1 or request.date_to != last_day:
            raise ValueError(
                "weight phase date ranges must contain complete natural months"
            )
        if request.date_to >= current_month:
            raise ValueError("weight phase date range must end before the current month")
        windows = _month_windows(request.date_from, request.date_to)
    else:
        windows = _completed_month_windows(request.months or 6)
    if request.phase == "style":
        selected = [
            value
            for value in metadata
            if value.category == "风格指数"
            and (not request.codes or value.index_code in request.codes)
        ]
        table_name = STYLE_PIT_TABLE
    elif request.phase == "general":
        missing = sorted(set(request.codes) - set(by_code))
        if missing:
            raise TushareDataError(
                "hq_idx_basic is missing requested indices: " + ", ".join(missing)
            )
        selected = [by_code[code] for code in request.codes]
        style_codes = [value.index_code for value in selected if value.category == "风格指数"]
        if style_codes:
            raise TushareDataError(
                "style indices must use the style phase: " + ", ".join(style_codes)
            )
        table_name = GENERAL_PIT_TABLE
    else:
        raise ValueError("weight units require style or general phase")
    units: list[_WeightUnit] = []
    for value in selected:
        for month_start, month_end in windows:
            if value.list_date and value.list_date > month_end:
                continue
            if value.exp_date and value.exp_date < month_start:
                continue
            units.append(
                _WeightUnit(
                    unit_key=f"{table_name}:{value.index_code}:{month_start:%Y%m}",
                    table_name=table_name,
                    metadata=value,
                    month_start=month_start,
                    month_end=month_end,
                )
            )
    if not units:
        raise TushareDataError("no active index-month units match the request")
    return tuple(units)


def _run_weight_new(
    request: IndexPitRequest,
    *,
    runtime: TushareJobRuntime,
    reporter: ProgressReporter,
    preflight: JobPreflight,
) -> JobResult:
    ensure_index_pit_tables(runtime.engine)
    units = _weight_units(request, runtime=runtime)
    client = runtime.client(max_retries=request.max_retries)
    checkpoint = _new_checkpoint(
        kind="weight",
        request=request,
        preflight=preflight,
        units=[_weight_unit_json(unit) for unit in units],
    )
    run_id = _create_run(runtime.engine, checkpoint, preflight)
    return _run_weight_checkpoint(
        request,
        runtime=runtime,
        reporter=reporter,
        preflight=preflight,
        run_id=run_id,
        checkpoint=checkpoint,
        client=client,
    )


def _run_weight_checkpoint(
    request: IndexPitRequest,
    *,
    runtime: TushareJobRuntime,
    reporter: ProgressReporter,
    preflight: JobPreflight,
    run_id: int,
    checkpoint: dict[str, Any],
    client: Any | None = None,
) -> JobResult:
    ensure_index_pit_tables(runtime.engine)
    units = tuple(_weight_unit_from_json(value) for value in checkpoint["units"])
    active_client = client or runtime.client(max_retries=request.max_retries)
    checkpoint = _mark_running(runtime.engine, run_id, checkpoint)
    invocation_calls = 0
    global_error: str | None = None
    _report(reporter, "start", checkpoint, len(units), message=f"run_id={run_id}")
    while int(checkpoint["cursor"]["unit_index"]) < len(units):
        unit_index = int(checkpoint["cursor"]["unit_index"])
        unit = units[unit_index]
        endpoint_unit = unit.endpoint_unit()
        offset = int(checkpoint["cursor"]["offset"])
        response: TushareResponse | None = None
        cleaned_rows = 0
        candidate: dict[str, Any] | None = None
        lease_expected_checkpoint: dict[str, Any] | None = None
        page_error: BaseException | None = None
        page_committed = False
        advance = False
        published = 0
        if _budget_exhausted(request, active_client, invocation_calls):
            global_error = "max_api_calls reached before the next safe request"
            break
        try:
            with tushare_run_lease(runtime.engine, run_id):
                _assert_durable_checkpoint(runtime.engine, run_id, checkpoint)
                try:
                    response = active_client.fetch_page(
                        endpoint_unit.page_request(INDEX_WEIGHT_SPEC, offset=offset)
                    )
                    invocation_calls += response.attempts
                    cleaned = clean_page(INDEX_WEIGHT_SPEC, response)
                    cleaned_rows = cleaned.cleaned_rows
                    _validate_weight_scope(unit, cleaned.rows)
                    signature = _page_signature(response)
                    _assert_page_progress(checkpoint, unit_index, offset, signature)
                    next_offset = next_page_offset(
                        INDEX_WEIGHT_SPEC,
                        current_offset=offset,
                        rows_returned=response.rows_returned,
                    )
                    candidate = _provider_success_checkpoint(
                        checkpoint,
                        response=response,
                        cleaned_rows=cleaned.cleaned_rows,
                        next_offset=next_offset,
                        signature=signature,
                    )
                    with index_pit_page_transaction(
                        runtime.engine, unit.table_name
                    ) as connection:
                        upsert_weight_stage(
                            connection,
                            run_id=run_id,
                            unit_key=unit.unit_key,
                            rows=cleaned.rows,
                        )
                        stage_metrics = weight_unit_metrics(
                            connection, run_id=run_id, unit_key=unit.unit_key
                        )
                        if next_offset is None:
                            if int(stage_metrics["snapshots"] or 0) == 0:
                                raise TushareNoDataError(
                                    "index_weight returned no monthly snapshot",
                                    endpoint=INDEX_WEIGHT_SPEC.key,
                                    attempts=response.attempts,
                                    status_code=response.status_code,
                                    provider_code=0,
                                )
                            published = publish_weight_unit(
                                connection,
                                run_id=run_id,
                                unit_key=unit.unit_key,
                                table_name=unit.table_name,
                                metadata=unit.metadata,
                                month_start=unit.month_start,
                                month_end=unit.month_end,
                            )
                            candidate["counters"]["rows_inserted"] += published
                            candidate.setdefault("weight_metrics", {})[
                                unit.unit_key
                            ] = {
                                key: str(value) if value is not None else None
                                for key, value in stage_metrics.items()
                            }
                        _record_api_call(
                            connection,
                            run_id=run_id,
                            spec=INDEX_WEIGHT_SPEC,
                            unit=endpoint_unit,
                            response=response,
                            error=None,
                        )
                        _save_checkpoint(
                            connection, run_id, candidate, status="running"
                        )
                    checkpoint = candidate
                    lease_expected_checkpoint = checkpoint
                except TushareStorageError as error:
                    checkpoint, page_committed = _reconcile_page_failure_locked(
                        runtime.engine,
                        run_id=run_id,
                        checkpoint=checkpoint,
                        candidate=candidate,
                        spec=INDEX_WEIGHT_SPEC,
                        unit=endpoint_unit,
                        response=response,
                        cleaned_rows=cleaned_rows,
                        error=error,
                    )
                    lease_expected_checkpoint = checkpoint
                    page_error = error
                except TushareError as error:
                    if response is None:
                        invocation_calls += int(error.attempts or 1)
                    else:
                        error.endpoint = INDEX_WEIGHT_SPEC.key
                        error.attempts = response.attempts
                        error.status_code = response.status_code
                    advance = _is_terminal_unit_failure(error, response=response)
                    checkpoint = _persist_provider_failure_locked(
                        runtime.engine,
                        run_id=run_id,
                        checkpoint=checkpoint,
                        spec=INDEX_WEIGHT_SPEC,
                        unit=endpoint_unit,
                        error=error,
                        response=response,
                        cleaned_rows=cleaned_rows,
                        advance=advance,
                        weight_stage_unit_key=unit.unit_key,
                    )
                    lease_expected_checkpoint = checkpoint
                    page_error = error
                except Exception as error:
                    checkpoint, page_committed = _reconcile_page_failure_locked(
                        runtime.engine,
                        run_id=run_id,
                        checkpoint=checkpoint,
                        candidate=candidate,
                        spec=INDEX_WEIGHT_SPEC,
                        unit=endpoint_unit,
                        response=response,
                        cleaned_rows=cleaned_rows,
                        error=error,
                    )
                    lease_expected_checkpoint = checkpoint
                    page_error = error
        except TushareRunLeaseCleanupError as error:
            durable = _load_checkpoint(runtime.engine, run_id)
            if lease_expected_checkpoint is None or durable != lease_expected_checkpoint:
                raise TushareStorageError(
                    "Index weight page could not be reconciled after run-lease cleanup"
                ) from error
            checkpoint = durable
            page_committed = candidate is not None and durable == candidate
            if page_error is None:
                page_error = error
        if page_error is not None:
            _report(
                reporter,
                "unit_failed",
                checkpoint,
                len(units),
                unit=unit.unit_key,
                message=_weight_log_message(
                    unit,
                    offset=offset,
                    fetched=response.rows_returned if response is not None else 0,
                    cleaned=cleaned_rows,
                    published=published if page_committed else 0,
                    calls=int(checkpoint["counters"]["api_calls"]),
                    status=(
                        "committed_with_warning"
                        if page_committed
                        else "failed:" + getattr(page_error, "kind", "unexpected")
                    ),
                ),
            )
            if not advance:
                global_error = safe_error_message(page_error)
                break
            continue
        _report(
            reporter,
            "unit_completed" if next_offset is None else "message",
            checkpoint,
            len(units),
            unit=unit.unit_key,
            message=_weight_log_message(
                unit,
                offset=offset,
                fetched=response.rows_returned,
                cleaned=cleaned.cleaned_rows,
                published=published,
                calls=int(checkpoint["counters"]["api_calls"]),
                status="committed",
            ),
        )
    checkpoint = _finish_run(
        runtime.engine,
        run_id,
        checkpoint,
        total_units=len(units),
        error_message=global_error,
    )
    result = _result_from_checkpoint(run_id, checkpoint, preflight, global_error)
    _report(reporter, "finish", checkpoint, len(units), message=f"status={result.status}")
    return result


def _new_checkpoint(
    *,
    kind: str,
    request: IndexPitRequest,
    preflight: JobPreflight,
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    parameters = _request_parameters(request)
    if kind == "weight" and request.date_from is None:
        windows = _completed_month_windows(request.months or 6)
        parameters["resolved_weight_date_from"] = windows[0][0].isoformat()
        parameters["resolved_weight_date_to"] = windows[-1][1].isoformat()
    plan_hash = _checkpoint_plan_hash(kind, parameters, units)
    return {
        "version": _CHECKPOINT_VERSION,
        "kind": kind,
        "phase": request.phase,
        "parameters": parameters,
        "preflight": preflight.to_dict(),
        "plan_hash": plan_hash,
        "units": units,
        "cursor": {"unit_index": 0, "offset": 0},
        "last_page": None,
        "page_signatures": [],
        "counters": {
            "units_completed": 0,
            "units_failed": 0,
            "pages_committed": 0,
            "rows_fetched": 0,
            "rows_cleaned": 0,
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_rejected": 0,
            "api_calls": 0,
        },
        "failures": [],
        "status": "running",
        "complete": False,
    }


def _create_run(engine: Engine, checkpoint: dict[str, Any], preflight: JobPreflight) -> int:
    parameters = checkpoint["parameters"]
    phase = str(checkpoint["phase"])
    with engine.begin() as connection:
        result = connection.execute(
            ingestion_task_run.insert().values(
                job_name=f"index_pit_{checkpoint['kind']}_{phase.replace('-', '_')}",
                market="CN",
                source="TUSHARE" if checkpoint["kind"] != "sw_pit" else "A_SHARE",
                target_schema="a_share",
                target_table=(
                    preflight.target_tables[0]
                    if len(preflight.target_tables) == 1
                    else "multiple_index_tables"
                ),
                status="running",
                date_from=_iso_date_or_none(parameters.get("date_from")),
                date_to=_iso_date_or_none(parameters.get("date_to")),
                started_at=datetime.now(UTC),
                config_hash=checkpoint["plan_hash"],
                code_version="index-pit-v1",
                checkpoint_json=checkpoint,
            )
        )
        run_id = result.inserted_primary_key[0]
    return int(run_id)


def _load_checkpoint(engine: Engine, run_id: int) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            select(
                ingestion_task_run.c.job_name,
                ingestion_task_run.c.config_hash,
                ingestion_task_run.c.checkpoint_json,
            ).where(ingestion_task_run.c.run_id == run_id)
        ).mappings().one_or_none()
    if row is None or not str(row["job_name"]).startswith("index_pit_"):
        raise TushareStorageError(f"index PIT run_id {run_id} does not exist")
    checkpoint = row["checkpoint_json"]
    if not isinstance(checkpoint, dict) or checkpoint.get("version") != _CHECKPOINT_VERSION:
        raise TushareStorageError("index PIT checkpoint is invalid or unsupported")
    _validate_checkpoint_payload(
        checkpoint,
        job_name=str(row["job_name"]),
        config_hash=str(row["config_hash"] or ""),
    )
    return deepcopy(checkpoint)


def _checkpoint_plan_hash(
    kind: object,
    parameters: object,
    units: object,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {"kind": kind, "parameters": parameters, "units": units},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_checkpoint_payload(
    checkpoint: Mapping[str, Any],
    *,
    job_name: str,
    config_hash: str,
) -> None:
    try:
        kind = str(checkpoint["kind"])
        phase = str(checkpoint["phase"])
        parameters = checkpoint["parameters"]
        units = checkpoint["units"]
        cursor = checkpoint["cursor"]
        counters = checkpoint["counters"]
        plan_hash = str(checkpoint["plan_hash"])
        if kind not in {"provider", "sw_pit", "weight"} or phase not in _PHASES:
            raise ValueError("unsupported kind or phase")
        if not isinstance(parameters, dict) or not isinstance(units, list) or not units:
            raise ValueError("parameters or units are invalid")
        if parameters.get("phase") != phase:
            raise ValueError("parameters phase does not match the checkpoint phase")
        expected_hash = _checkpoint_plan_hash(kind, parameters, units)
        if plan_hash != expected_hash or config_hash != expected_hash:
            raise ValueError("plan hash does not match its durable run")
        expected_job_name = f"index_pit_{kind}_{phase.replace('-', '_')}"
        if job_name != expected_job_name:
            raise ValueError("job name does not match kind and phase")
        if not isinstance(cursor, dict):
            raise ValueError("cursor is invalid")
        unit_index = cursor.get("unit_index")
        offset = cursor.get("offset")
        if (
            isinstance(unit_index, bool)
            or not isinstance(unit_index, int)
            or not 0 <= unit_index <= len(units)
            or isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or (unit_index == len(units) and offset != 0)
        ):
            raise ValueError("cursor is outside the immutable plan")
        if not isinstance(counters, dict) or any(
            isinstance(counters.get(name), bool)
            or not isinstance(counters.get(name), int)
            or int(counters[name]) < 0
            for name in (
                "units_completed",
                "units_failed",
                "pages_committed",
                "rows_fetched",
                "rows_cleaned",
                "rows_inserted",
                "rows_updated",
                "rows_rejected",
                "api_calls",
            )
        ):
            raise ValueError("checkpoint counters are invalid")
        preflight = checkpoint.get("preflight")
        if not isinstance(preflight, dict) or int(preflight.get("work_units", -1)) != len(
            units
        ):
            raise ValueError("preflight no longer matches its work units")
        _validate_checkpoint_units(kind, phase, units, parameters=parameters)
    except (KeyError, TypeError, ValueError) as error:
        raise TushareStorageError(f"index PIT checkpoint validation failed: {error}") from error


def _validate_checkpoint_units(
    kind: str,
    phase: str,
    units: Sequence[object],
    *,
    parameters: Mapping[str, Any],
) -> None:
    if kind == "provider":
        allowed_by_phase = {
            "basic": {INDEX_BASIC_SPEC.key},
            "classify": {INDEX_CLASSIFY_SPEC.key},
            "sw-daily": {SW_DAILY_SPEC.key},
            "sw-members": {INDEX_MEMBER_SPEC.key, INDEX_MEMBER_ALL_SPEC.key},
        }
        allowed = allowed_by_phase.get(phase)
        if allowed is None:
            raise ValueError("provider checkpoint has an invalid phase")
        for raw in units:
            if not isinstance(raw, dict):
                raise ValueError("provider unit is invalid")
            unit = _endpoint_unit_from_json(raw)
            spec = _PROVIDER_SPECS.get(unit.endpoint_key)
            if (
                spec is None
                or unit.endpoint_key not in allowed
                or unit.page_limit != spec.page_limit
            ):
                raise ValueError("provider unit changed endpoint or page limit")
        return
    if kind == "weight":
        expected_table = STYLE_PIT_TABLE if phase == "style" else GENERAL_PIT_TABLE
        if phase not in {"style", "general"}:
            raise ValueError("weight checkpoint has an invalid phase")
        parsed_units: list[_WeightUnit] = []
        for raw in units:
            if not isinstance(raw, dict):
                raise ValueError("weight unit is invalid")
            unit = _weight_unit_from_json(raw)
            parsed_units.append(unit)
            expected_key = (
                f"{unit.table_name}:{unit.metadata.index_code}:{unit.month_start:%Y%m}"
            )
            if (
                unit.table_name != expected_table
                or unit.unit_key != expected_key
                or unit.month_start.day != 1
                or unit.month_end != _next_month(unit.month_start) - timedelta(days=1)
                or unit.month_end >= date(date.today().year, date.today().month, 1)
                or (phase == "style")
                != (unit.metadata.category == "风格指数")
            ):
                raise ValueError("weight unit changed table, scope, or category")
        _validate_weight_checkpoint_plan(phase, parsed_units, parameters)
        return
    if phase != "sw-pit":
        raise ValueError("SW PIT checkpoint has an invalid phase")
    for raw in units:
        if not isinstance(raw, dict):
            raise ValueError("SW PIT unit is invalid")
        version = str(raw["version"])
        start = date.fromisoformat(str(raw["date_from"]))
        end = date.fromisoformat(str(raw["date_to"]))
        expected_scope = f"{version}:{start:%Y%m%d}..{end:%Y%m%d}"
        if str(raw["scope_key"]) != expected_scope or end < start:
            raise ValueError("SW PIT unit scope changed")
        if version == "SW2014" and not (
            _SW2014_START <= start <= end <= _SW2014_END
        ):
            raise ValueError("SW2014 unit is outside its effective dates")
        if version == "SW2021" and start < _SW2021_START:
            raise ValueError("SW2021 unit is outside its effective dates")
        if version not in {"SW2014", "SW2021"}:
            raise ValueError("SW PIT unit has an invalid version")


def _validate_weight_checkpoint_plan(
    phase: str,
    units: Sequence[_WeightUnit],
    parameters: Mapping[str, Any],
) -> None:
    raw_from = parameters.get("date_from")
    raw_to = parameters.get("date_to")
    raw_months = parameters.get("months")
    if (raw_from is None) != (raw_to is None):
        raise ValueError("weight checkpoint date range is incomplete")
    if raw_from is not None:
        if raw_months is not None:
            raise ValueError("weight checkpoint mixes exact dates and months")
        start = date.fromisoformat(str(raw_from))
        end = date.fromisoformat(str(raw_to))
        if (
            start.day != 1
            or end
            != _next_month(date(end.year, end.month, 1)) - timedelta(days=1)
        ):
            raise ValueError("weight checkpoint range is not complete natural months")
        if end < start or end >= date(date.today().year, date.today().month, 1):
            raise ValueError("weight checkpoint range is not a completed month range")
        windows = _month_windows(start, end)
    else:
        if (
            isinstance(raw_months, bool)
            or not isinstance(raw_months, int)
            or raw_months <= 0
        ):
            raise ValueError("weight checkpoint months is invalid")
        if not units:
            raise ValueError("weight checkpoint has no index-month units")
        resolved_from = parameters.get("resolved_weight_date_from")
        resolved_to = parameters.get("resolved_weight_date_to")
        if (resolved_from is None) != (resolved_to is None):
            raise ValueError("weight checkpoint resolved month range is incomplete")
        if resolved_from is not None:
            start = date.fromisoformat(str(resolved_from))
            end = date.fromisoformat(str(resolved_to))
            if (
                start.day != 1
                or end != _next_month(date(end.year, end.month, 1)) - timedelta(days=1)
                or end < start
                or end >= date(date.today().year, date.today().month, 1)
            ):
                raise ValueError("weight checkpoint resolved month range is invalid")
            windows = _month_windows(start, end)
            if len(windows) != raw_months:
                raise ValueError(
                    "weight checkpoint resolved month range does not match months"
                )
        else:
            # Checkpoints created before the resolved range was stored remain
            # resumable. Their latest actual unit is a safe anchor when at least
            # one selected index overlaps the final requested month.
            latest_month_end = max(unit.month_end for unit in units)
            if latest_month_end >= date(date.today().year, date.today().month, 1):
                raise ValueError("weight checkpoint months include the current month")
            cursor = _next_month(
                date(latest_month_end.year, latest_month_end.month, 1)
            )
            anchored_windows: list[tuple[date, date]] = []
            for _ in range(raw_months):
                previous_end = cursor - timedelta(days=1)
                previous_start = date(previous_end.year, previous_end.month, 1)
                anchored_windows.append((previous_start, previous_end))
                cursor = previous_start
            anchored_windows.reverse()
            windows = tuple(anchored_windows)

    raw_codes = parameters.get("codes")
    if not isinstance(raw_codes, list) or any(
        not isinstance(code, str) for code in raw_codes
    ):
        raise ValueError("weight checkpoint codes are invalid")
    requested_codes = tuple(_normalize_codes(raw_codes))
    if list(requested_codes) != raw_codes:
        raise ValueError("weight checkpoint codes are not exact normalized codes")
    metadata_by_code: dict[str, IndexMetadata] = {}
    actual_keys: list[tuple[str, date]] = []
    for unit in units:
        code = unit.metadata.index_code
        previous = metadata_by_code.setdefault(code, unit.metadata)
        if previous != unit.metadata:
            raise ValueError("weight checkpoint metadata changes within one index")
        actual_keys.append((code, unit.month_start))
    if len(actual_keys) != len(set(actual_keys)):
        raise ValueError("weight checkpoint contains duplicate index-month units")

    actual_codes = set(metadata_by_code)
    if (phase == "general" or requested_codes) and actual_codes != set(requested_codes):
        raise ValueError("weight checkpoint codes do not match its parameters")
    expected_keys = {
        (code, month_start)
        for code, metadata in metadata_by_code.items()
        for month_start, month_end in windows
        if (metadata.list_date is None or metadata.list_date <= month_end)
        and (metadata.exp_date is None or metadata.exp_date >= month_start)
    }
    if set(actual_keys) != expected_keys:
        raise ValueError(
            "weight checkpoint months are not continuous or do not match its exact range"
        )


def _mark_running(engine: Engine, run_id: int, checkpoint: dict[str, Any]) -> dict[str, Any]:
    if checkpoint.get("complete"):
        return checkpoint
    candidate = deepcopy(checkpoint)
    candidate["status"] = "running"
    try:
        with tushare_run_lease(engine, run_id):
            _assert_durable_checkpoint(engine, run_id, checkpoint)
            try:
                with engine.begin() as connection:
                    _save_checkpoint(
                        connection, run_id, candidate, status="running", finished=False
                    )
            except Exception as commit_error:
                durable = _load_checkpoint(engine, run_id)
                if durable == candidate:
                    return durable
                if durable != checkpoint:
                    raise TushareStorageError(
                        "Index PIT checkpoint changed while run start was persisted"
                    ) from commit_error
                raise TushareStorageError(
                    "Index PIT running status could not be persisted"
                ) from commit_error
    except TushareRunLeaseCleanupError as cleanup_error:
        durable = _load_checkpoint(engine, run_id)
        if durable == candidate:
            return durable
        raise TushareStorageError(
            "Index PIT run start could not be reconciled after run-lease cleanup"
        ) from cleanup_error
    return candidate


def _assert_durable_checkpoint(
    engine: Engine,
    run_id: int,
    expected: Mapping[str, Any],
) -> None:
    actual = _load_checkpoint(engine, run_id)
    if actual != dict(expected):
        raise TushareStorageError("index PIT run checkpoint changed in another executor")


def _save_checkpoint(
    connection: Any,
    run_id: int,
    checkpoint: Mapping[str, Any],
    *,
    status: str,
    finished: bool = False,
    error_message: str | None = None,
) -> None:
    counters = checkpoint["counters"]
    values: dict[str, object] = {
        "status": status,
        "checkpoint_json": dict(checkpoint),
        "rows_fetched": counters["rows_fetched"],
        "rows_inserted": counters["rows_inserted"],
        "rows_updated": counters["rows_updated"],
        "rows_rejected": counters["rows_rejected"],
        "api_calls": counters["api_calls"],
        "error_message": error_message,
    }
    if finished:
        values["finished_at"] = datetime.now(UTC)
    else:
        values["finished_at"] = None
    connection.execute(
        update(ingestion_task_run)
        .where(ingestion_task_run.c.run_id == run_id)
        .values(**values)
    )


def _save_checkpoint_engine(
    engine: Engine,
    run_id: int,
    checkpoint: Mapping[str, Any],
    *,
    status: str,
    finished: bool = False,
    error_message: str | None = None,
) -> None:
    with engine.begin() as connection:
        _save_checkpoint(
            connection,
            run_id,
            checkpoint,
            status=status,
            finished=finished,
            error_message=error_message,
        )


def _record_api_call(
    connection: Any,
    *,
    run_id: int,
    spec: EndpointSpec,
    unit: EndpointUnit,
    response: TushareResponse | None,
    error: TushareError | None,
) -> None:
    attempts = response.attempts if response is not None else int(error.attempts or 1)
    connection.execute(
        api_call_log.insert().values(
            run_id=run_id,
            source="TUSHARE",
            endpoint=spec.api_name,
            provider_symbol=_provider_symbol(unit),
            date_from=_request_date(unit.params.get("start_date") or unit.params.get("trade_date")),
            date_to=_request_date(unit.params.get("end_date") or unit.params.get("trade_date")),
            status_code=response.status_code if response is not None else error.status_code,
            success=error is None,
            retry_count=max(0, attempts - 1),
            rows_returned=response.rows_returned if response is not None else 0,
            error_message=None if error is None else safe_error_message(error),
            called_at=datetime.now(UTC),
            duration_ms=None,
        )
    )


def _persist_provider_failure_locked(
    engine: Engine,
    *,
    run_id: int,
    checkpoint: dict[str, Any],
    spec: EndpointSpec,
    unit: EndpointUnit,
    error: TushareError,
    response: TushareResponse | None,
    cleaned_rows: int,
    advance: bool,
    weight_stage_unit_key: str | None = None,
) -> dict[str, Any]:
    candidate = deepcopy(checkpoint)
    attempts = response.attempts if response is not None else int(error.attempts or 1)
    candidate["counters"]["api_calls"] += attempts
    if response is not None:
        candidate["counters"]["rows_fetched"] += response.rows_returned
        candidate["counters"]["rows_cleaned"] += cleaned_rows
    failure = {
        "unit": unit.scope_key,
        "category": error.kind,
        "message": safe_error_message(error),
        "terminal": advance,
    }
    candidate["failures"].append(failure)
    if advance:
        candidate["counters"]["units_failed"] += 1
        candidate["cursor"]["unit_index"] += 1
        candidate["cursor"]["offset"] = 0
        candidate["page_signatures"] = []
    try:
        with engine.begin() as connection:
            if advance and weight_stage_unit_key is not None:
                clear_weight_stage(
                    connection,
                    run_id=run_id,
                    unit_key=weight_stage_unit_key,
                )
            _record_api_call(
                connection,
                run_id=run_id,
                spec=spec,
                unit=unit,
                response=response,
                error=error,
            )
            _save_checkpoint(connection, run_id, candidate, status="running")
    except Exception as commit_error:
        durable = _load_checkpoint(engine, run_id)
        if durable == candidate:
            return durable
        if durable != checkpoint:
            raise TushareStorageError(
                "Index PIT checkpoint changed while a provider failure was persisted"
            ) from commit_error
        raise TushareStorageError(
            "Consumed index PIT failure and API usage could not be persisted"
        ) from commit_error
    return candidate


def _reconcile_page_failure_locked(
    engine: Engine,
    *,
    run_id: int,
    checkpoint: dict[str, Any],
    candidate: dict[str, Any] | None,
    spec: EndpointSpec,
    unit: EndpointUnit,
    response: TushareResponse | None,
    cleaned_rows: int,
    error: BaseException,
) -> tuple[dict[str, Any], bool]:
    """Keep a committed cursor, or durably account for an uncommitted API page."""
    durable = _load_checkpoint(engine, run_id)
    message = safe_error_message(error)
    category = "storage" if isinstance(error, TushareStorageError) else "unexpected"
    if candidate is not None and durable == candidate:
        return durable, True
    if durable != checkpoint:
        raise TushareStorageError(
            "Index PIT checkpoint changed while a page failure was reconciled"
        ) from error
    if response is None:
        return (
            _append_local_failure_locked(
                engine,
                run_id,
                durable,
                unit.scope_key,
                category,
                message,
            ),
            False,
        )
    return (
        _persist_uncommitted_page_usage_locked(
            engine,
            run_id=run_id,
            checkpoint=durable,
            spec=spec,
            unit=unit,
            response=response,
            cleaned_rows=cleaned_rows,
            category=category,
            message=message,
        ),
        False,
    )


def _persist_uncommitted_page_usage_locked(
    engine: Engine,
    *,
    run_id: int,
    checkpoint: dict[str, Any],
    spec: EndpointSpec,
    unit: EndpointUnit,
    response: TushareResponse,
    cleaned_rows: int,
    category: str,
    message: str,
) -> dict[str, Any]:
    """Record consumed provider usage without advancing a rolled-back cursor."""
    candidate = deepcopy(checkpoint)
    candidate["counters"]["rows_fetched"] += response.rows_returned
    candidate["counters"]["rows_cleaned"] += cleaned_rows
    candidate["counters"]["api_calls"] += response.attempts
    candidate["failures"].append(
        {
            "unit": unit.scope_key,
            "category": category,
            "message": message,
            "terminal": False,
        }
    )
    audit_error = TushareStorageError(
        message,
        endpoint=spec.key,
        attempts=response.attempts,
        status_code=response.status_code,
    )
    try:
        with engine.begin() as connection:
            _record_api_call(
                connection,
                run_id=run_id,
                spec=spec,
                unit=unit,
                response=response,
                error=audit_error,
            )
            _save_checkpoint(connection, run_id, candidate, status="running")
    except Exception as commit_error:
        durable = _load_checkpoint(engine, run_id)
        if durable == candidate:
            return durable
        if durable != checkpoint:
            raise TushareStorageError(
                "Index PIT checkpoint changed while provider usage was persisted"
            ) from commit_error
        raise TushareStorageError(
            "Consumed index PIT API usage could not be persisted"
        ) from commit_error
    return candidate


def _append_local_failure_locked(
    engine: Engine,
    run_id: int,
    checkpoint: dict[str, Any],
    unit: str,
    category: str,
    message: str,
) -> dict[str, Any]:
    candidate = deepcopy(checkpoint)
    candidate["failures"].append(
        {
            "unit": unit,
            "category": category,
            "message": message,
            "terminal": False,
        }
    )
    try:
        _save_checkpoint_engine(engine, run_id, candidate, status="running")
    except Exception as commit_error:
        durable = _load_checkpoint(engine, run_id)
        if durable == candidate:
            return durable
        if durable != checkpoint:
            raise TushareStorageError(
                "Index PIT checkpoint changed while a local failure was persisted"
            ) from commit_error
        raise TushareStorageError(
            "Index PIT local failure could not be persisted"
        ) from commit_error
    return candidate


def _append_local_failure(
    engine: Engine,
    run_id: int,
    checkpoint: dict[str, Any],
    unit: str,
    category: str,
    message: str,
) -> dict[str, Any]:
    with tushare_run_lease(engine, run_id):
        _assert_durable_checkpoint(engine, run_id, checkpoint)
        return _append_local_failure_locked(
            engine,
            run_id,
            checkpoint,
            unit,
            category,
            message,
        )


def _finish_run(
    engine: Engine,
    run_id: int,
    checkpoint: dict[str, Any],
    *,
    total_units: int,
    error_message: str | None,
    require_published: bool = False,
) -> dict[str, Any]:
    candidate = deepcopy(checkpoint)
    cursor_done = int(candidate["cursor"]["unit_index"]) >= total_units
    published = not require_published or bool(candidate.get("published"))
    candidate["complete"] = cursor_done and published
    terminal_failures = int(candidate["counters"]["units_failed"]) > 0
    has_committed_work = bool(
        int(candidate["counters"]["units_completed"])
        or int(candidate["counters"]["pages_committed"])
        or cursor_done
    )
    if candidate["complete"] and not terminal_failures and error_message is None:
        status = "success"
    elif has_committed_work:
        status = "partial_failed"
    else:
        status = "failed"
    candidate["status"] = status
    try:
        with tushare_run_lease(engine, run_id):
            _assert_durable_checkpoint(engine, run_id, checkpoint)
            try:
                _save_checkpoint_engine(
                    engine,
                    run_id,
                    candidate,
                    status=status,
                    finished=True,
                    error_message=error_message,
                )
            except Exception as commit_error:
                durable = _load_checkpoint(engine, run_id)
                if durable == candidate:
                    return durable
                if durable != checkpoint:
                    raise TushareStorageError(
                        "Index PIT checkpoint changed while run completion was persisted"
                    ) from commit_error
                raise TushareStorageError(
                    "Index PIT run completion could not be persisted"
                ) from commit_error
    except TushareRunLeaseCleanupError as cleanup_error:
        durable = _load_checkpoint(engine, run_id)
        if durable == candidate:
            return durable
        raise TushareStorageError(
            "Index PIT run completion could not be reconciled after run-lease cleanup"
        ) from cleanup_error
    return candidate


def _provider_success_checkpoint(
    checkpoint: dict[str, Any],
    *,
    response: TushareResponse,
    cleaned_rows: int,
    next_offset: int | None,
    signature: str,
) -> dict[str, Any]:
    candidate = deepcopy(checkpoint)
    candidate["counters"]["rows_fetched"] += response.rows_returned
    candidate["counters"]["rows_cleaned"] += cleaned_rows
    candidate["counters"]["api_calls"] += response.attempts
    candidate["counters"]["pages_committed"] += 1
    candidate["last_page"] = {
        "unit_index": candidate["cursor"]["unit_index"],
        "offset": candidate["cursor"]["offset"],
        "signature": signature,
    }
    page_signatures = list(candidate.get("page_signatures", []))
    page_signatures.append(signature)
    if next_offset is None:
        candidate["cursor"]["unit_index"] += 1
        candidate["cursor"]["offset"] = 0
        candidate["counters"]["units_completed"] += 1
        candidate["page_signatures"] = []
    else:
        candidate["cursor"]["offset"] = next_offset
        candidate["page_signatures"] = page_signatures
    return candidate


def _result_from_checkpoint(
    run_id: int,
    checkpoint: Mapping[str, Any],
    preflight: JobPreflight,
    error_message: str | None,
) -> JobResult:
    counters = checkpoint["counters"]
    visible_failure_values = (
        [] if checkpoint.get("status") == "success" else checkpoint.get("failures", [])
    )
    failures = [
        JobFailure(
            str(value.get("unit", "unknown")),
            str(value.get("category", "unknown")),
            str(value.get("message", "unknown")),
        )
        for value in visible_failure_values
        if isinstance(value, dict)
    ]
    return JobResult(
        job=_JOB_KEY,
        status=str(checkpoint["status"]),  # type: ignore[arg-type]
        run_id=run_id,
        parameters=preflight.parameters,
        parameter_sources=preflight.parameter_sources,
        rows_fetched=int(counters["rows_fetched"]),
        rows_matched=int(counters["rows_cleaned"]),
        rows_inserted=int(counters["rows_inserted"]),
        rows_rejected=int(counters["rows_rejected"]),
        api_calls=int(counters["api_calls"]),
        work_units_total=preflight.work_units,
        work_units_completed=int(counters["units_completed"]),
        work_units_failed=int(counters["units_failed"]),
        failures=failures,
        metrics={
            "rows_updated": int(counters["rows_updated"]),
            "pages_committed": int(counters["pages_committed"]),
            "published": bool(checkpoint.get("published", False)),
            "validation": checkpoint.get("validation"),
        },
        error_message=error_message,
        preflight=preflight,
    )


def _dry_run(request: IndexPitRequest, preflight: JobPreflight) -> JobResult:
    return JobResult(
        job=_JOB_KEY,
        status="dry_run",
        run_id=request.resume_run_id,
        parameters=preflight.parameters,
        parameter_sources=preflight.parameter_sources,
        work_units_total=preflight.work_units,
        preflight=preflight,
    )


def _preflight_from_checkpoint(checkpoint: Mapping[str, Any]) -> JobPreflight:
    raw = checkpoint.get("preflight")
    if not isinstance(raw, dict):
        raise TushareStorageError("index PIT checkpoint has no preflight plan")
    return JobPreflight(**raw)


def _source_contracts(
    engine: Engine,
    specs: Sequence[EndpointSpec],
) -> dict[str, Any]:
    with engine.connect() as connection:
        return {spec.key: verify_external_table(connection, spec) for spec in specs}


def _unique_specs(units: Sequence[EndpointUnit]) -> tuple[EndpointSpec, ...]:
    result: list[EndpointSpec] = []
    seen: set[str] = set()
    for unit in units:
        if unit.endpoint_key not in seen:
            seen.add(unit.endpoint_key)
            result.append(_PROVIDER_SPECS[unit.endpoint_key])
    return tuple(result)


def _validate_source_scope(
    spec: EndpointSpec,
    unit: EndpointUnit,
    rows: Sequence[Mapping[str, object]],
) -> None:
    for row in rows:
        if spec is INDEX_CLASSIFY_SPEC:
            if row["src"] != unit.params["src"] or row["level"] != unit.params["level"]:
                raise TushareDataError("index_classify returned rows outside src/level scope")
        elif spec is SW_DAILY_SPEC:
            trade_date = row["trade_date"]
            if not isinstance(trade_date, date):
                raise TushareDataError("sw_daily returned an invalid trade_date")
            start = _request_date(unit.params["start_date"])
            end = _request_date(unit.params["end_date"])
            if not start <= trade_date <= end:
                raise TushareDataError("sw_daily returned rows outside requested dates")
        elif spec is INDEX_MEMBER_SPEC:
            if row["index_code"] != unit.params["index_code"]:
                raise TushareDataError("index_member returned rows outside index_code scope")
            if row["is_new"] != unit.params["is_new"]:
                raise TushareDataError("index_member returned rows outside is_new scope")
        elif spec is INDEX_MEMBER_ALL_SPEC:
            if row["l1_code"] != unit.params["l1_code"]:
                raise TushareDataError("index_member_all returned rows outside l1_code scope")
            if row["is_new"] != unit.params["is_new"]:
                raise TushareDataError("index_member_all returned rows outside is_new scope")


def _validate_weight_scope(
    unit: _WeightUnit,
    rows: Sequence[Mapping[str, object]],
) -> None:
    for row in rows:
        if row["index_code"] != unit.metadata.index_code:
            raise TushareDataError("index_weight returned another index_code")
        trade_date = row["trade_date"]
        if not isinstance(trade_date, date) or not unit.month_start <= trade_date <= unit.month_end:
            raise TushareDataError("index_weight returned a snapshot outside its month")


def _assert_page_progress(
    checkpoint: Mapping[str, Any],
    unit_index: int,
    offset: int,
    signature: str,
) -> None:
    signatures = checkpoint.get("page_signatures", [])
    if isinstance(signatures, list) and signature in signatures:
        raise TushareDataError("provider repeated an earlier page in the current unit")
    previous = checkpoint.get("last_page")
    if not isinstance(previous, dict):
        return
    if (
        int(previous.get("unit_index", -1)) == unit_index
        and int(previous.get("offset", -1)) != offset
        and previous.get("signature") == signature
    ):
        raise TushareDataError("provider repeated the previous page at a new offset")


def _page_signature(response: TushareResponse) -> str:
    payload = {
        "fields": response.fields,
        "rows": response.items,
        "count": response.rows_returned,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _budget_exhausted(request: IndexPitRequest, client: Any, used: int) -> bool:
    if request.max_api_calls is None:
        return False
    maximum_attempts = int(getattr(client, "max_retries", 0)) + 1
    return used + maximum_attempts > request.max_api_calls


def _is_terminal_unit_failure(
    error: TushareError,
    *,
    response: TushareResponse | None,
) -> bool:
    """Skip only endpoint-local failures whose provider usage must not be replayed."""
    if isinstance(error, (TushareAuthenticationError, TushareRateLimitError)):
        return False
    if isinstance(error, (TusharePermissionError, TushareNoDataError)):
        return True
    if isinstance(error, TushareTransportError):
        return True
    # Cleaning and scope failures happen after a response was consumed.  Replaying
    # that immutable unit on ordinary resume only spends the same call again.
    return response is not None and isinstance(error, TushareDataError)


def _provider_log_message(
    spec: EndpointSpec,
    unit: EndpointUnit,
    *,
    offset: int,
    fetched: int,
    cleaned: int,
    written: int,
    calls: int,
    status: str,
) -> str:
    code = (
        unit.params.get("index_code")
        or unit.params.get("l1_code")
        or unit.params.get("ts_code")
        or "-"
    )
    date_scope = (
        f"{unit.params.get('start_date', '-')}..{unit.params.get('end_date', '-')}"
    )
    return (
        f"phase={spec.api_name} endpoint={spec.api_name} table={spec.target_table} "
        f"scope={unit.scope_key} code={code} date={date_scope} "
        f"offset={offset} fetched={fetched} "
        f"cleaned={cleaned} written={written} cumulative_calls={calls} status={status}"
    )


def _weight_log_message(
    unit: _WeightUnit,
    *,
    offset: int,
    fetched: int,
    cleaned: int,
    published: int,
    calls: int,
    status: str,
) -> str:
    return (
        f"phase=weight endpoint=index_weight table={unit.table_name} "
        f"index={unit.metadata.index_code} month={unit.month_start:%Y-%m} "
        f"unit={unit.unit_key} offset={offset} fetched={fetched} "
        f"cleaned={cleaned} published={published} cumulative_calls={calls} "
        f"status={status}"
    )


def _report(
    reporter: ProgressReporter,
    kind: str,
    checkpoint: Mapping[str, Any],
    total: int,
    *,
    unit: str | None = None,
    message: str,
) -> None:
    try:
        reporter.on_event(
            ProgressEvent(
                kind=kind,  # type: ignore[arg-type]
                job=_JOB_KEY,
                completed=int(checkpoint["counters"]["units_completed"]),
                total=total,
                unit=unit,
                message=f"J21 database[index PIT] {message}",
                counters={
                    "fetched": int(checkpoint["counters"]["rows_fetched"]),
                    "inserted": int(checkpoint["counters"]["rows_inserted"]),
                    "updated": int(checkpoint["counters"]["rows_updated"]),
                    "failed": int(checkpoint["counters"]["units_failed"]),
                    "api_calls": int(checkpoint["counters"]["api_calls"]),
                },
            )
        )
    except Exception:
        return


def _unit(spec: EndpointSpec, scope_key: str, params: Mapping[str, object]) -> EndpointUnit:
    if spec.page_limit is None:
        raise ValueError(f"{spec.key} has no page limit")
    return EndpointUnit(spec.key, scope_key, params, spec.page_limit)  # type: ignore[arg-type]


def _endpoint_unit_json(unit: EndpointUnit) -> dict[str, Any]:
    return {
        "endpoint_key": unit.endpoint_key,
        "scope_key": unit.scope_key,
        "params": dict(unit.params),
        "page_limit": unit.page_limit,
    }


def _endpoint_unit_from_json(value: Mapping[str, Any]) -> EndpointUnit:
    return EndpointUnit(
        endpoint_key=str(value["endpoint_key"]),
        scope_key=str(value["scope_key"]),
        params=dict(value["params"]),
        page_limit=int(value["page_limit"]),
    )


def _weight_unit_json(unit: _WeightUnit) -> dict[str, Any]:
    return {
        "unit_key": unit.unit_key,
        "table_name": unit.table_name,
        "metadata": {
            **asdict(unit.metadata),
            "list_date": unit.metadata.list_date.isoformat() if unit.metadata.list_date else None,
            "exp_date": unit.metadata.exp_date.isoformat() if unit.metadata.exp_date else None,
        },
        "month_start": unit.month_start.isoformat(),
        "month_end": unit.month_end.isoformat(),
    }


def _weight_unit_from_json(value: Mapping[str, Any]) -> _WeightUnit:
    raw_metadata = dict(value["metadata"])
    raw_metadata["list_date"] = _iso_date_or_none(raw_metadata.get("list_date"))
    raw_metadata["exp_date"] = _iso_date_or_none(raw_metadata.get("exp_date"))
    return _WeightUnit(
        unit_key=str(value["unit_key"]),
        table_name=str(value["table_name"]),
        metadata=IndexMetadata(**raw_metadata),
        month_start=date.fromisoformat(str(value["month_start"])),
        month_end=date.fromisoformat(str(value["month_end"])),
    )


def _request_parameters(request: IndexPitRequest) -> dict[str, Any]:
    return {
        "phase": request.phase,
        "date_from": request.date_from.isoformat() if request.date_from else None,
        "date_to": request.date_to.isoformat() if request.date_to else None,
        "months": request.months,
        "codes": list(request.codes),
    }


def _all_phase_requests(request: IndexPitRequest) -> tuple[IndexPitRequest, ...]:
    common = {
        "max_retries": request.max_retries,
        "max_api_calls": request.max_api_calls,
        "execute": request.execute,
        "override_source": request.override_source,
    }
    phases = [
        IndexPitRequest(phase="basic", **common),
        IndexPitRequest(phase="classify", **common),
        IndexPitRequest(
            phase="sw-daily",
            date_from=request.date_from,
            date_to=request.date_to,
            **common,
        ),
        IndexPitRequest(phase="sw-members", **common),
        IndexPitRequest(
            phase="sw-pit",
            date_from=request.date_from,
            date_to=request.date_to,
            **common,
        ),
        IndexPitRequest(
            phase="style",
            months=request.months or 6,
            **common,
        ),
    ]
    if request.codes:
        phases.append(
            IndexPitRequest(
                phase="general",
                months=request.months or 6,
                codes=request.codes,
                **common,
            )
        )
    return tuple(phases)


def _resolved_dates(
    request: IndexPitRequest,
    *,
    default_from: date,
) -> tuple[date, date]:
    return request.date_from or default_from, request.date_to or date.today()


def _month_windows(start: date, end: date) -> tuple[tuple[date, date], ...]:
    result: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        next_month = _next_month(cursor)
        result.append((max(start, cursor), min(end, next_month - timedelta(days=1))))
        cursor = next_month
    return tuple(result)


def _completed_month_windows(months: int) -> tuple[tuple[date, date], ...]:
    current_month = date(date.today().year, date.today().month, 1)
    cursor = current_month
    result: list[tuple[date, date]] = []
    for _ in range(months):
        previous_end = cursor - timedelta(days=1)
        previous_start = date(previous_end.year, previous_end.month, 1)
        result.append((previous_start, previous_end))
        cursor = previous_start
    result.reverse()
    return tuple(result)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _normalize_codes(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("index codes must be text")
        for raw in value.split(","):
            code = raw.strip().upper()
            if not code or len(code) > 20 or not all(
                character.isalnum() or character in "._-" for character in code
            ):
                raise ValueError(f"invalid index code: {raw}")
            if code not in seen:
                seen.add(code)
                result.append(code)
    return tuple(result)


def _provider_symbol(unit: EndpointUnit) -> str | None:
    for key in ("index_code", "l1_code", "ts_code"):
        value = unit.params.get(key)
        if isinstance(value, str) and value and len(value) <= 128:
            return value
    return None


def _request_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y%m%d").date()


def _iso_date_or_none(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
