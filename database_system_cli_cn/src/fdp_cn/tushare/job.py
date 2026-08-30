"""Resumable Tushare endpoint job shared by CLI, Menu, and Python callers."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from fdp_cn.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
)
from fdp_cn.tushare.runtime import TushareJobRuntime
from fdp_cn.tushare.catalog import (
    default_historical_endpoint_specs,
    get_endpoint_spec,
    iter_endpoint_specs,
)
from fdp_cn.tushare.cleaning import clean_page
from fdp_cn.tushare.errors import (
    TushareAuthenticationError,
    TushareDataError,
    TushareError,
    TusharePostCommitStorageError,
    TushareRunLeaseCleanupError,
    TushareStorageError,
    safe_error_message,
)
from fdp_cn.tushare.models import (
    CleanedPage,
    EndpointPlanRequest,
    EndpointSpec,
    EndpointUnit,
    ExternalTableContract,
    TushareApiEvent,
    TushareResponse,
)
from fdp_cn.tushare.planning import (
    next_page_offset,
    plan_endpoint_units,
    validate_endpoint_params,
)
from fdp_cn.tushare.storage import (
    external_table_page_transaction,
    tushare_run_lease,
    verify_external_table,
    write_business_rows,
)
from fdp_cn.tushare.system_tables import api_call_log, ingestion_task_run

CHECKPOINT_VERSION = 2
TARGET_SCHEMA = "a_share"
DEFAULT_MAX_API_CALLS = 10_000
_ATOMIC_SYSTEM_TABLES = frozenset({"api_call_log", "ingestion_task_run"})
_SYSTEM_TABLE_ENGINES = text(
    """
    SELECT TABLE_NAME AS table_name, ENGINE AS engine
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = 'system_cn'
      AND TABLE_NAME IN ('api_call_log', 'ingestion_task_run')
    """
)


@dataclass(frozen=True)
class TushareJobRequest:
    """UI-neutral request for one new or resumed Tushare ingest run."""

    endpoint: str | None = None
    category: str | None = None
    all_endpoints: bool = False
    date_from: date | None = None
    date_to: date | None = None
    codes: tuple[str, ...] = ()
    params: Mapping[str, object] = field(default_factory=dict)
    refresh: bool = False
    resume_run_id: int | None = None
    max_retries: int | None = None
    max_api_calls: int | None = None
    execute: bool = False
    override_source: str = "python"

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "codes", tuple(self.codes))
        if self.max_retries is not None and (
            isinstance(self.max_retries, bool) or self.max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if self.max_api_calls is not None and (
            isinstance(self.max_api_calls, bool)
            or not isinstance(self.max_api_calls, int)
            or self.max_api_calls <= 0
        ):
            raise ValueError("max_api_calls must be a positive integer")
        if self.resume_run_id is not None and self.resume_run_id <= 0:
            raise ValueError("resume_run_id must be positive")


class TushareEndpointJob:
    """Execute catalogued Tushare pages with atomic writes and checkpoints."""

    job_key = "ingest.tushare"
    job_module = "fdp_cn.tushare.job"

    def preflight(
        self,
        request: TushareJobRequest,
        *,
        runtime: TushareJobRuntime | None = None,
        verify_storage: bool = True,
    ) -> JobPreflight:
        active_request = request
        if request.resume_run_id is not None:
            if runtime is None:
                raise ValueError(
                    "runtime is required to preflight a resumed Tushare run"
                )
            checkpoint = self._load_checkpoint(runtime, request.resume_run_id)
            active_request = _resume_request(request, checkpoint)
            specs = _specs_from_checkpoint(checkpoint)
        else:
            specs = _select_specs(active_request)
        planned = _plan_specs(specs, active_request)
        if request.resume_run_id is not None:
            _assert_checkpoint_catalog(checkpoint, specs, planned)
        if verify_storage:
            if runtime is None:
                runtime = TushareJobRuntime.from_env()
            with runtime.engine.connect() as connection:
                for spec, _units in planned:
                    verify_external_table(connection, spec)

        warnings = [
            "estimated_api_calls is a lower bound; full pages continue by documented offset",
        ]
        if active_request.all_endpoints or active_request.category:
            skipped = _skipped_specs(active_request)
            if skipped:
                warnings.append(
                    f"{len(skipped)} catalogued endpoint(s) are visible but not executable in J21 database v1"
                )
            if active_request.codes:
                warnings.append(
                    "codes apply only to code-scoped endpoints such as cyq_chips; "
                    "daily and sw_daily still request the full market date range"
                )
        parameters = _request_snapshot(active_request, specs)
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=[spec.target_table for spec, _units in planned],
            work_units=sum(len(units) for _spec, units in planned),
            estimated_api_calls=sum(len(units) for _spec, units in planned),
            parameters=parameters,
            parameter_sources={
                key: active_request.override_source for key in parameters
            },
            warnings=warnings,
        )

    def run(
        self,
        request: TushareJobRequest,
        *,
        runtime: TushareJobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        preflight: JobPreflight | None = None,
    ) -> JobResult:
        active_runtime = runtime or TushareJobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()
        active_preflight = preflight or self.preflight(
            request,
            runtime=active_runtime,
            verify_storage=True,
        )
        if not request.execute:
            return JobResult(
                job=self.job_key,
                status="dry_run",
                run_id=request.resume_run_id,
                parameters=active_preflight.parameters,
                parameter_sources=active_preflight.parameter_sources,
                work_units_total=active_preflight.work_units,
                preflight=active_preflight,
            )

        def report(event: ProgressEvent) -> None:
            try:
                active_reporter.on_event(event)
            except Exception:
                # Rendering and terminal sinks are observational. A broken sink must
                # never stop a committed page or prevent the next endpoint from running.
                return

        def report_api_event(event: TushareApiEvent) -> None:
            report(
                ProgressEvent(
                    "message",
                    self.job_key,
                    0,
                    active_preflight.work_units,
                    unit=event.endpoint,
                    message=_api_event_message(event),
                )
            )

        client = None
        if request.resume_run_id is not None:
            checkpoint = self._load_checkpoint(active_runtime, request.resume_run_id)
            active_request = _resume_request(request, checkpoint)
            specs = _specs_from_checkpoint(checkpoint)
            planned = _plan_specs(specs, active_request)
            _assert_checkpoint_catalog(checkpoint, specs, planned)
            run_id = request.resume_run_id
        else:
            active_request = request
            specs = _select_specs(active_request)
            planned = _plan_specs(specs, active_request)
            contracts = self._verify_storage(active_runtime, planned)
            # Validate the credential/runtime before creating a durable run row.
            # This keeps a missing token from leaving an unresumable "running" run.
            client = active_runtime.client(
                max_retries=active_request.max_retries,
                progress_callback=report_api_event,
            )
            checkpoint = _new_checkpoint(active_request, specs, planned=planned)
            run_id = self._create_run(active_runtime, active_request, specs, checkpoint)

        total_units = sum(len(units) for _spec, units in planned)
        report(
            ProgressEvent(
                "start",
                self.job_key,
                int(checkpoint["counters"]["units_completed"]),
                total_units,
                message=f"run_id={run_id}",
            )
        )

        cursor_done = int(checkpoint["cursor"]["endpoint_index"]) >= len(planned)
        if cursor_done and not bool(checkpoint.get("complete")):
            checkpoint = self._finish(
                active_runtime,
                run_id=run_id,
                checkpoint=checkpoint,
                failures=[
                    _failure_from_json(value)
                    for value in checkpoint.get("failures", [])
                ],
                global_error=None,
            )
        if bool(checkpoint.get("complete")):
            return self._completed_result(
                run_id=run_id,
                request=active_request,
                preflight=active_preflight,
                checkpoint=checkpoint,
                total_units=total_units,
            )

        if request.resume_run_id is not None:
            contracts = self._verify_storage(active_runtime, planned)
        if client is None:
            client = active_runtime.client(
                max_retries=active_request.max_retries,
                progress_callback=report_api_event,
            )
        if request.resume_run_id is not None:
            try:
                with tushare_run_lease(active_runtime.engine, run_id):
                    self._assert_durable_checkpoint(
                        active_runtime,
                        run_id=run_id,
                        expected=checkpoint,
                    )
                    checkpoint = self._mark_resumed_run(
                        active_runtime,
                        run_id=run_id,
                        checkpoint=checkpoint,
                    )
            except TushareRunLeaseCleanupError as error:
                durable = self._load_checkpoint(active_runtime, run_id)
                if durable != checkpoint:
                    raise _RunLeaseRejected(
                        "Resumed Tushare state could not be reconciled after lease cleanup"
                    ) from error
                checkpoint = durable
        failures = [
            _failure_from_json(value) for value in checkpoint.get("failures", [])
        ]
        global_error: str | None = None
        response: TushareResponse | None = None
        invocation_api_calls_start = int(checkpoint["counters"]["api_calls"])
        lease_expected_checkpoint: dict[str, Any] | None = None
        finish_durable_expected: dict[str, Any] | None = None
        pending_audit: _PendingAuditRecord | None = None

        try:
            while int(checkpoint["cursor"]["endpoint_index"]) < len(planned):
                endpoint_index = int(checkpoint["cursor"]["endpoint_index"])
                spec, units = planned[endpoint_index]
                endpoint_failed = False
                while int(checkpoint["cursor"]["unit_index"]) < len(units):
                    unit_index = int(checkpoint["cursor"]["unit_index"])
                    unit = units[unit_index]
                    offset = int(checkpoint["cursor"]["offset"])
                    response = None
                    cleaned: CleanedPage | None = None
                    lease_expected_checkpoint = None
                    try:
                        with tushare_run_lease(active_runtime.engine, run_id):
                            self._assert_durable_checkpoint(
                                active_runtime,
                                run_id=run_id,
                                expected=checkpoint,
                            )
                            _assert_invocation_api_budget(
                                active_request,
                                checkpoint=checkpoint,
                                invocation_api_calls_start=invocation_api_calls_start,
                                client=client,
                            )
                            try:
                                response = client.fetch_page(
                                    unit.page_request(spec, offset=offset)
                                )
                                cleaned = clean_page(spec, response)
                                _assert_page_scope(spec, unit, cleaned)
                                page_signature = _page_signature(response)
                                _assert_fresh_page(
                                    checkpoint,
                                    spec=spec,
                                    signature=page_signature,
                                )
                                page_next_offset = next_page_offset(
                                    spec,
                                    current_offset=offset,
                                    rows_returned=response.rows_returned,
                                )
                            except TushareAuthenticationError as error:
                                failure = _job_failure(spec, unit, error)
                                failures.append(failure)
                                checkpoint = self._save_endpoint_failure(
                                    active_runtime,
                                    run_id=run_id,
                                    checkpoint=checkpoint,
                                    spec=spec,
                                    unit=unit,
                                    error=error,
                                    terminal=True,
                                    failed_units=1,
                                    response=response,
                                )
                                lease_expected_checkpoint = checkpoint
                                global_error = failure.message
                                report(
                                    ProgressEvent(
                                        "unit_failed",
                                        self.job_key,
                                        int(checkpoint["counters"]["units_completed"]),
                                        total_units,
                                        unit=unit.scope_key,
                                        message=_page_failure_message(
                                            spec=spec,
                                            unit=unit,
                                            offset=offset,
                                            fetched=(
                                                response.rows_returned
                                                if response is not None
                                                else 0
                                            ),
                                            cleaned=0,
                                            attempts=int(
                                                checkpoint["counters"]["api_calls"]
                                            ),
                                            error_kind=error.kind,
                                            error_message=failure.message,
                                        ),
                                        counters=_progress_counters(checkpoint),
                                    )
                                )
                                raise _GlobalTushareStop from error
                            except TushareError as error:
                                if response is not None:
                                    error.endpoint = spec.key
                                    error.attempts = response.attempts
                                    error.status_code = response.status_code
                                failure = _job_failure(spec, unit, error)
                                failures.append(failure)
                                checkpoint = self._save_endpoint_failure(
                                    active_runtime,
                                    run_id=run_id,
                                    checkpoint=checkpoint,
                                    spec=spec,
                                    unit=unit,
                                    error=error,
                                    terminal=False,
                                    failed_units=len(units) - unit_index,
                                    response=response,
                                )
                                lease_expected_checkpoint = checkpoint
                                endpoint_failed = True
                                report(
                                    ProgressEvent(
                                        "unit_failed",
                                        self.job_key,
                                        int(checkpoint["counters"]["units_completed"]),
                                        total_units,
                                        unit=unit.scope_key,
                                        message=_page_failure_message(
                                            spec=spec,
                                            unit=unit,
                                            offset=offset,
                                            fetched=(
                                                response.rows_returned
                                                if response is not None
                                                else 0
                                            ),
                                            cleaned=(
                                                cleaned.cleaned_rows
                                                if cleaned is not None
                                                else 0
                                            ),
                                            attempts=int(
                                                checkpoint["counters"]["api_calls"]
                                            ),
                                            error_kind=error.kind,
                                            error_message=failure.message,
                                        ),
                                        counters=_progress_counters(checkpoint),
                                    )
                                )
                            else:
                                next_checkpoint = _advance_success_checkpoint(
                                    checkpoint,
                                    planned=planned,
                                    response=response,
                                    cleaned_rows=cleaned.cleaned_rows,
                                    next_offset=page_next_offset,
                                    page_signature=page_signature,
                                )
                                try:
                                    with external_table_page_transaction(
                                        active_runtime.engine,
                                        spec,
                                    ) as connection:
                                        write_result = write_business_rows(
                                            connection,
                                            spec,
                                            cleaned.rows,
                                            contract=contracts[spec.key],
                                        )
                                        _record_successful_call(
                                            connection,
                                            run_id=run_id,
                                            spec=spec,
                                            unit=unit,
                                            response=response,
                                        )
                                        _apply_write_counts(
                                            next_checkpoint, write_result
                                        )
                                        _save_checkpoint_row(
                                            connection,
                                            run_id=run_id,
                                            checkpoint=next_checkpoint,
                                            status="running",
                                        )
                                    lease_expected_checkpoint = next_checkpoint
                                except (SQLAlchemyError, TushareStorageError) as error:
                                    report(
                                        ProgressEvent(
                                            "unit_failed",
                                            self.job_key,
                                            int(
                                                checkpoint["counters"][
                                                    "units_completed"
                                                ]
                                            ),
                                            total_units,
                                            unit=unit.scope_key,
                                            message=_page_failure_message(
                                                spec=spec,
                                                unit=unit,
                                                offset=offset,
                                                fetched=response.rows_returned,
                                                cleaned=cleaned.cleaned_rows,
                                                attempts=(
                                                    int(
                                                        checkpoint["counters"][
                                                            "api_calls"
                                                        ]
                                                    )
                                                    + response.attempts
                                                ),
                                                error_kind="storage",
                                                error_message=safe_error_message(error),
                                            ),
                                            counters=_progress_counters(checkpoint),
                                        )
                                    )
                                    checkpoint = self._resolve_page_storage_failure(
                                        active_runtime,
                                        run_id=run_id,
                                        checkpoint=checkpoint,
                                        next_checkpoint=next_checkpoint,
                                        spec=spec,
                                        unit=unit,
                                        response=response,
                                        cleaned_rows=cleaned.cleaned_rows,
                                        error=error,
                                    )
                                    raise
                    except _GlobalTushareStop:
                        raise
                    except _InvocationBudgetExhausted:
                        raise
                    except _RunLeaseRejected:
                        raise
                    if endpoint_failed:
                        break
                    checkpoint = next_checkpoint
                    report(
                        ProgressEvent(
                            "message",
                            self.job_key,
                            int(checkpoint["counters"]["units_completed"]),
                            total_units,
                            unit=unit.scope_key,
                            message=_page_message(
                                spec=spec,
                                unit=unit,
                                offset=offset,
                                fetched=response.rows_returned,
                                cleaned=cleaned.cleaned_rows,
                                written=write_result.written_rows,
                                attempts=int(checkpoint["counters"]["api_calls"]),
                            ),
                        )
                    )
                    response = None
                    if page_next_offset is None:
                        report(
                            ProgressEvent(
                                "unit_completed",
                                self.job_key,
                                int(checkpoint["counters"]["units_completed"]),
                                total_units,
                                unit=unit.scope_key,
                                message="committed",
                                counters=_progress_counters(checkpoint),
                            )
                        )
                        # Completing the final unit advances the endpoint cursor.  The
                        # local ``units`` tuple still belongs to the prior endpoint, so
                        # leave this loop before inspecting it again.  Without this
                        # guard a one-unit endpoint restarts at offset zero and consumes
                        # another provider page after it has already completed.
                        if (
                            int(checkpoint["cursor"]["endpoint_index"])
                            != endpoint_index
                        ):
                            break
                if endpoint_failed:
                    continue
        except _RunLeaseRejected:
            raise
        except _GlobalTushareStop:
            pass
        except _InvocationBudgetExhausted as error:
            global_error = str(error)
        except _PendingCheckpointPersistenceError as error:
            checkpoint = deepcopy(error.next_checkpoint)
            finish_durable_expected = deepcopy(error.prior_checkpoint)
            pending_audit = error.audit_record
            global_error = safe_error_message(error)
            storage_failure = JobFailure("database", error.kind, global_error)
            failures = [
                _failure_from_json(value) for value in checkpoint.get("failures", [])
            ]
            if not any(
                failure.category == storage_failure.category
                and failure.message == storage_failure.message
                for failure in failures
            ):
                failures.append(storage_failure)
        except TushareRunLeaseCleanupError as error:
            durable = self._load_checkpoint(active_runtime, run_id)
            if (
                lease_expected_checkpoint is None
                or durable != lease_expected_checkpoint
            ):
                raise _RunLeaseRejected(
                    "Tushare page state could not be reconciled after lease cleanup"
                ) from error
            checkpoint = durable
            global_error = safe_error_message(error)
            storage_failure = JobFailure("database", error.kind, global_error)
            failures = [
                _failure_from_json(value) for value in checkpoint.get("failures", [])
            ]
            failures.append(storage_failure)
        except TusharePostCommitStorageError as error:
            global_error = safe_error_message(error)
            storage_failure = JobFailure("database", error.kind, global_error)
            failures = [
                _failure_from_json(value) for value in checkpoint.get("failures", [])
            ]
            failures.append(storage_failure)
        except (SQLAlchemyError, TushareStorageError) as error:
            global_error = safe_error_message(error)
            storage_failure = JobFailure("database", "storage", global_error)
            failures = [
                _failure_from_json(value) for value in checkpoint.get("failures", [])
            ]
            if not any(
                failure.category == storage_failure.category
                and failure.message == storage_failure.message
                for failure in failures
            ):
                failures.append(storage_failure)

        checkpoint = self._finish(
            active_runtime,
            run_id=run_id,
            checkpoint=checkpoint,
            failures=failures,
            global_error=global_error,
            durable_expected=finish_durable_expected,
            pending_audit=pending_audit,
        )
        status = str(checkpoint["status"])
        report(
            ProgressEvent(
                "finish",
                self.job_key,
                int(checkpoint["counters"]["units_completed"]),
                total_units,
                message=status,
                counters=_progress_counters(checkpoint),
            )
        )
        return _job_result(
            run_id=run_id,
            request=active_request,
            preflight=active_preflight,
            checkpoint=checkpoint,
            total_units=total_units,
            failures=failures,
            error_message=global_error,
        )

    def _create_run(
        self,
        runtime: TushareJobRuntime,
        request: TushareJobRequest,
        specs: tuple[EndpointSpec, ...],
        checkpoint: dict[str, Any],
    ) -> int:
        target_table = (
            specs[0].target_table if len(specs) == 1 else "multiple_hq_tables"
        )
        with runtime.engine.begin() as connection:
            result = connection.execute(
                ingestion_task_run.insert().values(
                    job_name="tushare_endpoint",
                    market="CN",
                    source="TUSHARE",
                    target_schema=TARGET_SCHEMA,
                    target_table=target_table,
                    status="running",
                    date_from=request.date_from,
                    date_to=request.date_to,
                    started_at=datetime.now(UTC),
                    checkpoint_json=checkpoint,
                )
            )
            return int(result.inserted_primary_key[0])

    def _load_checkpoint(
        self,
        runtime: TushareJobRuntime,
        run_id: int,
    ) -> dict[str, Any]:
        with runtime.engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        ingestion_task_run.c.source,
                        ingestion_task_run.c.job_name,
                        ingestion_task_run.c.checkpoint_json,
                    ).where(ingestion_task_run.c.run_id == run_id)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ValueError(f"Tushare resume run_id {run_id} does not exist")
        if row["source"] != "TUSHARE" or row["job_name"] != "tushare_endpoint":
            raise ValueError(f"run_id {run_id} is not a Tushare endpoint run")
        checkpoint = row["checkpoint_json"]
        if (
            not isinstance(checkpoint, dict)
            or checkpoint.get("version") != CHECKPOINT_VERSION
        ):
            raise ValueError(f"run_id {run_id} has an unsupported Tushare checkpoint")
        return _normalize_checkpoint(checkpoint)

    def _verify_storage(
        self,
        runtime: TushareJobRuntime,
        planned: tuple[tuple[EndpointSpec, tuple[EndpointUnit, ...]], ...],
    ) -> dict[str, ExternalTableContract]:
        with runtime.engine.connect() as connection:
            _verify_atomic_system_tables(connection)
            return {
                spec.key: verify_external_table(connection, spec)
                for spec, _units in planned
            }

    def _mark_resumed_run(
        self,
        runtime: TushareJobRuntime,
        *,
        run_id: int,
        checkpoint: dict[str, Any],
    ) -> dict[str, Any]:
        """Reopen an incomplete run only after storage and client preflight succeeds."""
        next_checkpoint = deepcopy(checkpoint)
        next_checkpoint["status"] = "running"
        next_checkpoint["complete"] = False
        with runtime.engine.begin() as connection:
            connection.execute(
                update(ingestion_task_run)
                .where(ingestion_task_run.c.run_id == run_id)
                .values(
                    status="running",
                    finished_at=None,
                    error_message=None,
                    checkpoint_json=next_checkpoint,
                )
            )
        return next_checkpoint

    def _assert_durable_checkpoint(
        self,
        runtime: TushareJobRuntime,
        *,
        run_id: int,
        expected: Mapping[str, Any],
    ) -> None:
        """Reject a stale executor before it can consume another provider call."""
        durable = self._load_checkpoint(runtime, run_id)
        if durable != expected:
            raise _RunLeaseRejected(
                "Tushare run state changed in another executor; reload and resume the run"
            )

    def _save_endpoint_failure(
        self,
        runtime: TushareJobRuntime,
        *,
        run_id: int,
        checkpoint: dict[str, Any],
        spec: EndpointSpec,
        unit: EndpointUnit,
        error: TushareError,
        terminal: bool,
        failed_units: int,
        response: TushareResponse | None,
    ) -> dict[str, Any]:
        next_checkpoint = deepcopy(checkpoint)
        attempts = error.attempts or 1
        next_checkpoint["counters"]["api_calls"] += attempts
        if response is not None:
            next_checkpoint["counters"]["rows_fetched"] += response.rows_returned
        next_checkpoint["counters"]["units_failed"] += failed_units
        next_checkpoint["failures"].append(
            {
                "unit": f"{spec.key}:{unit.scope_key}",
                "category": error.kind,
                "message": safe_error_message(error),
            }
        )
        if terminal:
            next_checkpoint["status"] = "failed"
        else:
            next_checkpoint["cursor"]["endpoint_index"] += 1
            next_checkpoint["cursor"]["unit_index"] = 0
            next_checkpoint["cursor"]["offset"] = 0
            next_checkpoint["page_signatures"] = []
        try:
            with runtime.engine.begin() as connection:
                _record_failed_call(
                    connection,
                    run_id=run_id,
                    spec=spec,
                    unit=unit,
                    error=error,
                    response=response,
                )
                _save_checkpoint_row(
                    connection,
                    run_id=run_id,
                    checkpoint=next_checkpoint,
                    status="failed" if terminal else "running",
                )
        except (SQLAlchemyError, TushareStorageError) as commit_error:
            durable = self._load_checkpoint(runtime, run_id)
            if durable == next_checkpoint:
                return durable
            if durable != checkpoint:
                raise _RunLeaseRejected(
                    "Tushare run changed while provider failure state was being committed"
                ) from commit_error
            raise _PendingCheckpointPersistenceError(
                "Provider failure state was not committed; no consumed usage was discarded",
                prior_checkpoint=checkpoint,
                next_checkpoint=next_checkpoint,
                audit_record=_PendingAuditRecord(
                    spec=spec,
                    unit=unit,
                    status_code=error.status_code,
                    success=False,
                    attempts=attempts,
                    rows_returned=response.rows_returned if response is not None else 0,
                    error_message=safe_error_message(error),
                ),
            ) from commit_error
        return next_checkpoint

    def _resolve_page_storage_failure(
        self,
        runtime: TushareJobRuntime,
        *,
        run_id: int,
        checkpoint: dict[str, Any],
        next_checkpoint: dict[str, Any],
        spec: EndpointSpec,
        unit: EndpointUnit,
        response: TushareResponse,
        cleaned_rows: int,
        error: BaseException,
    ) -> dict[str, Any]:
        """Resolve one page's commit outcome while the caller still owns the run lease."""
        durable = self._load_checkpoint(runtime, run_id)
        if durable == next_checkpoint:
            return durable
        if durable != checkpoint:
            raise _RunLeaseRejected(
                "Tushare run changed while a page commit was being resolved"
            ) from error
        if isinstance(error, TusharePostCommitStorageError):
            raise TushareStorageError(
                "A committed Tushare page could not be found in its durable checkpoint"
            ) from error
        return self._save_uncommitted_page_usage(
            runtime,
            run_id=run_id,
            checkpoint=checkpoint,
            spec=spec,
            unit=unit,
            response=response,
            cleaned_rows=cleaned_rows,
            error=error,
        )

    def _save_uncommitted_page_usage(
        self,
        runtime: TushareJobRuntime,
        *,
        run_id: int,
        checkpoint: dict[str, Any],
        spec: EndpointSpec,
        unit: EndpointUnit,
        response: TushareResponse,
        cleaned_rows: int,
        error: BaseException,
    ) -> dict[str, Any]:
        """Record consumed provider work without advancing a rolled-back page cursor."""
        next_checkpoint = deepcopy(checkpoint)
        counters = next_checkpoint["counters"]
        counters["rows_fetched"] += response.rows_returned
        counters["rows_cleaned"] += cleaned_rows
        counters["rows_rejected"] += response.rows_returned - cleaned_rows
        counters["api_calls"] += response.attempts
        failure = JobFailure("database", "storage", safe_error_message(error))
        next_checkpoint["failures"].append(_failure_to_json(failure))
        try:
            with runtime.engine.begin() as connection:
                _record_call(
                    connection,
                    run_id=run_id,
                    spec=spec,
                    unit=unit,
                    status_code=response.status_code,
                    success=False,
                    attempts=response.attempts,
                    rows_returned=response.rows_returned,
                    error_message=failure.message,
                )
                _save_checkpoint_row(
                    connection,
                    run_id=run_id,
                    checkpoint=next_checkpoint,
                    status="running",
                )
        except (SQLAlchemyError, TushareStorageError) as commit_error:
            durable = self._load_checkpoint(runtime, run_id)
            if durable == next_checkpoint:
                return durable
            if durable != checkpoint:
                raise _RunLeaseRejected(
                    "Tushare run changed while provider usage was being committed"
                ) from commit_error
            raise _PendingCheckpointPersistenceError(
                "Provider usage was not committed; no consumed usage was discarded",
                prior_checkpoint=checkpoint,
                next_checkpoint=next_checkpoint,
                audit_record=_PendingAuditRecord(
                    spec=spec,
                    unit=unit,
                    status_code=response.status_code,
                    success=False,
                    attempts=response.attempts,
                    rows_returned=response.rows_returned,
                    error_message=failure.message,
                ),
            ) from commit_error
        return next_checkpoint

    def _finish(
        self,
        runtime: TushareJobRuntime,
        *,
        run_id: int,
        checkpoint: dict[str, Any],
        failures: list[JobFailure],
        global_error: str | None,
        durable_expected: Mapping[str, Any] | None = None,
        pending_audit: _PendingAuditRecord | None = None,
    ) -> dict[str, Any]:
        final_checkpoint: dict[str, Any] | None = None
        expected_checkpoint = (
            checkpoint if durable_expected is None else durable_expected
        )
        try:
            with tushare_run_lease(runtime.engine, run_id):
                self._assert_durable_checkpoint(
                    runtime,
                    run_id=run_id,
                    expected=expected_checkpoint,
                )
                final_checkpoint = deepcopy(checkpoint)
                cursor_done = int(final_checkpoint["cursor"]["endpoint_index"]) >= len(
                    final_checkpoint["endpoint_keys"]
                )
                final_checkpoint["complete"] = cursor_done and global_error is None
                final_checkpoint["failures"] = [
                    _failure_to_json(failure) for failure in failures
                ]
                has_committed_work = bool(
                    final_checkpoint["counters"].get("pages_committed", 0)
                    or final_checkpoint["counters"]["units_completed"]
                )
                if global_error is not None:
                    status = "partial_failed" if has_committed_work else "failed"
                elif failures:
                    status = "partial_failed" if has_committed_work else "failed"
                else:
                    status = "success"
                final_checkpoint["status"] = status
                try:
                    with runtime.engine.begin() as connection:
                        if pending_audit is not None:
                            _record_call(
                                connection,
                                run_id=run_id,
                                spec=pending_audit.spec,
                                unit=pending_audit.unit,
                                status_code=pending_audit.status_code,
                                success=pending_audit.success,
                                attempts=pending_audit.attempts,
                                rows_returned=pending_audit.rows_returned,
                                error_message=pending_audit.error_message,
                            )
                        _save_checkpoint_row(
                            connection,
                            run_id=run_id,
                            checkpoint=final_checkpoint,
                            status=status,
                            finished=True,
                            error_message=global_error,
                        )
                except (SQLAlchemyError, TushareStorageError) as commit_error:
                    durable = self._load_checkpoint(runtime, run_id)
                    if durable == final_checkpoint:
                        return durable
                    if durable != expected_checkpoint:
                        raise _RunLeaseRejected(
                            "Tushare run changed while final status was being committed"
                        ) from commit_error
                    raise
                return final_checkpoint
        except TushareRunLeaseCleanupError as error:
            durable = self._load_checkpoint(runtime, run_id)
            if final_checkpoint is not None and durable == final_checkpoint:
                return durable
            raise _RunLeaseRejected(
                "Final Tushare state could not be reconciled after lease cleanup"
            ) from error

    def _completed_result(
        self,
        *,
        run_id: int,
        request: TushareJobRequest,
        preflight: JobPreflight,
        checkpoint: dict[str, Any],
        total_units: int,
    ) -> JobResult:
        return _job_result(
            run_id=run_id,
            request=request,
            preflight=preflight,
            checkpoint=checkpoint,
            total_units=total_units,
            failures=[
                _failure_from_json(value) for value in checkpoint.get("failures", [])
            ],
            error_message=None,
        )


