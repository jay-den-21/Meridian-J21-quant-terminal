"""Guarded EODHD ID Mapping ingest shared by CLI, menu, and Python."""

from __future__ import annotations

from math import ceil
from typing import Any

from sqlalchemy import func, select

from fdp.get_data.api_budget import remote_api_capacity_metrics
from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
)
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.id_mapping import parse_identifier_mapping_envelope
from fdp.sources.eodhd.ingest import process_identifier_mapping_page
from fdp.sources.eodhd.ingest.common import (
    create_task_run,
    finish_task_run,
    normalize_provider_symbols,
    record_api_call,
)
from fdp.sources.eodhd.ingest.id_mapping import IdentifierMappingPageResult
from fdp.sources.eodhd.retry import EodhdApiBudgetExceeded, WeightedApiBudget
from fdp.storage.schema import ensure_runtime_schemas
from fdp.storage.tables import instrument


DEFAULT_PAGE_LIMIT = 1000
DEFAULT_MAX_API_CALLS = 200
SUPPORTED_EXCHANGE = "US"


class IdentifierMappingJob:
    """Synchronize undated EODHD crosswalk aliases into identifier history."""

    job_key = "ingest.id_mappings"
    job_module = "fdp.get_data.reference.get_id_mappings"

    def preflight(
        self,
        *,
        exchange: str | None = None,
        symbols: list[str] | None = None,
        page_limit: int | None = None,
        start_offset: int | None = None,
        max_api_calls: int | None = None,
        max_requests_per_minute: int | None = None,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        active_runtime = runtime or JobRuntime.from_env()
        parameters, sources = self._resolve_options(
            exchange=exchange,
            symbols=symbols,
            page_limit=page_limit,
            start_offset=start_offset,
            max_api_calls=max_api_calls,
            max_requests_per_minute=max_requests_per_minute,
            runtime=active_runtime,
            override_source=override_source,
        )
        warnings = [
            "EODHD ID Mapping has no effective dates; stored values are undated aliases, not current-only or PIT history"
        ]
        if parameters["scope"] == "exchange":
            with active_runtime.engine.connect() as connection:
                local_rows = self._count_local_instruments(
                    connection,
                    market=SUPPORTED_EXCHANGE,
                )
            remaining_rows = max(local_rows - parameters["start_offset"], 0)
            estimated_calls = max(1, ceil(remaining_rows / parameters["page_limit"]))
            if estimated_calls > parameters["max_api_calls"]:
                warnings.append(
                    "local page estimate exceeds the hard API budget; execution will stop with next_offset"
                )
            estimated_rows = local_rows
            work_units = min(estimated_calls, parameters["max_api_calls"])
        else:
            estimated_calls = len(parameters["symbols"])
            estimated_rows = estimated_calls
            work_units = estimated_calls
            if estimated_calls > parameters["max_api_calls"]:
                raise ValueError(
                    f"symbol count {estimated_calls} exceeds max-api-calls "
                    f"{parameters['max_api_calls']}"
                )
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=[
                "instrument_identifier_history",
                "system.identifier_mapping_unmatched_observation",
            ],
            work_units=work_units,
            estimated_api_calls=estimated_calls,
            estimated_rows=estimated_rows,
            parameters=parameters,
            parameter_sources=sources,
            warnings=warnings,
        )

    def run(
        self,
        *,
        exchange: str | None = None,
        symbols: list[str] | None = None,
        page_limit: int | None = None,
        start_offset: int | None = None,
        max_api_calls: int | None = None,
        max_requests_per_minute: int | None = None,
        execute: bool = True,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        preflight: JobPreflight | None = None,
        override_source: str = "python",
    ) -> JobResult:
        active_runtime = runtime or JobRuntime.from_env()
        active_preflight = preflight or self.preflight(
            exchange=exchange,
            symbols=symbols,
            page_limit=page_limit,
            start_offset=start_offset,
            max_api_calls=max_api_calls,
            max_requests_per_minute=max_requests_per_minute,
            runtime=active_runtime,
            override_source=override_source,
        )
        parameters = active_preflight.parameters
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
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            run_id = create_task_run(
                connection,
                market=SUPPORTED_EXCHANGE,
                job_name="eodhd_id_mapping",
                target_table="instrument_identifier_history",
            )

        active_reporter.on_event(
            ProgressEvent(
                "start",
                self.job_key,
                0,
                active_preflight.work_units,
                message="ID mapping started",
            )
        )
        preflight_api_calls = 0
        try:
            remote_client = active_runtime.client(
                active_reporter,
                max_requests_per_minute=parameters["max_requests_per_minute"],
            )
            user_response = remote_client.get_user()
            preflight_api_calls = user_response.retry_count + 1
            with active_runtime.engine.begin() as connection:
                record_api_call(connection, run_id=run_id, response=user_response)
        except KeyboardInterrupt:
            return self._finish_early_failure(
                runtime=active_runtime,
                reporter=active_reporter,
                run_id=run_id,
                preflight=active_preflight,
                message="operator cancelled ID mapping during User API preflight",
                category="cancelled",
                api_calls=preflight_api_calls,
                status="cancelled",
            )
        except Exception as exc:
            return self._finish_early_failure(
                runtime=active_runtime,
                reporter=active_reporter,
                run_id=run_id,
                preflight=active_preflight,
                message=f"EODHD User API preflight failed: {exc}",
                category="runtime_error",
                api_calls=preflight_api_calls,
            )
        try:
            remote_budget = remote_api_capacity_metrics(
                user_response,
                required_units=parameters["max_api_calls"],
            )
        except ValueError as exc:
            return self._finish_early_failure(
                runtime=active_runtime,
                reporter=active_reporter,
                run_id=run_id,
                preflight=active_preflight,
                message=str(exc),
                category="api_budget",
                api_calls=preflight_api_calls,
            )

        api_budget = WeightedApiBudget(parameters["max_api_calls"])
        try:
            client = active_runtime.client(
                active_reporter,
                max_requests_per_minute=parameters["max_requests_per_minute"],
                api_budget=api_budget,
            )
        except KeyboardInterrupt:
            return self._finish_early_failure(
                runtime=active_runtime,
                reporter=active_reporter,
                run_id=run_id,
                preflight=active_preflight,
                message="operator cancelled ID mapping during mapping client initialization",
                category="cancelled",
                api_calls=preflight_api_calls,
                status="cancelled",
            )
        except Exception as exc:
            return self._finish_early_failure(
                runtime=active_runtime,
                reporter=active_reporter,
                run_id=run_id,
                preflight=active_preflight,
                message=f"EODHD mapping client initialization failed: {exc}",
                category="runtime_error",
                api_calls=preflight_api_calls,
            )

        pages: list[IdentifierMappingPageResult] = []
        failures: list[JobFailure] = []
        missing_symbols: list[str] = []
        next_offset: int | None = None
        remote_total: int | None = None
        work_completed = 0
        cancelled = False
        try:
            if parameters["scope"] == "exchange":
                next_offset, remote_total, work_completed, cancelled = (
                    self._run_exchange_pages(
                        active_runtime,
                        client,
                        run_id=run_id,
                        exchange=parameters["exchange"],
                        page_limit=parameters["page_limit"],
                        start_offset=parameters["start_offset"],
                        pages=pages,
                        failures=failures,
                        reporter=active_reporter,
                        progress_total=active_preflight.work_units,
                    )
                )
            else:
                work_completed, missing_symbols, cancelled = self._run_symbols(
                    active_runtime,
                    client,
                    run_id=run_id,
                    symbols=parameters["symbols"],
                    page_limit=parameters["page_limit"],
                    pages=pages,
                    failures=failures,
                    reporter=active_reporter,
                )
        except Exception as exc:  # final safety boundary records committed-page facts
            failures.append(
                JobFailure(
                    "id-mappings",
                    "runtime_error",
                    self._concise_exception(exc),
                )
            )

        totals = self._page_totals(pages)
        budget_snapshot = api_budget.snapshot()
        api_calls = preflight_api_calls + budget_snapshot.consumed
        status, error_message = self._status(
            totals=totals,
            failures=failures,
            next_offset=next_offset,
            cancelled=cancelled,
        )
        with active_runtime.engine.begin() as connection:
            finish_task_run(
                connection,
                run_id=run_id,
                status=status,
                rows_fetched=totals["rows_fetched"],
                rows_inserted=totals["identifiers_inserted"],
                rows_updated=totals["identifiers_unchanged"],
                rows_rejected=totals["rows_unmatched"],
                api_calls=api_calls,
                error_message=error_message,
            )

        actual_total = max(active_preflight.work_units, work_completed)
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                self.job_key,
                work_completed,
                actual_total,
                message=status,
                counters={
                    "fetched": totals["rows_fetched"],
                    "inserted": totals["identifiers_inserted"],
                    "unmatched": totals["rows_unmatched"],
                    "api_calls": api_calls,
                },
            )
        )
        return JobResult(
            job=self.job_key,
            status=status,
            run_id=run_id,
            parameters=parameters,
            parameter_sources=active_preflight.parameter_sources,
            rows_fetched=totals["rows_fetched"],
            rows_matched=totals["rows_matched"],
            rows_inserted=totals["identifiers_inserted"],
            rows_rejected=totals["rows_invalid"],
            rows_unmatched=totals["rows_unmatched"],
            api_calls=api_calls,
            work_units_total=actual_total,
            work_units_completed=work_completed,
            work_units_failed=len(failures),
            missing_symbols=missing_symbols,
            failures=failures,
            metrics={
                "pages_requested": len(pages),
                "identifiers_unchanged": totals["identifiers_unchanged"],
                "identifier_conflicts": totals["identifier_conflicts"],
                "remote_total": remote_total,
                "next_offset": next_offset,
                "mapping_api_units_limit": budget_snapshot.limit,
                "mapping_api_units_consumed": budget_snapshot.consumed,
                "mapping_api_units_remaining": budget_snapshot.remaining,
                "task_api_units_consumed": api_calls,
                **remote_budget,
            },
            error_message=error_message,
            preflight=active_preflight,
        )

    @staticmethod
    def _resolve_options(
        *,
        exchange: str | None,
        symbols: list[str] | None,
        page_limit: int | None,
        start_offset: int | None,
        max_api_calls: int | None,
        max_requests_per_minute: int | None,
        runtime: JobRuntime,
        override_source: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        normalized_exchange = exchange.strip().upper() if exchange else None
        normalized_symbols = normalize_provider_symbols(symbols or [])
        if (normalized_exchange is None) == (not normalized_symbols):
            raise ValueError("provide exactly one ID Mapping scope: --exchange or --symbols")
        if normalized_exchange is not None and normalized_exchange != SUPPORTED_EXCHANGE:
            raise ValueError("ID Mapping ingest currently supports exchange US only")
        if any(not symbol.endswith(".US") for symbol in normalized_symbols):
            raise ValueError("ID Mapping symbol scope currently accepts only provider symbols ending .US")

        resolved_limit = page_limit if page_limit is not None else DEFAULT_PAGE_LIMIT
        resolved_offset = start_offset if start_offset is not None else 0
        resolved_max_calls = (
            max_api_calls if max_api_calls is not None else DEFAULT_MAX_API_CALLS
        )
        resolved_rpm = (
            max_requests_per_minute
            if max_requests_per_minute is not None
            else runtime.config.max_requests_per_minute
        )
        if not 1 <= resolved_limit <= 1000:
            raise ValueError("page_limit must be between 1 and 1000")
        if resolved_offset < 0:
            raise ValueError("start_offset must be non-negative")
        if normalized_symbols and resolved_offset:
            raise ValueError("start_offset is only supported with exchange scope")
        if resolved_max_calls <= 0:
            raise ValueError("max_api_calls must be positive")
        if not 1 <= resolved_rpm <= 1000:
            raise ValueError("max_requests_per_minute must be between 1 and 1000")

        parameters = {
            "scope": "exchange" if normalized_exchange is not None else "symbols",
            "exchange": normalized_exchange,
            "symbols": normalized_symbols,
            "market": SUPPORTED_EXCHANGE,
            "page_limit": resolved_limit,
            "start_offset": resolved_offset,
            "max_api_calls": resolved_max_calls,
            "max_requests_per_minute": resolved_rpm,
            "source": "eodhd",
        }
        sources = {
            "scope": override_source,
            "exchange": override_source if exchange is not None else "not_applicable",
            "symbols": override_source if symbols is not None else "not_applicable",
            "market": "job_default",
            "page_limit": override_source if page_limit is not None else "job_default",
            "start_offset": override_source if start_offset is not None else "job_default",
            "max_api_calls": override_source if max_api_calls is not None else "job_default",
            "max_requests_per_minute": (
                override_source if max_requests_per_minute is not None else "runtime_config"
            ),
            "source": "job_default",
        }
        return parameters, sources

    @staticmethod
    def _count_local_instruments(connection: Any, *, market: str) -> int:
        return int(
            connection.execute(
                select(func.count())
                .select_from(instrument)
                .where(instrument.c.provider == "EODHD", instrument.c.market == market)
            ).scalar_one()
        )

    def _run_exchange_pages(
        self,
        runtime: JobRuntime,
        client: Any,
        *,
        run_id: int,
        exchange: str,
        page_limit: int,
        start_offset: int,
        pages: list[IdentifierMappingPageResult],
        failures: list[JobFailure],
        reporter: ProgressReporter,
        progress_total: int,
    ) -> tuple[int | None, int | None, int, bool]:
        offset = start_offset
        remote_total: int | None = None
        completed = 0
        while True:
            try:
                response = client.get_id_mappings(
                    filter_type="ex",
                    filter_value=exchange,
                    limit=page_limit,
                    offset=offset,
                )
                page = self._commit_response(
                    runtime,
                    run_id=run_id,
                    response=response,
                    market=SUPPORTED_EXCHANGE,
                )
            except EodhdApiBudgetExceeded as exc:
                failures.append(JobFailure(str(offset), "api_budget", str(exc)))
                return offset, remote_total, completed, False
            except KeyboardInterrupt:
                failures.append(
                    JobFailure(str(offset), "cancelled", "operator cancelled ID mapping")
                )
                return offset, remote_total, completed, True
            if isinstance(page, JobFailure):
                failures.append(page)
                return offset, remote_total, completed, False
            pages.append(page)
            completed += 1
            remote_total = page.total
            reporter.on_event(
                ProgressEvent(
                    "unit_completed",
                    self.job_key,
                    completed,
                    max(progress_total, completed),
                    unit=f"offset={offset}",
                    counters={
                        "fetched": page.rows_fetched,
                        "inserted": page.identifiers_inserted,
                        "unmatched": page.rows_unmatched,
                    },
                )
            )
            if page.next_offset is None:
                return None, remote_total, completed, False
            offset = page.next_offset

    def _run_symbols(
        self,
        runtime: JobRuntime,
        client: Any,
        *,
        run_id: int,
        symbols: list[str],
        page_limit: int,
        pages: list[IdentifierMappingPageResult],
        failures: list[JobFailure],
        reporter: ProgressReporter,
    ) -> tuple[int, list[str], bool]:
        missing: list[str] = []
        completed = 0
        for symbol in symbols:
            try:
                response = client.get_id_mappings(
                    filter_type="symbol",
                    filter_value=symbol,
                    limit=page_limit,
                    offset=0,
                )
                page = self._commit_response(
                    runtime,
                    run_id=run_id,
                    response=response,
                    market=SUPPORTED_EXCHANGE,
                )
            except EodhdApiBudgetExceeded as exc:
                failures.append(JobFailure(symbol, "api_budget", str(exc)))
                break
            except KeyboardInterrupt:
                failures.append(
                    JobFailure(symbol, "cancelled", "operator cancelled ID mapping")
                )
                return completed, missing, True
            if isinstance(page, JobFailure):
                failures.append(page)
                break
            pages.append(page)
            completed += 1
            if page.rows_fetched == 0:
                missing.append(symbol)
                failures.append(JobFailure(symbol, "no_mapping", "no ID mapping returned"))
            if page.next_offset is not None:
                failures.append(
                    JobFailure(
                        symbol,
                        "unexpected_pagination",
                        "targeted symbol returned more than one page; use exchange scope",
                    )
                )
                break
            reporter.on_event(
                ProgressEvent(
                    "unit_completed",
                    self.job_key,
                    completed,
                    len(symbols),
                    unit=symbol,
                    counters={
                        "fetched": page.rows_fetched,
                        "inserted": page.identifiers_inserted,
                        "unmatched": page.rows_unmatched,
                    },
                )
            )
        return completed, missing, False

    @staticmethod
    def _commit_response(
        runtime: JobRuntime,
        *,
        run_id: int,
        response: Any,
        market: str,
    ) -> IdentifierMappingPageResult | JobFailure:
        with runtime.engine.begin() as connection:
            record_api_call(connection, run_id=run_id, response=response)
        if not response.success:
            return JobFailure(
                response.endpoint,
                "request",
                response.error_message or f"HTTP {response.status_code}",
            )
        try:
            envelope = parse_identifier_mapping_envelope(response.payload)
            with runtime.engine.begin() as connection:
                return process_identifier_mapping_page(
                    connection,
                    run_id=run_id,
                    market=market,
                    envelope=envelope,
                )
        except (TypeError, ValueError) as exc:
            return JobFailure(response.endpoint, "invalid_payload", str(exc))

    @staticmethod
    def _page_totals(pages: list[IdentifierMappingPageResult]) -> dict[str, int]:
        names = (
            "rows_fetched",
            "rows_matched",
            "identifiers_inserted",
            "identifiers_unchanged",
            "rows_unmatched",
            "rows_invalid",
            "identifier_conflicts",
        )
        return {name: sum(getattr(page, name) for page in pages) for name in names}

    @staticmethod
    def _status(
        *,
        totals: dict[str, int],
        failures: list[JobFailure],
        next_offset: int | None,
        cancelled: bool = False,
    ) -> tuple[str, str | None]:
        problems = [failure.message for failure in failures]
        if totals["rows_unmatched"]:
            problems.append(f"{totals['rows_unmatched']} mapping row(s) require reconciliation")
        if next_offset is not None:
            problems.append(f"resume exchange sync from offset {next_offset}")
        if cancelled:
            return "cancelled", "; ".join(problems)
        if not problems:
            return "success", None
        if totals["rows_fetched"] == 0:
            return "failed", "; ".join(problems)
        return "partial_failed", "; ".join(problems)

    def _finish_early_failure(
        self,
        *,
        runtime: JobRuntime,
        reporter: ProgressReporter,
        run_id: int,
        preflight: JobPreflight,
        message: str,
        category: str,
        api_calls: int,
        status: str = "failed",
    ) -> JobResult:
        with runtime.engine.begin() as connection:
            finish_task_run(
                connection,
                run_id=run_id,
                status=status,
                rows_fetched=0,
                rows_inserted=0,
                rows_updated=0,
                rows_rejected=0,
                api_calls=api_calls,
                error_message=message,
            )
        reporter.on_event(
            ProgressEvent(
                "finish",
                self.job_key,
                0,
                preflight.work_units,
                message=status,
                counters={
                    "api_calls": api_calls,
                    "cancelled" if status == "cancelled" else "failed": 1,
                },
            )
        )
        return JobResult(
            job=self.job_key,
            status=status,
            run_id=run_id,
            parameters=preflight.parameters,
            parameter_sources=preflight.parameter_sources,
            api_calls=api_calls,
            work_units_total=preflight.work_units,
            work_units_failed=1,
            failures=[JobFailure("user-api", category, message)],
            error_message=message,
            preflight=preflight,
        )

    @staticmethod
    def _concise_exception(exc: Exception) -> str:
        """Return a bounded operator message without SQL statements or parameters."""
        original = getattr(exc, "orig", None)
        message = str(original if original is not None else exc)
        return " ".join(message.split())[:1000]
