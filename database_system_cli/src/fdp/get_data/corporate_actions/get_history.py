"""Guarded per-instrument EODHD dividend and split history backfill."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import date
import hashlib
import json
from threading import Lock
from typing import Any

from sqlalchemy import or_, select, update

from fdp.get_data.api_budget import remote_api_capacity_metrics
from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
)
from fdp.get_data.historical.base import (
    DEFAULT_MAX_CONSECUTIVE_GLOBAL_FAILURES,
    FATAL_HTTP_STATUS_CODES,
    GLOBAL_TRANSIENT_STATUS_CODES,
)
from fdp.get_data.runtime import JobRuntime
from fdp.quality.corporate_actions import (
    create_corporate_action_quality_check,
    finish_corporate_action_quality_check,
)
from fdp.sources.eodhd.corporate_action_identity import CorporateActionIdentityResolver
from fdp.sources.eodhd.ingest import (
    CorporateActionUnitResult,
    fetch_corporate_action_unit,
    normalize_action_types,
    persist_corporate_action_unit,
    record_corporate_action_api_calls,
)
from fdp.sources.eodhd.ingest.common import (
    create_task_run,
    finish_task_run,
    normalize_symbols,
    record_api_call,
)
from fdp.sources.eodhd.retry import EodhdApiBudgetExceeded, WeightedApiBudget
from fdp.storage.schema import ensure_runtime_schemas
from fdp.storage.tables import ingestion_task_run, instrument

DEFAULT_ACTION_TYPES = ("dividend", "split")
DEFAULT_INSTRUMENT_STATUS = "active"
DEFAULT_MARKET = "US"
DEFAULT_MAX_API_CALLS = 200
DEFAULT_WORKERS = 4
DEFAULT_BATCH_SIZE = 100
SUPPORTED_INSTRUMENT_STATUSES = frozenset({"active", "inactive", "all"})
CHECKPOINT_VERSION = 1


class CorporateActionsHistoryJob:
    """Backfill dividends/splits with one hard weighted budget and resumable batches."""

    job_key = "ingest.corporate_actions"
    job_module = "fdp.get_data.corporate_actions.get_history"
    job_name = "eodhd_corporate_actions"

    def preflight(
        self,
        *,
        symbols: list[str] | None = None,
        action_types: list[str] | None = None,
        instrument_status: str | None = None,
        market: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
        parallel: bool | None = None,
        workers: int | None = None,
        batch_size: int | None = None,
        max_requests_per_minute: int | None = None,
        max_api_calls: int | None = None,
        resume_run_id: int | None = None,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        active_runtime = runtime or JobRuntime.from_env()
        parameters, sources = self._resolve_options(
            symbols=symbols,
            action_types=action_types,
            instrument_status=instrument_status,
            market=market,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            parallel=parallel,
            workers=workers,
            batch_size=batch_size,
            max_requests_per_minute=max_requests_per_minute,
            max_api_calls=max_api_calls,
            resume_run_id=resume_run_id,
            runtime=active_runtime,
            override_source=override_source,
        )
        with active_runtime.engine.connect() as connection:
            checkpoint = self._load_resume_checkpoint(
                connection,
                resume_run_id=parameters["resume_run_id"],
            )
            parameters = self._apply_resume_budget(parameters, checkpoint)
            instruments, missing_symbols, universe_count = self._select_instruments(
                connection,
                parameters=parameters,
                checkpoint=checkpoint,
            )
        self._validate_fingerprint(parameters, checkpoint)

        remaining_budget = parameters["remaining_api_calls"]
        action_cost = len(parameters["action_types"])
        max_complete = max(remaining_budget - 1, 0) // action_cost
        selected = instruments[:max_complete]
        warnings = []
        if len(instruments) > len(selected):
            warnings.append(
                f"hard API budget selects {len(selected)} of {len(instruments)} eligible instruments"
            )
        if missing_symbols:
            warnings.append(
                f"{len(missing_symbols)} symbol(s) do not match the selected instrument scope"
            )
        if not selected:
            warnings.append("no complete instrument request fits the remaining API budget")
        parameters = {
            **parameters,
            "eligible_instruments": len(instruments),
            "selected_instruments": len(selected),
            "universe_instruments": universe_count,
            "start_after_instrument_id": (
                int(checkpoint.get("last_instrument_id") or 0) if checkpoint else 0
            ),
        }
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=["corporate_action", "system.data_quality_issue"],
            work_units=len(selected),
            estimated_api_calls=(len(selected) * action_cost) + (1 if selected else 0),
            estimated_rows=None,
            parameters=parameters,
            parameter_sources=sources,
            missing_symbols=missing_symbols,
            warnings=warnings,
        )

    def run(
        self,
        *,
        execute: bool = False,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        preflight: JobPreflight | None = None,
        override_source: str = "python",
        **options: Any,
    ) -> JobResult:
        active_runtime = runtime or JobRuntime.from_env()
        active_preflight = preflight or self.preflight(
            runtime=active_runtime,
            override_source=override_source,
            **options,
        )
        parameters = active_preflight.parameters
        if not execute:
            return JobResult(
                job=self.job_key,
                status="dry_run",
                run_id=parameters["resume_run_id"],
                parameters=parameters,
                parameter_sources=active_preflight.parameter_sources,
                work_units_total=active_preflight.work_units,
                missing_symbols=active_preflight.missing_symbols,
                preflight=active_preflight,
            )
        if active_preflight.work_units == 0:
            raise ValueError("no corporate-action work units fit the selected scope and budget")

        active_reporter = reporter or NullProgressReporter()
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            checkpoint = self._load_resume_checkpoint(
                connection,
                resume_run_id=parameters["resume_run_id"],
            )
            self._validate_fingerprint(parameters, checkpoint)
            instruments, missing_symbols, universe_count = self._select_instruments(
                connection,
                parameters=parameters,
                checkpoint=checkpoint,
            )
            instruments = instruments[: active_preflight.work_units]
            run_id, check_run_id, checkpoint = self._prepare_run(
                connection,
                parameters=parameters,
                checkpoint=checkpoint,
            )
            identity_resolver = CorporateActionIdentityResolver.from_connection(
                connection,
                market=parameters["market"],
            )

        active_reporter.on_event(
            ProgressEvent(
                "start",
                self.job_key,
                int(checkpoint["work_units_completed"]),
                int(checkpoint["work_units_completed"]) + len(instruments),
                message="corporate-action backfill started",
            )
        )
        invocation_budget = WeightedApiBudget(int(parameters["remaining_api_calls"]))
        invocation_base_api_calls = int(checkpoint["api_calls"])
        remote_metrics: dict[str, int | str] = {}
        failures: list[JobFailure] = []
        cancelled = False
        fatal_stop = False
        write_lock = Lock()

        try:
            preflight_client = active_runtime.client(
                active_reporter,
                max_requests_per_minute=parameters["max_requests_per_minute"],
                api_budget=invocation_budget,
            )
            user_response = preflight_client.get_user()
            with active_runtime.engine.begin() as connection:
                record_api_call(connection, run_id=run_id, response=user_response)
            remote_metrics = remote_api_capacity_metrics(
                user_response,
                required_units=invocation_budget.snapshot().remaining,
            )
            client = active_runtime.client(
                active_reporter,
                max_requests_per_minute=parameters["max_requests_per_minute"],
                api_budget=invocation_budget,
            )
            fatal_stop = self._execute_batches(
                active_runtime,
                client,
                run_id=run_id,
                check_run_id=check_run_id,
                instruments=instruments,
                parameters=parameters,
                checkpoint=checkpoint,
                failures=failures,
                reporter=active_reporter,
                budget=invocation_budget,
                invocation_base_api_calls=invocation_base_api_calls,
                write_lock=write_lock,
                identity_resolver=identity_resolver,
            )
        except KeyboardInterrupt:
            cancelled = True
        except EodhdApiBudgetExceeded as exc:
            failures.append(JobFailure("api-budget", "api_budget", str(exc)))
            fatal_stop = True
        except Exception as exc:
            failures.append(JobFailure(self.job_key, "runtime_error", self._concise(exc)))
            fatal_stop = True

        budget_snapshot = invocation_budget.snapshot()
        checkpoint["api_calls"] = invocation_base_api_calls + budget_snapshot.consumed
        checkpoint["updated_at_status"] = (
            "cancelled" if cancelled else "partial_failed" if failures else "success"
        )
        error_message = (
            "; ".join(f"{failure.unit}: {failure.message}" for failure in failures) or None
        )
        if cancelled:
            error_message = "cancelled by operator" + (
                f"; {error_message}" if error_message else ""
            )
        completed = int(checkpoint["work_units_completed"])
        failed = int(checkpoint["work_units_failed"])
        successful = max(completed - failed, 0)
        if cancelled:
            status = "cancelled"
        elif (failures or fatal_stop) and successful == 0:
            status = "failed"
        elif failures or fatal_stop or failed:
            status = "partial_failed"
        else:
            status = "success"
        expected_completed = int(checkpoint["initial_work_units_completed"]) + len(
            instruments
        )
        checkpoint["complete"] = (
            not cancelled
            and not fatal_stop
            and completed >= expected_completed
        )

        persisted_status = "failed" if status == "cancelled" and successful == 0 else status
        if status == "cancelled" and successful:
            persisted_status = "partial_failed"
        with active_runtime.engine.begin() as connection:
            self._persist_checkpoint(connection, run_id=run_id, checkpoint=checkpoint)
            finish_task_run(
                connection,
                run_id=run_id,
                status=persisted_status,
                rows_fetched=int(checkpoint["rows_fetched"]),
                rows_inserted=int(checkpoint["rows_inserted"]),
                rows_updated=0,
                rows_rejected=int(checkpoint["rows_rejected"]),
                api_calls=int(checkpoint["api_calls"]),
                error_message=error_message,
            )
            if status != "cancelled":
                finish_corporate_action_quality_check(
                    connection,
                    check_run_id=check_run_id,
                    status="failed" if status == "failed" else "success",
                    issues_found=int(checkpoint["rows_rejected"]),
                    error_message=error_message if status == "failed" else None,
                )

        total = int(checkpoint["initial_work_units_completed"]) + len(instruments)
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                self.job_key,
                completed,
                total,
                message=status,
                counters={
                    "fetched": int(checkpoint["rows_fetched"]),
                    "inserted": int(checkpoint["rows_inserted"]),
                    "rejected": int(checkpoint["rows_rejected"]),
                    "failed": failed,
                    "api_calls": int(checkpoint["api_calls"]),
                },
            )
        )
        return JobResult(
            job=self.job_key,
            status=status,
            run_id=run_id,
            parameters=parameters,
            parameter_sources=active_preflight.parameter_sources,
            rows_fetched=int(checkpoint["rows_fetched"]),
            rows_matched=completed,
            rows_inserted=int(checkpoint["rows_inserted"]),
            rows_rejected=int(checkpoint["rows_rejected"]),
            api_calls=int(checkpoint["api_calls"]),
            work_units_total=total,
            work_units_completed=completed,
            work_units_failed=failed,
            missing_symbols=missing_symbols,
            failures=failures,
            metrics={
                "quality_check_run_id": check_run_id,
                "universe_instruments": universe_count,
                "selected_instruments": len(instruments),
                "invocation_api_units_limit": budget_snapshot.limit,
                "invocation_api_units_consumed": budget_snapshot.consumed,
                "invocation_api_units_remaining": budget_snapshot.remaining,
                "task_api_units_limit": int(checkpoint["api_units_limit"]),
                "task_api_units_consumed": int(checkpoint["api_calls"]),
                **remote_metrics,
            },
            error_message=error_message,
            preflight=active_preflight,
        )

    def _execute_batches(
        self,
        runtime: JobRuntime,
        client: Any,
        *,
        run_id: int,
        check_run_id: int,
        instruments: list[dict[str, object]],
        parameters: dict[str, Any],
        checkpoint: dict[str, Any],
        failures: list[JobFailure],
        reporter: ProgressReporter,
        budget: WeightedApiBudget,
        invocation_base_api_calls: int,
        write_lock: Any,
        identity_resolver: CorporateActionIdentityResolver,
    ) -> bool:
        fatal_stop = False
        batch_size = int(parameters["batch_size"])
        for start in range(0, len(instruments), batch_size):
            batch = instruments[start : start + batch_size]
            results, batch_failures, batch_fatal = self._execute_batch(
                runtime,
                client,
                run_id=run_id,
                check_run_id=check_run_id,
                batch=batch,
                parameters=parameters,
                write_lock=write_lock,
                identity_resolver=identity_resolver,
            )
            failures.extend(batch_failures)
            for result in sorted(results, key=lambda item: item.instrument_id):
                self._add_result(checkpoint, result)
                reporter.on_event(
                    ProgressEvent(
                        "unit_completed" if result.status == "success" else "unit_failed",
                        self.job_key,
                        int(checkpoint["work_units_completed"]),
                        int(checkpoint["initial_work_units_completed"]) + len(instruments),
                        unit=result.provider_symbol,
                        message=result.status,
                        counters={
                            "fetched": int(checkpoint["rows_fetched"]),
                            "inserted": int(checkpoint["rows_inserted"]),
                            "rejected": int(checkpoint["rows_rejected"]),
                            "failed": int(checkpoint["work_units_failed"]),
                            "api_calls": (
                                invocation_base_api_calls + budget.snapshot().consumed
                            ),
                        },
                    )
                )
            completed_ids = {result.instrument_id for result in results}
            for row in batch:
                if int(row["instrument_id"]) not in completed_ids:
                    break
                checkpoint["last_instrument_id"] = int(row["instrument_id"])
            with runtime.engine.begin() as connection:
                checkpoint["api_calls"] = (
                    invocation_base_api_calls + budget.snapshot().consumed
                )
                self._persist_checkpoint(connection, run_id=run_id, checkpoint=checkpoint)
            if batch_fatal:
                fatal_stop = True
                break
        return fatal_stop

    def _execute_batch(
        self,
        runtime: JobRuntime,
        client: Any,
        *,
        run_id: int,
        check_run_id: int,
        batch: list[dict[str, object]],
        parameters: dict[str, Any],
        write_lock: Any,
        identity_resolver: CorporateActionIdentityResolver,
    ) -> tuple[list[CorporateActionUnitResult], list[JobFailure], bool]:
        if not parameters["parallel"] or parameters["workers"] == 1:
            results: list[CorporateActionUnitResult] = []
            failures: list[JobFailure] = []
            consecutive_global = 0
            for instrument_row in batch:
                provider_symbol = str(instrument_row["provider_symbol"])
                try:
                    result = self._run_unit(
                        runtime,
                        client,
                        run_id=run_id,
                        check_run_id=check_run_id,
                        instrument_row=instrument_row,
                        parameters=parameters,
                        write_lock=write_lock,
                        identity_resolver=identity_resolver,
                    )
                except Exception as exc:
                    failures.append(self._exception_failure(provider_symbol, exc))
                    return results, failures, True
                results.append(result)
                stop, consecutive_global = self._result_stop(result, consecutive_global)
                if result.status != "success":
                    failures.append(self._unit_failure(result))
                if stop:
                    return results, failures, True
            return results, failures, False

        results = []
        failures = []
        fatal = False
        executor = ThreadPoolExecutor(max_workers=int(parameters["workers"]))
        futures: dict[Future[CorporateActionUnitResult], dict[str, object]] = {
            executor.submit(
                self._run_unit,
                runtime,
                client,
                run_id=run_id,
                check_run_id=check_run_id,
                instrument_row=instrument_row,
                parameters=parameters,
                write_lock=write_lock,
                identity_resolver=identity_resolver,
            ): instrument_row
            for instrument_row in batch
        }
        try:
            for future in as_completed(futures):
                row = futures[future]
                provider_symbol = str(row["provider_symbol"])
                try:
                    result = future.result()
                except Exception as exc:
                    failures.append(self._exception_failure(provider_symbol, exc))
                    fatal = True
                    for pending in futures:
                        pending.cancel()
                    continue
                results.append(result)
                if result.status != "success":
                    failures.append(self._unit_failure(result))
                if result.status_code in FATAL_HTTP_STATUS_CODES:
                    fatal = True
                    for pending in futures:
                        pending.cancel()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        consecutive_global = 0
        for result in sorted(results, key=lambda item: item.instrument_id):
            stop, consecutive_global = self._result_stop(result, consecutive_global)
            if stop:
                fatal = True
                break
        return results, failures, fatal

    @staticmethod
    def _run_unit(
        runtime: JobRuntime,
        client: Any,
        *,
        run_id: int,
        check_run_id: int,
        instrument_row: dict[str, object],
        parameters: dict[str, Any],
        write_lock: Any,
        identity_resolver: CorporateActionIdentityResolver,
    ) -> CorporateActionUnitResult:
        provider_symbol = str(instrument_row["provider_symbol"])
        fetched = fetch_corporate_action_unit(
            client,
            provider_symbol=provider_symbol,
            action_types=parameters["action_types"],
            date_from=parameters["date_from"],
            date_to=parameters["date_to"],
        )
        with write_lock:
            try:
                with runtime.engine.begin() as connection:
                    record_corporate_action_api_calls(
                        connection,
                        run_id=run_id,
                        fetched=fetched,
                        date_from=parameters["date_from"],
                        date_to=parameters["date_to"],
                    )
                    return persist_corporate_action_unit(
                        connection,
                        fetched=fetched,
                        check_run_id=check_run_id,
                        market=parameters["market"],
                        instrument_row=instrument_row,
                        identity_resolver=identity_resolver,
                    )
            except Exception:
                # Preserve API evidence even when canonical DML rolls back.
                with runtime.engine.begin() as connection:
                    record_corporate_action_api_calls(
                        connection,
                        run_id=run_id,
                        fetched=fetched,
                        date_from=parameters["date_from"],
                        date_to=parameters["date_to"],
                    )
                raise

    @staticmethod
    def _add_result(checkpoint: dict[str, Any], result: CorporateActionUnitResult) -> None:
        checkpoint["work_units_completed"] = int(checkpoint["work_units_completed"]) + 1
        checkpoint["rows_fetched"] = int(checkpoint["rows_fetched"]) + result.rows_fetched
        checkpoint["rows_inserted"] = int(checkpoint["rows_inserted"]) + result.rows_inserted
        checkpoint["rows_rejected"] = int(checkpoint["rows_rejected"]) + result.rows_rejected
        if result.status != "success":
            checkpoint["work_units_failed"] = int(checkpoint["work_units_failed"]) + 1

    @staticmethod
    def _result_stop(
        result: CorporateActionUnitResult,
        consecutive_global: int,
    ) -> tuple[bool, int]:
        if result.status_code in FATAL_HTTP_STATUS_CODES:
            return True, consecutive_global
        if result.status == "failed" and (
            result.status_code is None or result.status_code in GLOBAL_TRANSIENT_STATUS_CODES
        ):
            consecutive_global += 1
            return consecutive_global >= DEFAULT_MAX_CONSECUTIVE_GLOBAL_FAILURES, consecutive_global
        return False, 0

    @staticmethod
    def _unit_failure(result: CorporateActionUnitResult) -> JobFailure:
        category = (
            "authentication_or_entitlement"
            if result.status_code in FATAL_HTTP_STATUS_CODES
            else "provider_or_validation"
        )
        return JobFailure(
            result.provider_symbol,
            category,
            result.error_message or result.status,
        )

    @staticmethod
    def _exception_failure(provider_symbol: str, exc: Exception) -> JobFailure:
        category = "api_budget" if isinstance(exc, EodhdApiBudgetExceeded) else "runtime_error"
        return JobFailure(provider_symbol, category, CorporateActionsHistoryJob._concise(exc))

    @staticmethod
    def _resolve_options(
        *,
        symbols: list[str] | None,
        action_types: list[str] | None,
        instrument_status: str | None,
        market: str | None,
        date_from: date | None,
        date_to: date | None,
        limit: int | None,
        parallel: bool | None,
        workers: int | None,
        batch_size: int | None,
        max_requests_per_minute: int | None,
        max_api_calls: int | None,
        resume_run_id: int | None,
        runtime: JobRuntime,
        override_source: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if date_from is not None and date_to is not None and date_to < date_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        normalized_actions = normalize_action_types(list(action_types or DEFAULT_ACTION_TYPES))
        normalized_status = (instrument_status or DEFAULT_INSTRUMENT_STATUS).strip().lower()
        if normalized_status not in SUPPORTED_INSTRUMENT_STATUSES:
            raise ValueError("instrument_status must be active, inactive, or all")
        normalized_symbols = normalize_symbols(symbols or []) if symbols is not None else None
        if symbols is not None and not normalized_symbols:
            raise ValueError("symbols must contain at least one symbol")
        resolved_parallel = True if parallel is None else parallel
        resolved_workers = workers if workers is not None else DEFAULT_WORKERS
        if not resolved_parallel:
            resolved_workers = 1
        resolved_max_calls = max_api_calls
        if resolved_max_calls is None and resume_run_id is None:
            resolved_max_calls = DEFAULT_MAX_API_CALLS
        parameters = {
            "symbols": normalized_symbols,
            "action_types": normalized_actions,
            "asset_type": "stock",
            "instrument_status": normalized_status,
            "market": (market or DEFAULT_MARKET).strip().upper(),
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
            "parallel": resolved_parallel,
            "workers": resolved_workers,
            "batch_size": batch_size if batch_size is not None else DEFAULT_BATCH_SIZE,
            "max_requests_per_minute": (
                max_requests_per_minute
                if max_requests_per_minute is not None
                else runtime.config.max_requests_per_minute
            ),
            "max_api_calls": resolved_max_calls,
            "resume_run_id": resume_run_id,
        }
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        if resolved_workers <= 0 or parameters["batch_size"] <= 0:
            raise ValueError("workers and batch_size must be positive")
        if not 1 <= parameters["max_requests_per_minute"] <= 1000:
            raise ValueError("max_requests_per_minute must be between 1 and 1000")
        if resolved_max_calls is not None and resolved_max_calls <= 1:
            raise ValueError("max_api_calls must be at least 2 to include User API preflight")
        explicit = override_source
        sources = {
            "symbols": explicit if symbols is not None else "job_default",
            "action_types": explicit if action_types is not None else "job_default",
            "asset_type": "job_fixed",
            "instrument_status": explicit if instrument_status is not None else "job_default",
            "market": explicit if market is not None else "job_default",
            "date_from": explicit if date_from is not None else "job_default",
            "date_to": explicit if date_to is not None else "job_default",
            "limit": explicit if limit is not None else "job_default",
            "parallel": explicit if parallel is not None else "job_default",
            "workers": explicit if workers is not None else "job_default",
            "batch_size": explicit if batch_size is not None else "job_default",
            "max_requests_per_minute": (
                explicit if max_requests_per_minute is not None else "runtime_config"
            ),
            "max_api_calls": explicit if max_api_calls is not None else "job_default",
            "resume_run_id": explicit if resume_run_id is not None else "job_default",
        }
        return parameters, sources

    @staticmethod
    def _select_instruments(
        connection: Any,
        *,
        parameters: dict[str, Any],
        checkpoint: dict[str, Any] | None,
    ) -> tuple[list[dict[str, object]], list[str], int]:
        conditions = [
            instrument.c.provider == "EODHD",
            instrument.c.market == parameters["market"],
            instrument.c.asset_type == "stock",
        ]
        status = parameters["instrument_status"]
        if status == "active":
            conditions.append(instrument.c.is_active.is_(True))
        elif status == "inactive":
            conditions.append(instrument.c.is_active.is_(False))
        symbols = parameters["symbols"]
        if symbols is not None:
            conditions.append(
                or_(
                    instrument.c.symbol.in_(symbols),
                    instrument.c.provider_symbol.in_(symbols),
                )
            )
        rows = [
            dict(row)
            for row in connection.execute(
                select(
                    instrument.c.instrument_id,
                    instrument.c.symbol,
                    instrument.c.provider_symbol,
                    instrument.c.asset_type,
                    instrument.c.currency,
                )
                .where(*conditions)
                .order_by(instrument.c.instrument_id)
            ).mappings()
        ]
        universe_count = len(rows)
        found = {
            str(value).upper()
            for row in rows
            for value in (row["symbol"], row["provider_symbol"])
        }
        last_id = int(checkpoint.get("last_instrument_id") or 0) if checkpoint else 0
        rows = [row for row in rows if int(row["instrument_id"]) > last_id]
        if parameters["limit"] is not None:
            rows = rows[: int(parameters["limit"])]
        missing: list[str] = []
        if symbols is not None:
            missing = [symbol for symbol in symbols if symbol not in found]
        return rows, missing, universe_count

    def _prepare_run(
        self,
        connection: Any,
        *,
        parameters: dict[str, Any],
        checkpoint: dict[str, Any] | None,
    ) -> tuple[int, int, dict[str, Any]]:
        if checkpoint is not None:
            run_id = int(parameters["resume_run_id"])
            connection.execute(
                update(ingestion_task_run)
                .where(ingestion_task_run.c.run_id == run_id)
                .values(status="running", finished_at=None, error_message=None)
            )
            checkpoint["initial_work_units_completed"] = int(
                checkpoint["work_units_completed"]
            )
            return run_id, int(checkpoint["quality_check_run_id"]), checkpoint

        run_id = create_task_run(
            connection,
            market=parameters["market"],
            job_name=self.job_name,
            target_table="corporate_action",
            date_from=parameters["date_from"],
            date_to=parameters["date_to"],
        )
        check_run_id = create_corporate_action_quality_check(
            connection,
            market=parameters["market"],
            run_id=run_id,
        )
        checkpoint = {
            "version": CHECKPOINT_VERSION,
            "job": self.job_key,
            "fingerprint": self._fingerprint(parameters),
            "quality_check_run_id": check_run_id,
            "api_units_limit": int(parameters["max_api_calls"]),
            "api_calls": 0,
            "last_instrument_id": 0,
            "work_units_completed": 0,
            "initial_work_units_completed": 0,
            "work_units_failed": 0,
            "rows_fetched": 0,
            "rows_inserted": 0,
            "rows_rejected": 0,
            "complete": False,
        }
        self._persist_checkpoint(connection, run_id=run_id, checkpoint=checkpoint)
        return run_id, check_run_id, checkpoint

    @staticmethod
    def _load_resume_checkpoint(
        connection: Any,
        *,
        resume_run_id: int | None,
    ) -> dict[str, Any] | None:
        if resume_run_id is None:
            return None
        row = connection.execute(
            select(
                ingestion_task_run.c.job_name,
                ingestion_task_run.c.checkpoint_json,
            ).where(ingestion_task_run.c.run_id == resume_run_id)
        ).mappings().one_or_none()
        if row is None:
            raise ValueError(f"corporate-action run_id {resume_run_id} does not exist")
        if row["job_name"] != CorporateActionsHistoryJob.job_name:
            raise ValueError(f"run_id {resume_run_id} is not a corporate-action job")
        checkpoint = row["checkpoint_json"]
        if not isinstance(checkpoint, dict) or checkpoint.get("version") != CHECKPOINT_VERSION:
            raise ValueError(f"run_id {resume_run_id} has no compatible checkpoint")
        if checkpoint.get("complete"):
            raise ValueError(f"run_id {resume_run_id} is already complete")
        return dict(checkpoint)

    @staticmethod
    def _apply_resume_budget(
        parameters: dict[str, Any],
        checkpoint: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if checkpoint is None:
            limit = int(parameters["max_api_calls"])
            consumed = 0
        else:
            limit = int(checkpoint["api_units_limit"])
            if parameters["max_api_calls"] is not None and int(parameters["max_api_calls"]) != limit:
                raise ValueError(
                    f"resume max_api_calls must remain {limit}; start a new run for a new budget"
                )
            consumed = int(checkpoint["api_calls"])
        return {
            **parameters,
            "max_api_calls": limit,
            "remaining_api_calls": max(limit - consumed, 0),
        }

    def _validate_fingerprint(
        self,
        parameters: dict[str, Any],
        checkpoint: dict[str, Any] | None,
    ) -> None:
        if checkpoint is None:
            return
        actual = self._fingerprint(parameters)
        if checkpoint.get("fingerprint") != actual:
            raise ValueError("resume options do not match the original corporate-action run")

    @staticmethod
    def _fingerprint(parameters: dict[str, Any]) -> str:
        identity = {
            key: parameters.get(key)
            for key in (
                "symbols",
                "action_types",
                "asset_type",
                "instrument_status",
                "market",
                "date_from",
                "date_to",
                "limit",
            )
        }
        payload = json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _persist_checkpoint(
        connection: Any,
        *,
        run_id: int,
        checkpoint: dict[str, Any],
    ) -> None:
        connection.execute(
            update(ingestion_task_run)
            .where(ingestion_task_run.c.run_id == run_id)
            .values(checkpoint_json=dict(checkpoint))
        )

    @staticmethod
    def _concise(exc: Exception) -> str:
        return f"{type(exc).__name__}: {exc}"[:1000]