class _GlobalTushareStop(RuntimeError):
    pass


class _RunLeaseRejected(TushareStorageError):
    """A second or stale executor was stopped before consuming provider budget."""


class _InvocationBudgetExhausted(RuntimeError):
    """This explicit invocation reached its provider-attempt ceiling."""


@dataclass(frozen=True)
class _PendingAuditRecord:
    spec: EndpointSpec
    unit: EndpointUnit
    status_code: int | None
    success: bool
    attempts: int
    rows_returned: int
    error_message: str | None


class _PendingCheckpointPersistenceError(TushareStorageError):
    """Consumed provider work whose first checkpoint transaction did not persist."""

    kind = "storage_checkpoint_pending"

    def __init__(
        self,
        message: str,
        *,
        prior_checkpoint: Mapping[str, Any],
        next_checkpoint: Mapping[str, Any],
        audit_record: _PendingAuditRecord,
    ) -> None:
        super().__init__(message)
        self.prior_checkpoint = deepcopy(dict(prior_checkpoint))
        self.next_checkpoint = deepcopy(dict(next_checkpoint))
        self.audit_record = audit_record


def _select_specs(request: TushareJobRequest) -> tuple[EndpointSpec, ...]:
    selectors = sum(
        (
            request.endpoint is not None,
            request.category is not None,
            request.all_endpoints,
        )
    )
    if selectors != 1:
        raise ValueError("select exactly one of endpoint, category, or all_endpoints")
    if request.endpoint is not None:
        spec = get_endpoint_spec(request.endpoint)
        if not spec.executable:
            reason = spec.capability.reason or "endpoint is disabled"
            raise ValueError(f"Tushare endpoint {spec.key} is not executable: {reason}")
        return (spec,)
    if request.category is not None:
        specs = tuple(
            spec for spec in iter_endpoint_specs(request.category) if spec.executable
        )
        if not specs:
            raise ValueError(
                f"Tushare category {request.category} has no executable endpoints"
            )
        return specs
    specs = default_historical_endpoint_specs()
    if not specs:
        raise ValueError("Tushare default endpoint selection is empty")
    return specs


