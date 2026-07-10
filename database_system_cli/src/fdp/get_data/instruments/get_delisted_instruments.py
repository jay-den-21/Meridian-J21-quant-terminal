"""Shared delisted/inactive instrument ingest job."""

from __future__ import annotations

from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
)
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.ingest import load_delisted_instruments
from fdp.storage.schema import ensure_runtime_schemas

DEFAULT_MARKET = "US"


class DelistedInstrumentsJob:
    """Load EODHD inactive instruments and lifecycle observations."""

    job_key = "ingest.delisted_instruments"
    job_module = "fdp.get_data.instruments.get_delisted_instruments"

    def preflight(
        self,
        *,
        market: str | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=["instrument", "instrument_lifecycle_event"],
            work_units=1,
            estimated_api_calls=1,
            parameters={"market": (market or DEFAULT_MARKET).upper(), "source": "eodhd"},
            parameter_sources={
                "market": override_source if market is not None else "job_default",
                "source": "job_default",
            },
        )

    def run(
        self,
        *,
        market: str | None = None,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        override_source: str = "python",
        preflight: JobPreflight | None = None,
    ) -> JobResult:
        active_runtime = runtime or JobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()
        active_preflight = preflight or self.preflight(
            market=market,
            override_source=override_source,
        )
        parameters = active_preflight.parameters
        active_reporter.on_event(ProgressEvent("start", self.job_key, 0, 1))
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            result = load_delisted_instruments(
                connection,
                active_runtime.client(active_reporter),
                market=str(parameters["market"]),
            )
        failed = 0 if result.status == "success" else 1
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                self.job_key,
                1,
                1,
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
            [JobFailure("delisted-instruments", "request", result.error_message or result.status)]
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
            rows_inserted=result.rows_accepted + result.lifecycle_events_inserted,
            rows_rejected=result.rows_rejected,
            api_calls=result.api_calls,
            work_units_total=1,
            work_units_completed=1,
            work_units_failed=failed,
            failures=failures,
            metrics={"lifecycle_events_inserted": result.lifecycle_events_inserted},
            error_message=result.error_message,
            preflight=active_preflight,
        )
