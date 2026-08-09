"""Guarded multi-day EODHD Bulk EOD ingest job."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from fdp.bulk_unmatched import MENU_CLASSIFICATION_STATUSES
from fdp.get_data.bulk.get_daily import (
    DEFAULT_ASSET_TYPES,
    DEFAULT_EXCHANGE,
    DEFAULT_INSTRUMENT_STATUS,
    DEFAULT_MARKET,
    EODHD_BULK_FULL_EXCHANGE_API_CALL_COST,
    SUPPORTED_BULK_ASSET_TYPES,
    SUPPORTED_INSTRUMENT_STATUSES,
)
from fdp.get_data.bulk.prerequisites import (
    DailyPrerequisiteResult,
    execute_daily_prerequisites,
    plan_daily_prerequisites,
)
from fdp.get_data.bulk.workflow import DailyBulkExecutor, DailyWorkflowExecution
from fdp.get_data.api_budget import check_remote_api_capacity
from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
    resolved_value,
)
from fdp.get_data.historical.base import (
    DEFAULT_MAX_CONSECUTIVE_GLOBAL_FAILURES,
    FATAL_HTTP_STATUS_CODES,
    GLOBAL_TRANSIENT_STATUS_CODES,
)
from fdp.get_data.runtime import JobRuntime
from fdp.get_data.reconcile.bulk_unmatched import BulkUnmatchedReconcileJob
from fdp.get_data.task_ledger import (
    DailyTaskScope,
    TaskAcquisition,
    TaskLeaseHeartbeat,
    TaskLedger,
)
from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import BulkDailyPriceLoadResult, load_bulk_daily_prices
from fdp.sources.eodhd.ingest.common import normalize_symbols
from fdp.sources.eodhd.identity import DatedInstrumentIdentityResolver
from fdp.sources.eodhd.retry import WeightedApiBudget
from fdp.storage.schema import ensure_runtime_schemas
from fdp.storage.tables import instrument, market_calendar

DEFAULT_DATE_FROM: date | None = None
DEFAULT_DATE_TO: date | None = None
DEFAULT_BYTES_PER_ROW = 600
DEFAULT_MAX_ESTIMATED_GB = 30.0


class DailyRangeJob:
    """Estimate and optionally execute one full-exchange Bulk EOD call per trading day."""

    job_key = "ingest.daily_range"
    job_module = "fdp.get_data.bulk.get_daily_range"

    def preflight(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        exchange: str | None = None,
        asset_types: list[str] | None = None,
        market: str | None = None,
        instrument_status: str | None = None,
        symbols: list[str] | None = None,
        bytes_per_row: int | None = None,
        max_estimated_gb: float | None = None,
        parallel: bool | None = None,
        workers: int | None = None,
        max_requests_per_minute: int | None = None,
        max_api_calls: int | None = None,
        new_run: bool = False,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        active_runtime = runtime or JobRuntime.from_env()
        parameters, sources = self._resolve(
            date_from=date_from,
            date_to=date_to,
            exchange=exchange,
            asset_types=asset_types,
            market=market,
            instrument_status=instrument_status,
            symbols=symbols,
            bytes_per_row=bytes_per_row,
            max_estimated_gb=max_estimated_gb,
            parallel=parallel,
            workers=workers,
            max_requests_per_minute=max_requests_per_minute,
            max_api_calls=max_api_calls,
            runtime=active_runtime,
            override_source=override_source,
        )
        prerequisite_plan = plan_daily_prerequisites(
            active_runtime,
            date_from=parameters["date_from"],
            date_to=parameters["date_to"],
            market=parameters["market"],
            instrument_status=parameters["instrument_status"],
        )
        with active_runtime.engine.connect() as connection:
            if prerequisite_plan.calendar_refresh:
                trade_dates = self._estimated_weekdays(
                    date_from=parameters["date_from"],
                    date_to=parameters["date_to"],
                )
            else:
                trade_dates = self._load_trading_dates(
                    connection,
                    date_from=parameters["date_from"],
                    date_to=parameters["date_to"],
                )
            scoped_instruments = self._count_instruments(
                connection,
                market=parameters["market"],
                asset_types=parameters["asset_types"],
                instrument_status=parameters["instrument_status"],
            )
            if not trade_dates:
                raise ValueError("no trading days found in market_calendar for this range")
            scope = self._task_scope(parameters)
            task_estimate = TaskLedger().estimate_daily_task(
                connection,
                scope=scope,
                trade_dates=trade_dates,
                new_run=new_run,
            )
        estimated_rows = task_estimate.provider_work_units * scoped_instruments
        estimated_gb = estimated_rows * parameters["bytes_per_row"] / (1024**3)
        per_day_api_calls = EODHD_BULK_FULL_EXCHANGE_API_CALL_COST + len(
            parameters["symbols"]
        )
        provider_work_required = task_estimate.provider_work_units > 0
        estimated_api_calls = (
            task_estimate.provider_work_units * per_day_api_calls
            + (prerequisite_plan.estimated_api_units if provider_work_required else 0)
            + int(provider_work_required)  # redacted EODHD /user budget check
        )
        if estimated_gb > parameters["max_estimated_gb"]:
            raise ValueError(
                f"estimated storage {estimated_gb:.2f}GB exceeds max-estimated-gb "
                f"{parameters['max_estimated_gb']:.2f}GB"
            )
        if estimated_api_calls > parameters["max_api_calls"]:
            raise ValueError(
                f"estimated EODHD API calls {estimated_api_calls} exceed max-api-calls "
                f"{parameters['max_api_calls']}; split the range or raise the budget explicitly"
            )
        warnings = list(prerequisite_plan.warnings if provider_work_required else ())
        if task_estimate.exact_no_op:
            warnings.append(
                f"exact completed task run_id={task_estimate.existing_run_id}; provider cost is 0"
            )
        elif task_estimate.reusable_work_units:
            warnings.append(
                f"{task_estimate.reusable_work_units} verified date(s) will be reused"
            )
        parameters = {
            **parameters,
            "new_run": bool(new_run),
            "provider_work_units": task_estimate.provider_work_units,
            "reusable_work_units": task_estimate.reusable_work_units,
        }
        sources = {**sources, "new_run": "invocation"}
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=[
                *(f"{asset_type}_daily_price" for asset_type in parameters["asset_types"]),
                "system.bulk_unmatched_daily_price_observation",
            ],
            work_units=len(trade_dates),
            estimated_api_calls=estimated_api_calls,
            estimated_rows=estimated_rows,
            estimated_gb=estimated_gb,
            parameters=parameters,
            parameter_sources=sources,
            warnings=warnings,
        )

    def run(
        self,
        *,
        execute: bool = False,
        manual: bool = False,
        new_run: bool = False,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        preflight: JobPreflight | None = None,
        task_ledger: TaskLedger | None = None,
        override_source: str = "python",
        **options: Any,
    ) -> JobResult:
        active_runtime = runtime or JobRuntime.from_env()
        active_preflight = preflight or self.preflight(
            new_run=new_run,
            runtime=active_runtime,
            override_source=override_source,
            **options,
        )
        if preflight is not None and bool(preflight.parameters.get("new_run")) != bool(
            new_run
        ):
            raise ValueError(
                "preflight new_run does not match this execution; regenerate preflight "
                "so the outstanding API estimate remains valid"
            )
        parameters = {**active_preflight.parameters, "new_run": bool(new_run)}
        if not execute:
            return JobResult(
                job=self.job_key,
                status="dry_run",
                run_id=None,
                parameters=parameters,
                parameter_sources=active_preflight.parameter_sources,
                work_units_total=active_preflight.work_units,
                preflight=active_preflight,
            )

        active_reporter = reporter or NullProgressReporter()
        ledger = task_ledger or TaskLedger()
        scope = self._task_scope(parameters)
        with active_runtime.engine.connect() as connection:
            if not new_run:
                completed = ledger.completed_daily_task(connection, scope=scope)
                if completed is not None:
                    return self._completed_task_result(
                        connection,
                        ledger=ledger,
                        acquisition=completed,
                        parameters=parameters,
                        parameter_sources=active_preflight.parameter_sources,
                        preflight=active_preflight,
                    )
            ledger.assert_no_live_equivalent_task(connection, scope=scope)

        prerequisite_plan = plan_daily_prerequisites(
            active_runtime,
            date_from=parameters["date_from"],
            date_to=parameters["date_to"],
            market=parameters["market"],
            instrument_status=parameters["instrument_status"],
        )
        api_budget = WeightedApiBudget(parameters["max_api_calls"])
        client: EodhdClient | None = None
        remote_budget: dict[str, int | str] = {
            "remote_budget_check": "skipped_no_provider_work",
            "remote_preflight_api_units": 0,
        }
        remote_checked = False
        prerequisite_parts: list[DailyPrerequisiteResult] = []
        if prerequisite_plan.calendar_refresh:
            client = active_runtime.client(
                active_reporter,
                max_requests_per_minute=parameters["max_requests_per_minute"],
                api_budget=api_budget,
            )
            remote_budget = self._check_remote_api_capacity(
                client,
                required_units=max(active_preflight.estimated_api_calls - 1, 0),
            )
            remote_checked = True
            prerequisite_parts.append(
                execute_daily_prerequisites(
                    active_runtime,
                    client,
                    plan=replace(
                        prerequisite_plan,
                        active_instrument_refresh=False,
                        inactive_instrument_refresh=False,
                        estimated_api_units=1,
                    ),
                    date_from=parameters["date_from"],
                    date_to=parameters["date_to"],
                    market=parameters["market"],
                    reporter=active_reporter,
                )
            )
        with active_runtime.engine.connect() as connection:
            self._ensure_calendar_coverage(
                connection,
                date_from=parameters["date_from"],
                date_to=parameters["date_to"],
            )
            trade_dates = self._load_trading_dates(
                connection,
                date_from=parameters["date_from"],
                date_to=parameters["date_to"],
            )
        if not trade_dates:
            raise ValueError("no trading days found in market_calendar for this range")
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            acquisition = ledger.acquire_daily_task(
                connection,
                scope=scope,
                trade_dates=trade_dates,
                new_run=new_run,
                manual=manual,
            )
        if acquisition.no_op:
            with active_runtime.engine.connect() as connection:
                return self._completed_task_result(
                    connection,
                    ledger=ledger,
                    acquisition=acquisition,
                    parameters=parameters,
                    parameter_sources=active_preflight.parameter_sources,
                    preflight=active_preflight,
                    invocation_api_units=api_budget.snapshot().consumed,
                )
        pending_provider_units = len(acquisition.pending_work_units)
        metadata_plan = plan_daily_prerequisites(
            active_runtime,
            date_from=parameters["date_from"],
            date_to=parameters["date_to"],
            market=parameters["market"],
            instrument_status=parameters["instrument_status"],
        )
        metadata_plan = replace(
            metadata_plan,
            calendar_refresh=False,
            estimated_api_units=(
                2 * int(metadata_plan.active_instrument_refresh)
                + int(metadata_plan.inactive_instrument_refresh)
            ),
        )
        execution = DailyWorkflowExecution((), (), False, None)
        if pending_provider_units:
            if client is None:
                client = active_runtime.client(
                    active_reporter,
                    max_requests_per_minute=parameters["max_requests_per_minute"],
                    api_budget=api_budget,
                )
            per_day_api_units = EODHD_BULK_FULL_EXCHANGE_API_CALL_COST + len(
                parameters["symbols"]
            )
            remaining_provider_units = (
                pending_provider_units * per_day_api_units
                + metadata_plan.estimated_api_units
            )
            budget_snapshot = api_budget.snapshot()
            user_check_units = 0 if remote_checked else 1
            if remaining_provider_units + user_check_units > budget_snapshot.remaining:
                message = (
                    "remaining Daily task exceeds this invocation's max-api-calls: "
                    f"remaining_required={remaining_provider_units + user_check_units} "
                    f"remaining_budget={budget_snapshot.remaining}"
                )
                with active_runtime.engine.begin() as connection:
                    ledger.finalize_task(
                        connection,
                        run_id=acquisition.run_id,
                        review_required=True,
                        error_message=message,
                    )
                raise ValueError(message)
            if not remote_checked:
                try:
                    with TaskLeaseHeartbeat(
                        engine=active_runtime.engine,
                        ledger=ledger,
                        run_id=acquisition.run_id,
                    ):
                        remote_budget = self._check_remote_api_capacity(
                            client,
                            required_units=remaining_provider_units,
                        )
                    remote_checked = True
                except Exception as exc:
                    message = f"Daily API budget check failed: {type(exc).__name__}: {exc}"
                    with active_runtime.engine.begin() as connection:
                        ledger.finalize_task(
                            connection,
                            run_id=acquisition.run_id,
                            review_required=True,
                            error_message=message,
                        )
                    raise
            try:
                with TaskLeaseHeartbeat(
                    engine=active_runtime.engine,
                    ledger=ledger,
                    run_id=acquisition.run_id,
                ):
                    if metadata_plan.estimated_api_units:
                        prerequisite_parts.append(
                            execute_daily_prerequisites(
                                active_runtime,
                                client,
                                plan=metadata_plan,
                                date_from=parameters["date_from"],
                                date_to=parameters["date_to"],
                                market=parameters["market"],
                                reporter=active_reporter,
                            )
                        )
                    with active_runtime.engine.connect() as connection:
                        identity_resolver = DatedInstrumentIdentityResolver.from_connection(
                            connection,
                            market=parameters["market"],
                            asset_types=parameters["asset_types"],
                            instrument_status=parameters["instrument_status"],
                        )
                    executor = DailyBulkExecutor(
                        runtime=active_runtime,
                        ledger=ledger,
                        client=client,
                        scope=scope,
                        identity_resolver=identity_resolver,
                        reporter=active_reporter,
                    )
                    execution = executor.execute(
                        acquisition,
                        parallel=parameters["parallel"],
                        workers=parameters["workers"],
                    )
            except Exception as exc:
                message = f"Daily setup/fetch failed: {type(exc).__name__}: {exc}"
                with active_runtime.engine.begin() as connection:
                    ledger.finalize_task(
                        connection,
                        run_id=acquisition.run_id,
                        review_required=True,
                        error_message=message,
                    )
                raise
        prerequisite_result = self._combine_prerequisite_results(prerequisite_parts)
        with active_runtime.engine.connect() as connection:
            units_after_fetch = ledger.load_work_units(
                connection,
                run_id=acquisition.run_id,
            )
        fetch_complete = all(
            unit.status in {"success", "reused", "held"}
            for unit in units_after_fetch
        )
        review_required = execution.review_required or prerequisite_result.review_required
        reconcile_details: dict[str, object] = {"skipped": True, "reason": "fetch_incomplete"}
        reconcile_error: str | None = None
        if fetch_complete and acquisition.reused_work_units == len(units_after_fetch):
            reconcile_details = {"skipped": True, "reason": "all_work_units_reused"}
            with active_runtime.engine.begin() as connection:
                ledger.mark_units_verified(connection, run_id=acquisition.run_id)
        elif fetch_complete and manual:
            review_required = True
            reconcile_details = {"skipped": True, "reason": "manual_mode"}
        elif fetch_complete:
            try:
                with active_runtime.engine.begin() as connection:
                    ledger.set_phase(
                        connection,
                        run_id=acquisition.run_id,
                        phase="reconcile",
                    )
                with TaskLeaseHeartbeat(
                    engine=active_runtime.engine,
                    ledger=ledger,
                    run_id=acquisition.run_id,
                ):
                    reconcile_details = self._run_automatic_reconcile(
                        runtime=active_runtime,
                        reporter=active_reporter,
                        date_from=parameters["date_from"],
                        date_to=parameters["date_to"],
                        market=parameters["market"],
                        asset_types=parameters["asset_types"],
                    )
                if reconcile_details["status"] == "success":
                    with active_runtime.engine.begin() as connection:
                        ledger.mark_units_verified(
                            connection,
                            run_id=acquisition.run_id,
                        )
                else:
                    review_required = True
            except Exception as exc:
                review_required = True
                reconcile_error = f"automatic reconcile failed: {type(exc).__name__}: {exc}"
                reconcile_details = {
                    "status": "failed",
                    "error_message": reconcile_error,
                }

        error_parts = [
            execution.stop_reason,
            reconcile_error,
            *(
                f"{failure.unit}: {failure.message}"
                for failure in execution.failures
            ),
        ]
        error_message = "; ".join(value for value in error_parts if value) or None
        budget_snapshot = api_budget.snapshot()
        with active_runtime.engine.begin() as connection:
            final = ledger.finalize_task(
                connection,
                run_id=acquisition.run_id,
                review_required=review_required,
                cancelled=execution.cancelled,
                error_message=error_message,
                details={
                    "prerequisites": list(prerequisite_result.jobs),
                    "reconcile": reconcile_details,
                    "api_units": {
                        "limit": budget_snapshot.limit,
                        "consumed": budget_snapshot.consumed,
                        "remaining": budget_snapshot.remaining,
                    },
                },
            )
            final_units = ledger.load_work_units(
                connection,
                run_id=acquisition.run_id,
            )
        rows_matched = sum(
            int(unit.metrics.get("rows_matched") or 0) for unit in final_units
        )
        rows_shadowed = sum(
            int(unit.metrics.get("rows_shadowed") or 0) for unit in final_units
        )
        completed_units = sum(
            unit.status in {"success", "reused", "held"} for unit in final_units
        )
        failed_units = sum(unit.status == "failed" for unit in final_units)
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                self.job_key,
                completed_units,
                len(final_units),
                message=str(final["status"]),
                counters={
                    "fetched": int(final["rows_fetched"]),
                    "published": int(final["rows_published"]),
                    "pending": int(final["rows_pending"]),
                    "rejected": int(final["rows_rejected"]),
                    "failed": failed_units,
                    "api_units": budget_snapshot.consumed,
                },
            )
        )
        return JobResult(
            job=self.job_key,
            status=final["status"],
            run_id=acquisition.run_id,
            parameters=parameters,
            parameter_sources=active_preflight.parameter_sources,
            rows_fetched=int(final["rows_fetched"]),
            rows_matched=rows_matched,
            rows_inserted=int(final["rows_published"]),
            rows_rejected=int(final["rows_rejected"]),
            rows_unmatched=int(final["rows_pending"]),
            api_calls=sum(outcome.api_calls for outcome in execution.outcomes)
            + prerequisite_result.api_calls
            + int(remote_budget["remote_preflight_api_units"]),
            work_units_total=len(final_units),
            work_units_completed=completed_units,
            work_units_failed=failed_units,
            failures=list(execution.failures),
            metrics={
                "api_units_limit": budget_snapshot.limit,
                "api_units_consumed": budget_snapshot.consumed,
                "api_units_remaining": budget_snapshot.remaining,
                **remote_budget,
                "rows_shadowed": rows_shadowed,
                "task_api_units_consumed": budget_snapshot.consumed,
                "resumed": acquisition.resumed,
                "new_run": acquisition.new_run,
                "reused_work_units": acquisition.reused_work_units,
                "review_required": bool(final["review_required"]),
                "reconcile": reconcile_details,
                "prerequisites": list(prerequisite_result.jobs),
            },
            error_message=error_message,
            preflight=active_preflight,
        )

    @staticmethod
    def _combine_prerequisite_results(
        parts: list[DailyPrerequisiteResult],
    ) -> DailyPrerequisiteResult:
        return DailyPrerequisiteResult(
            api_calls=sum(part.api_calls for part in parts),
            rows_fetched=sum(part.rows_fetched for part in parts),
            rows_inserted=sum(part.rows_inserted for part in parts),
            review_required=any(part.review_required for part in parts),
            jobs=tuple(job for part in parts for job in part.jobs),
        )

    @staticmethod
    def _task_scope(parameters: dict[str, Any]) -> DailyTaskScope:
        return DailyTaskScope.create(
            source=str(parameters["source"]),
            market=str(parameters["market"]),
            exchange=str(parameters["exchange"]),
            date_from=parameters["date_from"],
            date_to=parameters["date_to"],
            asset_types=parameters["asset_types"],
            instrument_status=str(parameters["instrument_status"]),
            symbols=parameters["symbols"],
        )

    def _completed_task_result(
        self,
        connection: Any,
        *,
        ledger: TaskLedger,
        acquisition: TaskAcquisition,
        parameters: dict[str, Any],
        parameter_sources: dict[str, str],
        preflight: JobPreflight,
        invocation_api_units: int = 0,
    ) -> JobResult:
        payload = ledger.task_status(connection, run_id=acquisition.run_id)
        units = ledger.load_work_units(connection, run_id=acquisition.run_id)
        rows_matched = sum(int(unit.metrics.get("rows_matched") or 0) for unit in units)
        rows_pending = sum(unit.rows_pending for unit in units)
        completed = sum(unit.status in {"success", "reused", "held"} for unit in units)
        failed = sum(unit.status == "failed" for unit in units)
        checkpoint = payload["checkpoint"]
        return JobResult(
            job=self.job_key,
            status="success",
            run_id=acquisition.run_id,
            parameters=parameters,
            parameter_sources=parameter_sources,
            rows_fetched=int(payload["rows_fetched"]),
            rows_matched=rows_matched,
            rows_inserted=int(payload["rows_published"]),
            rows_rejected=int(payload["rows_rejected"]),
            rows_unmatched=rows_pending,
            api_calls=0,
            work_units_total=len(units),
            work_units_completed=completed,
            work_units_failed=failed,
            metrics={
                "no_op": True,
                "original_run_id": acquisition.run_id,
                "original_api_calls": int(payload["api_calls"]),
                "invocation_api_units": invocation_api_units,
                "review_required": bool(checkpoint.get("review_required", False)),
                "reused_work_units": acquisition.reused_work_units,
            },
            preflight=preflight,
        )

    @staticmethod
    def _run_automatic_reconcile(
        *,
        runtime: JobRuntime,
        reporter: ProgressReporter,
        date_from: date,
        date_to: date,
        market: str,
        asset_types: list[str],
    ) -> dict[str, object]:
        job = BulkUnmatchedReconcileJob()
        classify = job.classify(
            date_from=date_from,
            date_to=date_to,
            market=market,
            statuses=list(MENU_CLASSIFICATION_STATUSES),
            runtime=runtime,
            reporter=reporter,
            override_source="daily_workflow",
        )
        details: dict[str, object] = {
            "run_id": classify.run_id,
            "classify_status": classify.status,
            "classify_rows": classify.work_units_completed,
            "api_calls": 0,
        }
        if classify.status != "success" or classify.run_id is None:
            details["status"] = "review_required"
            details["error_message"] = classify.error_message
            return details
        route = job.route(
            date_from=date_from,
            date_to=date_to,
            market=market,
            asset_types=asset_types,
            execute=True,
            run_id=classify.run_id,
            runtime=runtime,
            reporter=reporter,
            override_source="daily_workflow",
        )
        details.update(
            {
                "route_status": route.status,
                "route_rows": route.rows_inserted,
            }
        )
        if route.status != "success":
            details["status"] = "review_required"
            details["error_message"] = route.error_message
            return details
        validation = job.validate(
            date_from=date_from,
            date_to=date_to,
            market=market,
            asset_types=asset_types,
            run_id=classify.run_id,
            runtime=runtime,
            override_source="daily_workflow",
        )
        details.update(
            {
                "status": validation.status,
                "validation_status": validation.status,
                "quality_issue_count": validation.metrics.get("quality_issue_count", 0),
                "error_message": validation.error_message,
            }
        )
        return details

    def _execute_dates(
        self,
        runtime: JobRuntime,
        client: Any,
        *,
        trade_dates: list[date],
        exchange: str,
        market: str,
        asset_types: list[str],
        instrument_status: str,
        identity_resolver: DatedInstrumentIdentityResolver,
        parallel: bool,
        workers: int,
        reporter: ProgressReporter,
    ) -> tuple[list[BulkDailyPriceLoadResult], list[JobFailure], bool]:
        results: list[BulkDailyPriceLoadResult] = []
        failures: list[JobFailure] = []
        completed = 0
        consecutive_global_failures = 0
        cancelled = False

        def record(result: BulkDailyPriceLoadResult, trade_date: date) -> bool:
            nonlocal completed, consecutive_global_failures
            results.append(result)
            completed += 1
            if result.status == "failed":
                failures.append(
                    JobFailure(
                        trade_date.isoformat(),
                        "request",
                        result.error_message or result.status,
                    )
                )
            counters = self._totals(results)
            reporter.on_event(
                ProgressEvent(
                    "unit_failed" if result.status == "failed" else "unit_completed",
                    self.job_key,
                    completed,
                    len(trade_dates),
                    unit=trade_date.isoformat(),
                    message=result.status,
                    counters={**counters, "failed": len(failures)},
                )
            )
            if result.status_code in FATAL_HTTP_STATUS_CODES:
                return True
            if result.status == "failed" and (
                result.status_code is None or result.status_code in GLOBAL_TRANSIENT_STATUS_CODES
            ):
                consecutive_global_failures += 1
                return consecutive_global_failures >= DEFAULT_MAX_CONSECUTIVE_GLOBAL_FAILURES
            consecutive_global_failures = 0
            return False

        if parallel and workers > 1:
            executor = ThreadPoolExecutor(max_workers=workers)
            futures: dict[Future[BulkDailyPriceLoadResult], date] = {
                executor.submit(
                    self._run_one_day,
                    runtime,
                    client,
                    trade_date=trade_date,
                    exchange=exchange,
                    market=market,
                    asset_types=asset_types,
                    instrument_status=instrument_status,
                    identity_resolver=identity_resolver,
                ): trade_date
                for trade_date in trade_dates
            }
            try:
                stop_requested = False
                for future in as_completed(futures):
                    if future.cancelled():
                        continue
                    trade_date = futures[future]
                    try:
                        should_stop = record(future.result(), trade_date)
                    except Exception as exc:
                        completed += 1
                        failures.append(JobFailure(trade_date.isoformat(), "exception", str(exc)))
                        reporter.on_event(
                            ProgressEvent(
                                "unit_failed",
                                self.job_key,
                                completed,
                                len(trade_dates),
                                unit=trade_date.isoformat(),
                                message=str(exc),
                                counters={"failed": len(failures)},
                            )
                        )
                        should_stop = True
                    if should_stop and not stop_requested:
                        stop_requested = True
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
            except KeyboardInterrupt:
                cancelled = True
                for pending in futures:
                    pending.cancel()
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
            return results, failures, cancelled

        try:
            for trade_date in trade_dates:
                try:
                    result = self._run_one_day(
                        runtime,
                        client,
                        trade_date=trade_date,
                        exchange=exchange,
                        market=market,
                        asset_types=asset_types,
                        instrument_status=instrument_status,
                        identity_resolver=identity_resolver,
                    )
                except Exception as exc:
                    completed += 1
                    failures.append(JobFailure(trade_date.isoformat(), "exception", str(exc)))
                    reporter.on_event(
                        ProgressEvent(
                            "unit_failed",
                            self.job_key,
                            completed,
                            len(trade_dates),
                            unit=trade_date.isoformat(),
                            message=str(exc),
                            counters={"failed": len(failures)},
                        )
                    )
                    break
                if record(result, trade_date):
                    break
        except KeyboardInterrupt:
            cancelled = True
        return results, failures, cancelled

    @staticmethod
    def _run_one_day(
        runtime: JobRuntime,
        client: Any,
        *,
        trade_date: date,
        exchange: str,
        market: str,
        asset_types: list[str],
        instrument_status: str,
        identity_resolver: DatedInstrumentIdentityResolver,
    ) -> BulkDailyPriceLoadResult:
        with runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            return load_bulk_daily_prices(
                connection,
                client,
                exchange=exchange,
                trade_date=trade_date,
                market=market,
                asset_types=asset_types,
                instrument_status=instrument_status,
                identity_resolver=identity_resolver,
            )

    @staticmethod
    def _totals(results: list[BulkDailyPriceLoadResult]) -> dict[str, int]:
        return {
            "rows_fetched": sum(result.rows_fetched for result in results),
            "rows_matched": sum(result.rows_matched for result in results),
            "rows_inserted": sum(result.rows_inserted for result in results),
            "rows_rejected": sum(result.rows_rejected for result in results),
            "rows_unmatched": sum(result.unmatched_rows for result in results),
            "rows_shadowed": sum(result.shadowed_rows for result in results),
            "api_calls": sum(result.api_calls for result in results),
        }

    @staticmethod
    def _resolve(
        *,
        date_from: date | None,
        date_to: date | None,
        exchange: str | None,
        asset_types: list[str] | None,
        market: str | None,
        instrument_status: str | None,
        symbols: list[str] | None,
        bytes_per_row: int | None,
        max_estimated_gb: float | None,
        parallel: bool | None,
        workers: int | None,
        max_requests_per_minute: int | None,
        max_api_calls: int | None,
        runtime: JobRuntime,
        override_source: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        resolved_from, from_source = resolved_value(
            date_from,
            DEFAULT_DATE_FROM,
            name="date_from",
            explicit_source=override_source,
        )
        resolved_to, to_source = resolved_value(
            date_to,
            DEFAULT_DATE_TO,
            name="date_to",
            explicit_source=override_source,
        )
        if resolved_to < resolved_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        resolved_assets = [value.lower() for value in (asset_types or DEFAULT_ASSET_TYPES)]
        unsupported = set(resolved_assets) - SUPPORTED_BULK_ASSET_TYPES
        if unsupported:
            raise ValueError(f"unsupported bulk asset type(s): {', '.join(sorted(unsupported))}")
        resolved_status = (instrument_status or DEFAULT_INSTRUMENT_STATUS).lower()
        if resolved_status not in SUPPORTED_INSTRUMENT_STATUSES:
            raise ValueError("instrument_status must be active or all")
        resolved_parallel = (
            runtime.config.daily_range_parallel_enabled if parallel is None else parallel
        )
        resolved_workers = (
            workers if workers is not None else runtime.config.daily_range_max_workers
        )
        if not resolved_parallel:
            resolved_workers = 1
        values = {
            "date_from": resolved_from,
            "date_to": resolved_to,
            "exchange": (exchange or DEFAULT_EXCHANGE).upper(),
            "asset_types": resolved_assets,
            "market": (market or DEFAULT_MARKET).upper(),
            "instrument_status": resolved_status,
            "symbols": normalize_symbols(symbols or []),
            "bytes_per_row": (
                bytes_per_row if bytes_per_row is not None else DEFAULT_BYTES_PER_ROW
            ),
            "max_estimated_gb": (
                max_estimated_gb if max_estimated_gb is not None else DEFAULT_MAX_ESTIMATED_GB
            ),
            "parallel": resolved_parallel,
            "workers": resolved_workers,
            "max_requests_per_minute": (
                max_requests_per_minute
                if max_requests_per_minute is not None
                else runtime.config.max_requests_per_minute
            ),
            "max_api_calls": (
                max_api_calls if max_api_calls is not None else runtime.config.daily_call_budget
            ),
            "source": "eodhd",
        }
        if values["bytes_per_row"] <= 0 or values["max_estimated_gb"] <= 0:
            raise ValueError("storage estimate controls must be positive")
        if values["workers"] <= 0 or values["max_requests_per_minute"] <= 0:
            raise ValueError("workers and max_requests_per_minute must be positive")
        if values["max_requests_per_minute"] > 1_000:
            raise ValueError("max_requests_per_minute must be less than or equal to 1000")
        if values["max_api_calls"] <= 0:
            raise ValueError("max_api_calls must be positive")
        sources = {
            "date_from": from_source,
            "date_to": to_source,
            "exchange": override_source if exchange is not None else "job_default",
            "asset_types": override_source if asset_types is not None else "job_default",
            "market": override_source if market is not None else "job_default",
            "instrument_status": (
                override_source if instrument_status is not None else "job_default"
            ),
            "symbols": override_source if symbols is not None else "job_default",
            "bytes_per_row": override_source if bytes_per_row is not None else "job_default",
            "max_estimated_gb": override_source if max_estimated_gb is not None else "job_default",
            "parallel": override_source if parallel is not None else "runtime_config",
            "workers": override_source if workers is not None else "runtime_config",
            "max_requests_per_minute": (
                override_source if max_requests_per_minute is not None else "runtime_config"
            ),
            "max_api_calls": override_source if max_api_calls is not None else "runtime_config",
            "source": "job_default",
        }
        return values, sources

    @staticmethod
    def _check_remote_api_capacity(
        client: EodhdClient,
        *,
        required_units: int,
    ) -> dict[str, int | str]:
        """Use the redacted User API counters to reject an underfunded real run."""
        return check_remote_api_capacity(client, required_units=required_units)

    @staticmethod
    def _load_trading_dates(connection: Any, *, date_from: date, date_to: date) -> list[date]:
        return list(
            connection.execute(
                select(market_calendar.c.calendar_date)
                .where(
                    market_calendar.c.calendar_date >= date_from,
                    market_calendar.c.calendar_date <= date_to,
                    market_calendar.c.is_trading_day.is_(True),
                )
                .order_by(market_calendar.c.calendar_date)
            ).scalars()
        )

    @staticmethod
    def _estimated_weekdays(*, date_from: date, date_to: date) -> list[date]:
        """Conservative read-only estimate used until missing calendar rows are loaded."""
        values: list[date] = []
        current = date_from
        while current <= date_to:
            if current.weekday() < 5:
                values.append(current)
            current += timedelta(days=1)
        return values

    @staticmethod
    def _ensure_calendar_coverage(connection: Any, *, date_from: date, date_to: date) -> None:
        expected_days = (date_to - date_from).days + 1
        loaded_days = int(
            connection.execute(
                select(func.count())
                .select_from(market_calendar)
                .where(
                    market_calendar.c.calendar_date >= date_from,
                    market_calendar.c.calendar_date <= date_to,
                )
            ).scalar_one()
        )
        if loaded_days < expected_days:
            raise ValueError(
                "market_calendar coverage is incomplete for this range: "
                f"loaded_days={loaded_days} expected_days={expected_days}; "
                "run calendar ingest before estimating or executing a large backfill"
            )

    @staticmethod
    def _count_instruments(
        connection: Any,
        *,
        market: str,
        asset_types: list[str],
        instrument_status: str,
    ) -> int:
        conditions = [
            instrument.c.provider == "EODHD",
            instrument.c.market == market,
            instrument.c.asset_type.in_(asset_types),
        ]
        if instrument_status == "active":
            conditions.append(instrument.c.is_active.is_(True))
        elif instrument_status != "all":
            raise ValueError("instrument_status must be active or all")
        return int(
            connection.execute(
                select(func.count())
                .select_from(instrument)
                .where(*conditions)
            ).scalar_one()
        )