def _skipped_specs(request: TushareJobRequest) -> tuple[EndpointSpec, ...]:
    if request.category is not None:
        return tuple(
            spec
            for spec in iter_endpoint_specs(request.category)
            if not spec.executable
        )
    if request.all_endpoints:
        selected = {spec.key for spec in default_historical_endpoint_specs()}
        return tuple(spec for spec in iter_endpoint_specs() if spec.key not in selected)
    return ()


def _plan_specs(
    specs: tuple[EndpointSpec, ...],
    request: TushareJobRequest,
) -> tuple[tuple[EndpointSpec, tuple[EndpointUnit, ...]], ...]:
    if (request.category is not None or request.all_endpoints) and request.params:
        raise ValueError("--param is available only with one --endpoint selection")
    code_scoped = tuple(
        spec.key for spec in specs if spec.scope_kind == "code_date_range"
    )
    params_supply_code = request.endpoint is not None and any(
        name.casefold() == "ts_code" for name in request.params
    )
    if code_scoped and not request.codes and not params_supply_code:
        names = ", ".join(code_scoped)
        raise ValueError(
            f"--codes is required because this selection includes: {names}"
        )
    planned: list[tuple[EndpointSpec, tuple[EndpointUnit, ...]]] = []
    for spec in specs:
        if spec.key in {"daily", "sw_daily", "cyq_chips"}:
            supplied_names = {name.casefold() for name in request.params}
            has_exact_date = "trade_date" in supplied_names
            has_structured_range = (
                request.date_from is not None and request.date_to is not None
            )
            has_parameter_range = {"start_date", "end_date"}.issubset(supplied_names)
            if not (has_exact_date or has_structured_range or has_parameter_range):
                raise ValueError(
                    f"Tushare endpoint {spec.key} requires --from/--to or --param trade_date"
                )
        supports_range = {
            "start_date",
            "end_date",
        }.issubset(spec.request_params)
        endpoint_codes = (
            request.codes
            if request.endpoint is not None or spec.scope_kind == "code_date_range"
            else ()
        )
        plan_request = EndpointPlanRequest(
            date_from=request.date_from if supports_range else None,
            date_to=request.date_to if supports_range else None,
            codes=endpoint_codes,
            params=request.params if request.endpoint is not None else {},
        )
        planned.append((spec, plan_endpoint_units(spec, plan_request)))
    return tuple(planned)


