"""Reusable script entrypoint for historical US market calendar rows."""

from datetime import date

from sqlalchemy.engine import Connection

from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
    resolved_value,
)
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import MarketCalendarLoadResult, load_market_calendar
from fdp.storage.schema import ensure_runtime_schemas

DEFAULT_DATE_FROM: date | None = None
DEFAULT_DATE_TO: date | None = None
DEFAULT_MARKET = "US"


class MarketCalendarJob:
    """Market-calendar job shared by CLI, menu, and Python callers."""

    job_key = "ingest.calendar"
    job_module = "fdp.get_data.historical.get_market_calendar"

    def preflight(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        market: str | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        parameters, sources = self._resolve(
            date_from=date_from,
            date_to=date_to,
            market=market,
            override_source=override_source,
        )
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=["market_calendar"],
            work_units=1,
            estimated_api_calls=1,
            parameters=parameters,
            parameter_sources=sources,
            estimated_rows=(parameters["date_to"] - parameters["date_from"]).days + 1,
        )

    def run(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        market: str | None = None,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        override_source: str = "python",
        preflight: JobPreflight | None = None,
    ) -> JobResult:
        active_runtime = runtime or JobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()
        active_preflight = preflight or self.preflight(
            date_from=date_from,
            date_to=date_to,
            market=market,
            override_source=override_source,
        )
        parameters = active_preflight.parameters
        active_reporter.on_event(
            ProgressEvent("start", self.job_key, 0, 1, message="calendar ingest started")
        )
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            result = load_market_calendar(
                connection,
                active_runtime.client(active_reporter),
                date_from=parameters["date_from"],
                date_to=parameters["date_to"],
                market=parameters["market"],
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
                    "inserted": result.rows_inserted,
                    "rejected": result.rows_rejected,
                    "failed": failed,
                    "api_calls": result.api_calls,
                },
            )
        )
        failures = (
            [JobFailure("calendar", "request", result.error_message or result.status)]
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
            rows_inserted=result.rows_inserted,
            rows_rejected=result.rows_rejected,
            api_calls=result.api_calls,
            work_units_total=1,
            work_units_completed=1,
            work_units_failed=failed,
            failures=failures,
            error_message=result.error_message,
            preflight=active_preflight,
        )

    @staticmethod
    def _resolve(
        *,
        date_from: date | None,
        date_to: date | None,
        market: str | None,
        override_source: str,
    ) -> tuple[dict[str, object], dict[str, str]]:
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
        resolved_market, market_source = resolved_value(
            market,
            DEFAULT_MARKET,
            name="market",
            explicit_source=override_source,
        )
        return (
            {
                "date_from": resolved_from,
                "date_to": resolved_to,
                "market": str(resolved_market).upper(),
            },
            {
                "date_from": from_source,
                "date_to": to_source,
                "market": market_source,
            },
        )


def get_market_calendar(
    connection: Connection,
    client: EodhdClient,
    *,
    date_from: date,
    date_to: date,
    market: str = "US",
) -> MarketCalendarLoadResult:
    """Load market calendar rows for an inclusive date range.

    Input: database connection, EODHD client, market, and date range.
    Output: market calendar load summary.
    Flow: exchange details -> trading-day rows -> market_calendar upsert.
    """
    return load_market_calendar(
        connection,
        client,
        date_from=date_from,
        date_to=date_to,
        market=market,
    )
