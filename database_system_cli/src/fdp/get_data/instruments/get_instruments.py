"""Shared active-instrument and symbol-history ingest job."""

from __future__ import annotations

from datetime import date

from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
)
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.ingest import SYMBOL_CHANGE_HISTORY_START, load_exchange_symbols
from fdp.storage.schema import ensure_runtime_schemas

DEFAULT_MARKET = "US"
DEFAULT_RENAME_FROM = SYMBOL_CHANGE_HISTORY_START


class ActiveInstrumentsJob:
    """Load active instruments and reconcile EODHD symbol changes."""

    job_key = "ingest.instruments"
    job_module = "fdp.get_data.instruments.get_instruments"

    def preflight(
        self,
        *,
        market: str | None = None,
        rename_from: date | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        parameters = {
            "market": (market or DEFAULT_MARKET).upper(),
            "rename_from": rename_from or DEFAULT_RENAME_FROM,
            "source": "eodhd",
        }
        sources = {
            "market": override_source if market is not None else "job_default",
            "rename_from": override_source if rename_from is not None else "job_default",
            "source": "job_default",
        }
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=["instrument", "instrument_identifier_history"],
            work_units=2,
            estimated_api_calls=2,
            parameters=parameters,
            parameter_sources=sources,
        )

    def run(
        self,
        *,
        market: str | None = None,
        rename_from: date | None = None,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        override_source: str = "python",
        preflight: JobPreflight | None = None,
    ) -> JobResult:
        active_runtime = runtime or JobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()
        active_preflight = preflight or self.preflight(
            market=market,
            rename_from=rename_from,
            override_source=override_source,
        )
        parameters = active_preflight.parameters
        active_reporter.on_event(ProgressEvent("start", self.job_key, 0, 2))
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            result = load_exchange_symbols(
                connection,
                active_runtime.client(active_reporter),
                market=str(parameters["market"]),
                rename_from=parameters["rename_from"],
            )
        failed = 0 if result.status == "success" else 1
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                self.job_key,
                2,
                2,
                message=result.status,
                counters={
                    "fetched": result.rows_fetched,
                    "inserted": result.rows_accepted,
                    "rejected": result.rows_rejected,
                    "failed": failed,
                    "api_calls": result.api_calls,
                },
            )
        )
        failures = (
            [JobFailure("instruments", "request", result.error_message or result.status)]
            if failed
            else []
        )
        return JobResult(
            job=self.job_key,
            status=result.status,
            run_id=result.run_id,
            parameters=parameters,
            parameter_sources=active_preflight.parameter_sources,
            rows_fetched=result.rows_fetched,
            rows_matched=result.rows_accepted,
            rows_inserted=result.rows_accepted,
            rows_rejected=result.rows_rejected,
            api_calls=result.api_calls,
            work_units_total=2,
            work_units_completed=2,
            work_units_failed=failed,
            failures=failures,
            error_message=result.error_message,
            preflight=active_preflight,
        )