def _request_snapshot(
    request: TushareJobRequest,
    specs: tuple[EndpointSpec, ...],
) -> dict[str, Any]:
    return {
        "endpoint_keys": [spec.key for spec in specs],
        "selector": (
            {"endpoint": request.endpoint}
            if request.endpoint is not None
            else {"category": request.category}
            if request.category is not None
            else {"all": True}
        ),
        "date_from": request.date_from.isoformat() if request.date_from else None,
        "date_to": request.date_to.isoformat() if request.date_to else None,
        "codes": list(request.codes),
        "params": _request_params_snapshot(request, specs),
        "refresh": request.refresh,
        "max_retries": request.max_retries,
        "max_api_calls": _request_api_budget(request),
    }


def _request_params_snapshot(
    request: TushareJobRequest,
    specs: tuple[EndpointSpec, ...],
) -> dict[str, object]:
    """Return validated, JSON-safe caller parameters for durable resume."""

    if not request.params:
        return {}
    if request.endpoint is None or len(specs) != 1:
        raise ValueError("Tushare params require one endpoint selection")
    normalized = validate_endpoint_params(specs[0], request.params)
    return {
        name: str(value) if isinstance(value, Decimal) else value
        for name, value in sorted(normalized.items())
    }


def _new_checkpoint(
    request: TushareJobRequest,
    specs: tuple[EndpointSpec, ...],
    *,
    planned: tuple[tuple[EndpointSpec, tuple[EndpointUnit, ...]], ...] | None = None,
) -> dict[str, Any]:
    active_plan = planned if planned is not None else _plan_specs(specs, request)
    return {
        "version": CHECKPOINT_VERSION,
        "request": _request_snapshot(request, specs),
        "endpoint_keys": [spec.key for spec in specs],
        "endpoint_contracts": _endpoint_contracts(specs),
        "planned_units": _planned_units_snapshot(active_plan),
        "cursor": {"endpoint_index": 0, "unit_index": 0, "offset": 0},
        "page_signatures": [],
        "counters": {
            "rows_fetched": 0,
            "rows_cleaned": 0,
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_rejected": 0,
            "api_calls": 0,
            "pages_committed": 0,
            "units_completed": 0,
            "units_failed": 0,
        },
        "failures": [],
        "complete": False,
        "status": "running",
    }


def _normalize_checkpoint(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize optional counters from early version-2 checkpoints."""
    result = deepcopy(dict(checkpoint))
    counters = result.get("counters")
    if not isinstance(counters, dict):
        raise ValueError("stored Tushare checkpoint counters are invalid")
    if "pages_committed" not in counters:
        cursor = result.get("cursor")
        progressed_cursor = isinstance(cursor, dict) and (
            int(cursor.get("offset", 0)) > 0
            or int(cursor.get("unit_index", 0)) > 0
            or int(cursor.get("endpoint_index", 0)) > 0
        )
        committed_rows = int(counters.get("rows_inserted", 0)) + int(
            counters.get("rows_updated", 0)
        )
        counters["pages_committed"] = int(
            progressed_cursor
            or int(counters.get("units_completed", 0)) > 0
            or committed_rows > 0
        )
    signatures = result.setdefault("page_signatures", [])
    if not isinstance(signatures, list) or any(
        not isinstance(value, str) or len(value) != 64 for value in signatures
    ):
        raise ValueError("stored Tushare page signatures are invalid")
    return result


def _endpoint_contracts(specs: tuple[EndpointSpec, ...]) -> list[dict[str, object]]:
    """Persist practical paging/write facts so resume cannot follow a changed catalog."""
    return [
        {
            "key": spec.key,
            "api_name": spec.api_name,
            "target_table": spec.target_table,
            "page_limit": spec.page_limit,
            "pagination_kind": spec.pagination.kind,
            "scope_kind": spec.scope_kind,
            "fields": list(spec.fields),
            "business_key": list(spec.business_key),
            "column_types": dict(sorted(spec.column_types.items())),
            "text_min_lengths": dict(sorted(spec.text_min_lengths.items())),
            "nullable_columns": sorted(spec.nullable_columns),
            "field_aliases": dict(sorted(spec.field_aliases.items())),
            "fixed_params": _checkpoint_mapping(spec.fixed_params),
            "request_params": [
                {
                    "name": name,
                    "kind": definition.kind,
                    "required": definition.required,
                    "choices": list(definition.choices),
                }
                for name, definition in spec.request_params.items()
            ],
            "fanouts": [
                {
                    "parameter": fanout.parameter,
                    "values": list(fanout.values),
                    "fixed_params": _checkpoint_mapping(fanout.fixed_params),
                }
                for fanout in spec.fanouts
            ],
        }
        for spec in specs
    ]


def _planned_units_snapshot(
    planned: tuple[tuple[EndpointSpec, tuple[EndpointUnit, ...]], ...],
) -> list[dict[str, object]]:
    return [
        {
            "endpoint_key": spec.key,
            "units": [
                {
                    "scope_key": unit.scope_key,
                    "params": _checkpoint_mapping(unit.params),
                    "page_limit": unit.page_limit,
                }
                for unit in units
            ],
        }
        for spec, units in planned
    ]


def _checkpoint_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {name: _checkpoint_scalar(values[name]) for name in sorted(values)}


def _checkpoint_scalar(value: object) -> object:
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise ValueError(
        f"Tushare checkpoint value has unsupported type: {type(value).__name__}"
    )


def _request_api_budget(request: TushareJobRequest) -> int:
    return request.max_api_calls or DEFAULT_MAX_API_CALLS


def _assert_checkpoint_catalog(
    checkpoint: Mapping[str, Any],
    specs: tuple[EndpointSpec, ...],
    planned: tuple[tuple[EndpointSpec, tuple[EndpointUnit, ...]], ...],
) -> None:
    expected_keys = [spec.key for spec in specs]
    if checkpoint.get("endpoint_keys") != expected_keys:
        raise ValueError(
            "stored Tushare endpoint order no longer matches the selected catalog"
        )
    if checkpoint.get("endpoint_contracts") != _endpoint_contracts(specs):
        raise ValueError(
            "stored Tushare endpoint contract no longer matches the current catalog"
        )
    if checkpoint.get("planned_units") != _planned_units_snapshot(planned):
        raise ValueError(
            "stored Tushare execution units no longer match the current plan"
        )


def _specs_from_checkpoint(checkpoint: Mapping[str, Any]) -> tuple[EndpointSpec, ...]:
    """Resolve the exact stored order so catalog expansion cannot move a resume cursor."""
    values = checkpoint.get("endpoint_keys")
    if not isinstance(values, list) or not values:
        raise ValueError("stored Tushare endpoint order is missing")
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("stored Tushare endpoint order is invalid")
    if len(values) != len(set(values)):
        raise ValueError("stored Tushare endpoint order contains duplicates")
    request = checkpoint.get("request")
    if not isinstance(request, dict) or request.get("endpoint_keys") != values:
        raise ValueError("stored Tushare request endpoint order is inconsistent")
    specs = tuple(get_endpoint_spec(value) for value in values)
    if any(not spec.executable for spec in specs):
        raise ValueError("stored Tushare endpoint is no longer executable")
    return specs


def _resume_request(
    request: TushareJobRequest, checkpoint: Mapping[str, Any]
) -> TushareJobRequest:
    stored = checkpoint.get("request")
    if not isinstance(stored, dict):
        raise ValueError("Tushare checkpoint request is missing")
    selector = stored.get("selector")
    if not isinstance(selector, dict):
        raise ValueError("Tushare checkpoint selector is invalid")
    stored_api_budget = _optional_positive_int(
        stored.get("max_api_calls"), "max_api_calls"
    )
    if stored_api_budget is None:
        stored_api_budget = DEFAULT_MAX_API_CALLS
    if request.max_api_calls is not None and request.max_api_calls != stored_api_budget:
        raise ValueError("resume max_api_calls must match the stored Tushare run")
    stored_params = stored.get("params", {})
    if not isinstance(stored_params, dict) or any(
        not isinstance(name, str) for name in stored_params
    ):
        raise ValueError("stored Tushare params are invalid")
    restored = TushareJobRequest(
        endpoint=selector.get("endpoint"),
        category=selector.get("category"),
        all_endpoints=selector.get("all") is True,
        date_from=_optional_date(stored.get("date_from")),
        date_to=_optional_date(stored.get("date_to")),
        codes=tuple(stored.get("codes", ())),
        params=stored_params,
        refresh=stored.get("refresh") is True,
        resume_run_id=request.resume_run_id,
        max_retries=(
            request.max_retries
            if request.max_retries is not None
            else _optional_nonnegative_int(stored.get("max_retries"), "max_retries")
        ),
        max_api_calls=stored_api_budget,
        execute=request.execute,
        override_source=request.override_source,
    )
    supplied_scope = any(
        (
            request.endpoint is not None,
            request.category is not None,
            request.all_endpoints,
            request.date_from is not None,
            request.date_to is not None,
            bool(request.codes),
            bool(request.params),
            request.refresh,
        )
    )
    if supplied_scope:
        supplied = _request_snapshot(request, _select_specs(request))
        restored_snapshot = _request_snapshot(restored, _select_specs(restored))
        for key in (
            "endpoint_keys",
            "selector",
            "date_from",
            "date_to",
            "codes",
            "params",
            "refresh",
        ):
            if supplied[key] != restored_snapshot[key]:
                raise ValueError(
                    f"resume parameter {key} does not match the stored Tushare run"
                )
    return restored


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("stored Tushare date is invalid")
    return date.fromisoformat(value)


def _optional_nonnegative_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"stored Tushare {label} is invalid")
    return value


def _optional_positive_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"stored Tushare {label} is invalid")
    return value


def _assert_invocation_api_budget(
    request: TushareJobRequest,
    *,
    checkpoint: Mapping[str, Any],
    invocation_api_calls_start: int,
    client: object,
) -> None:
    max_retries = getattr(client, "max_retries", 0)
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or max_retries < 0
    ):
        raise TushareStorageError("Tushare client exposes an invalid retry budget")
    consumed = int(checkpoint["counters"]["api_calls"]) - invocation_api_calls_start
    reserved_attempts = max_retries + 1
    if consumed + reserved_attempts > _request_api_budget(request):
        raise _InvocationBudgetExhausted(
            "Tushare invocation API-call budget reached before the next provider request; "
            "resume the same run to continue"
        )


def _advance_success_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    planned: tuple[tuple[EndpointSpec, tuple[EndpointUnit, ...]], ...],
    response: TushareResponse,
    cleaned_rows: int,
    next_offset: int | None,
    page_signature: str | None = None,
) -> dict[str, Any]:
    result = deepcopy(checkpoint)
    counters = result["counters"]
    counters["rows_fetched"] += response.rows_returned
    counters["rows_cleaned"] += cleaned_rows
    counters["rows_rejected"] += response.rows_returned - cleaned_rows
    counters["api_calls"] += response.attempts
    counters["pages_committed"] = int(counters.get("pages_committed", 0)) + 1
    cursor = result["cursor"]
    if next_offset is not None:
        if page_signature is None:
            raise ValueError("continued Tushare pages require a page signature")
        result.setdefault("page_signatures", []).append(page_signature)
        cursor["offset"] = next_offset
        return result
    counters["units_completed"] += 1
    cursor["unit_index"] += 1
    cursor["offset"] = 0
    result["page_signatures"] = []
    endpoint_index = int(cursor["endpoint_index"])
    if int(cursor["unit_index"]) >= len(planned[endpoint_index][1]):
        cursor["endpoint_index"] += 1
        cursor["unit_index"] = 0
    return result


def _page_signature(response: TushareResponse) -> str:
    """Return an order-independent fingerprint used only to stop paging loops."""

    try:
        encoded_rows = sorted(
            json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            for item in response.items
        )
        payload = json.dumps(
            {"fields": response.fields, "rows": encoded_rows},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise TushareDataError("Tushare page cannot be fingerprinted safely") from error
    return hashlib.sha256(payload).hexdigest()


def _assert_fresh_page(
    checkpoint: Mapping[str, Any],
    *,
    spec: EndpointSpec,
    signature: str,
) -> None:
    seen = checkpoint.get("page_signatures", [])
    if not isinstance(seen, list):
        raise TushareDataError("stored Tushare page signatures are invalid")
    if signature in seen:
        raise TushareDataError(
            f"Tushare endpoint {spec.key} repeated an earlier page; pagination stopped"
        )


def _assert_page_scope(
    spec: EndpointSpec,
    unit: EndpointUnit,
    cleaned: CleanedPage,
) -> None:
    """Reject provider rows that are observably outside the requested unit."""

    exact_params = {
        name: value
        for name, value in unit.params.items()
        if name not in {"start_date", "end_date"}
    }
    start = _scope_date(unit.params.get("start_date"), label="start_date")
    end = _scope_date(unit.params.get("end_date"), label="end_date")
    for row_number, row in enumerate(cleaned.rows):
        for name, expected in exact_params.items():
            if name not in row:
                continue
            actual = row[name]
            if name == "ts_code" and isinstance(expected, str):
                matches = actual in expected.split(",")
            elif isinstance(actual, date):
                expected_date = _scope_date(expected, label=name)
                matches = expected_date == actual
            else:
                matches = actual == expected
            if not matches:
                raise TushareDataError(
                    f"Tushare endpoint {spec.key} returned row {row_number} "
                    f"outside requested {name} scope"
                )

        if start is None and end is None:
            continue
        observed_dates = [
            (name, row[name]) for name in ("trade_date", "cal_date") if name in row
        ]
        for name, value in observed_dates:
            if (
                not isinstance(value, date)
                or (start is not None and value < start)
                or (end is not None and value > end)
            ):
                raise TushareDataError(
                    f"Tushare endpoint {spec.key} returned row {row_number} "
                    f"outside requested date range in {name}"
                )


def _scope_date(value: object, *, label: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for format_string in ("%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, format_string).date()
            except ValueError:
                continue
    raise TushareDataError(f"Tushare {label} scope is not a valid date")


def _verify_atomic_system_tables(connection: Connection) -> None:
    """Require one real transaction for business rows, audit, and checkpoint."""

    rows = connection.execute(_SYSTEM_TABLE_ENGINES).mappings().all()
    engines = {
        str(row["table_name"]): str(row["engine"]).upper()
        for row in rows
        if row["engine"] is not None
    }
    missing = sorted(_ATOMIC_SYSTEM_TABLES - set(engines))
    if missing:
        raise TushareStorageError(
            "required transactional system table(s) are missing: " + ", ".join(missing)
        )
    unsafe = sorted(name for name, engine in engines.items() if engine != "INNODB")
    if unsafe:
        raise TushareStorageError(
            "Tushare audit/checkpoint tables must use InnoDB: " + ", ".join(unsafe)
        )


def _apply_write_counts(checkpoint: dict[str, Any], result: Any) -> None:
    checkpoint["counters"]["rows_inserted"] += result.inserted_rows
    checkpoint["counters"]["rows_updated"] += result.updated_rows


def _save_checkpoint_row(
    connection: Connection,
    *,
    run_id: int,
    checkpoint: Mapping[str, Any],
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
    connection.execute(
        update(ingestion_task_run)
        .where(ingestion_task_run.c.run_id == run_id)
        .values(**values)
    )


def _record_successful_call(
    connection: Connection,
    *,
    run_id: int,
    spec: EndpointSpec,
    unit: EndpointUnit,
    response: TushareResponse,
) -> None:
    _record_call(
        connection,
        run_id=run_id,
        spec=spec,
        unit=unit,
        status_code=response.status_code,
        success=True,
        attempts=response.attempts,
        rows_returned=response.rows_returned,
        error_message=None,
    )


def _record_failed_call(
    connection: Connection,
    *,
    run_id: int,
    spec: EndpointSpec,
    unit: EndpointUnit,
    error: TushareError,
    response: TushareResponse | None,
) -> None:
    _record_call(
        connection,
        run_id=run_id,
        spec=spec,
        unit=unit,
        status_code=error.status_code,
        success=False,
        attempts=error.attempts or 1,
        rows_returned=response.rows_returned if response is not None else 0,
        error_message=safe_error_message(error),
    )


def _record_call(
    connection: Connection,
    *,
    run_id: int,
    spec: EndpointSpec,
    unit: EndpointUnit,
    status_code: int | None,
    success: bool,
    attempts: int,
    rows_returned: int,
    error_message: str | None,
) -> None:
    connection.execute(
        api_call_log.insert().values(
            run_id=run_id,
            source="TUSHARE",
            endpoint=spec.key,
            provider_symbol=_provider_symbol_for_audit(unit.params.get("ts_code")),
            date_from=_unit_date(
                unit.params.get("start_date") or unit.params.get("trade_date")
            ),
            date_to=_unit_date(
                unit.params.get("end_date") or unit.params.get("trade_date")
            ),
            status_code=status_code,
            success=success,
            retry_count=max(0, attempts - 1),
            rows_returned=rows_returned,
            error_message=error_message,
            called_at=datetime.now(UTC),
            duration_ms=None,
        )
    )


def _provider_symbol_for_audit(value: object) -> str | None:
    """Store one provider symbol only; full multi-code scope stays in the checkpoint."""

    if not isinstance(value, str) or not value or "," in value or len(value) > 128:
        return None
    return value


def _unit_date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return None
    return datetime.strptime(value, "%Y%m%d").date()


def _job_failure(
    spec: EndpointSpec, unit: EndpointUnit, error: TushareError
) -> JobFailure:
    return JobFailure(
        unit=f"{spec.key}:{unit.scope_key}",
        category=error.kind,
        message=safe_error_message(error),
    )


def _failure_from_json(value: object) -> JobFailure:
    if not isinstance(value, dict):
        return JobFailure("unknown", "checkpoint", "invalid stored failure")
    return JobFailure(
        str(value.get("unit", "unknown")),
        str(value.get("category", "unknown")),
        str(value.get("message", "unknown failure")),
    )


def _failure_to_json(value: JobFailure) -> dict[str, str]:
    return {
        "unit": value.unit,
        "category": value.category,
        "message": value.message,
    }


def _progress_counters(checkpoint: Mapping[str, Any]) -> dict[str, int]:
    counters = checkpoint["counters"]
    return {
        "fetched": int(counters["rows_fetched"]),
        "inserted": int(counters["rows_inserted"]),
        "updated": int(counters["rows_updated"]),
        "failed": int(counters["units_failed"]),
        "api_calls": int(counters["api_calls"]),
        "pages_committed": int(counters.get("pages_committed", 0)),
    }


def _page_message(
    *,
    spec: EndpointSpec,
    unit: EndpointUnit,
    offset: int,
    fetched: int,
    cleaned: int,
    written: int,
    attempts: int,
) -> str:
    code = unit.params.get("ts_code", "-")
    date_scope = (
        unit.params.get("trade_date")
        or f"{unit.params.get('start_date', '-')}..{unit.params.get('end_date', '-')}"
    )
    return (
        f"endpoint={spec.key} table={spec.target_table} code={code} "
        f"date_scope={date_scope} offset={offset} fetched={fetched} cleaned={cleaned} "
        f"written={written} cumulative_attempts={attempts}"
    )


def _page_failure_message(
    *,
    spec: EndpointSpec,
    unit: EndpointUnit,
    offset: int,
    fetched: int,
    cleaned: int,
    attempts: int,
    error_kind: str,
    error_message: str,
) -> str:
    return (
        _page_message(
            spec=spec,
            unit=unit,
            offset=offset,
            fetched=fetched,
            cleaned=cleaned,
            written=0,
            attempts=attempts,
        )
        + f" status=failed error_kind={error_kind} error={error_message}"
    )


def _api_event_message(event: TushareApiEvent) -> str:
    parts = [
        f"endpoint={event.endpoint}",
        f"api_event={event.kind}",
        f"attempt={event.attempt}/{event.max_attempts}",
    ]
    if event.retry_delay_seconds is not None:
        parts.append(f"retry_delay_seconds={event.retry_delay_seconds:g}")
    if event.rows_returned is not None:
        parts.append(f"rows_returned={event.rows_returned}")
    if event.duration_ms is not None:
        parts.append(f"duration_ms={event.duration_ms}")
    if event.error_kind:
        parts.append(f"error_kind={event.error_kind}")
    if event.error_message:
        parts.append(f"error={event.error_message}")
    return " ".join(parts)


def _job_result(
    *,
    run_id: int,
    request: TushareJobRequest,
    preflight: JobPreflight,
    checkpoint: Mapping[str, Any],
    total_units: int,
    failures: list[JobFailure],
    error_message: str | None,
) -> JobResult:
    counters = checkpoint["counters"]
    return JobResult(
        job=TushareEndpointJob.job_key,
        status=str(checkpoint["status"]),  # type: ignore[arg-type]
        run_id=run_id,
        parameters=preflight.parameters,
        parameter_sources=preflight.parameter_sources,
        rows_fetched=int(counters["rows_fetched"]),
        rows_matched=int(counters["rows_cleaned"]),
        rows_inserted=int(counters["rows_inserted"]),
        rows_rejected=int(counters["rows_rejected"]),
        api_calls=int(counters["api_calls"]),
        work_units_total=total_units,
        work_units_completed=int(counters["units_completed"]),
        work_units_failed=int(counters["units_failed"]),
        failures=failures,
        metrics={
            "rows_updated": int(counters["rows_updated"]),
            "pages_committed": int(counters.get("pages_committed", 0)),
        },
        error_message=error_message,
        preflight=preflight,
    )
