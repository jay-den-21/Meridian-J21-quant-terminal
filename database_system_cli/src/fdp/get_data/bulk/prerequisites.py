"""Read-only planning and explicit execution of Bulk Daily prerequisites."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from sqlalchemy import func, select

from fdp.get_data.contracts import ProgressReporter
from fdp.get_data.historical.get_market_calendar import MarketCalendarJob
from fdp.get_data.instruments.get_delisted_instruments import DelistedInstrumentsJob
from fdp.get_data.instruments.get_instruments import ActiveInstrumentsJob
from fdp.get_data.runtime import JobRuntime
from fdp.get_data.task_ledger import utc_now
from fdp.sources.eodhd.client import EodhdClient
from fdp.storage.tables import ingestion_task_run, market_calendar

ACTIVE_INSTRUMENT_MAX_AGE = timedelta(days=1)
INACTIVE_INSTRUMENT_MAX_AGE = timedelta(days=7)


@dataclass(frozen=True)
class DailyPrerequisitePlan:
    calendar_refresh: bool
    active_instrument_refresh: bool
    inactive_instrument_refresh: bool
    estimated_api_units: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class DailyPrerequisiteResult:
    api_calls: int
    rows_fetched: int
    rows_inserted: int
    review_required: bool
    jobs: tuple[dict[str, object], ...]


def plan_daily_prerequisites(
    runtime: JobRuntime,
    *,
    date_from: date,
    date_to: date,
    market: str,
    instrument_status: str,
    now: datetime | None = None,
) -> DailyPrerequisitePlan:
    """Inspect local coverage/freshness without constructing an API client."""
    timestamp = now or utc_now()
    with runtime.engine.connect() as connection:
        expected_days = (date_to - date_from).days + 1
        calendar_days = int(
            connection.execute(
                select(func.count())
                .select_from(market_calendar)
                .where(
                    market_calendar.c.calendar_date >= date_from,
                    market_calendar.c.calendar_date <= date_to,
                )
            ).scalar_one()
        )
        active_finished = connection.execute(
            _latest_successful_job("eodhd_exchange_symbols", market=market)
        ).scalar_one_or_none()
        inactive_finished = connection.execute(
            _latest_successful_job("eodhd_delisted_instruments", market=market)
        ).scalar_one_or_none()

    calendar_refresh = calendar_days < expected_days
    active_refresh = _is_stale(
        active_finished,
        now=timestamp,
        max_age=ACTIVE_INSTRUMENT_MAX_AGE,
    )
    inactive_refresh = instrument_status == "all" and _is_stale(
        inactive_finished,
        now=timestamp,
        max_age=INACTIVE_INSTRUMENT_MAX_AGE,
    )
    warnings: list[str] = []
    if calendar_refresh:
        warnings.append(
            "market calendar coverage is incomplete and will be refreshed after confirmation"
        )
    if active_refresh:
        warnings.append(
            "active instrument master is missing/stale and will be refreshed after confirmation"
        )
    if inactive_refresh:
        warnings.append(
            "inactive instrument master is missing/stale and will be refreshed after confirmation"
        )
    estimated_api_units = (
        int(calendar_refresh)
        + 2 * int(active_refresh)
        + int(inactive_refresh)
    )
    return DailyPrerequisitePlan(
        calendar_refresh=calendar_refresh,
        active_instrument_refresh=active_refresh,
        inactive_instrument_refresh=inactive_refresh,
        estimated_api_units=estimated_api_units,
        warnings=tuple(warnings),
    )


def execute_daily_prerequisites(
    runtime: JobRuntime,
    client: EodhdClient,
    *,
    plan: DailyPrerequisitePlan,
    date_from: date,
    date_to: date,
    market: str,
    reporter: ProgressReporter,
) -> DailyPrerequisiteResult:
    """Execute only planned prerequisites through the shared budgeted client."""
    child_runtime = JobRuntime(
        engine=runtime.engine,
        config=runtime.config,
        injected_client=client,
    )
    results = []
    if plan.calendar_refresh:
        results.append(
            MarketCalendarJob().run(
                date_from=date_from,
                date_to=date_to,
                market=market,
                runtime=child_runtime,
                reporter=reporter,
                override_source="prerequisite",
            )
        )
    if plan.active_instrument_refresh:
        results.append(
            ActiveInstrumentsJob().run(
                market=market,
                runtime=child_runtime,
                reporter=reporter,
                override_source="prerequisite",
            )
        )
    if plan.inactive_instrument_refresh:
        results.append(
            DelistedInstrumentsJob().run(
                market=market,
                runtime=child_runtime,
                reporter=reporter,
                override_source="prerequisite",
            )
        )
    failed = [result for result in results if result.status in {"failed", "cancelled"}]
    if failed:
        messages = [
            f"{result.job}:{result.status}:{result.error_message or '-'}"
            for result in failed
        ]
        raise RuntimeError("Daily prerequisite failed; Bulk fetch not started: " + "; ".join(messages))
    return DailyPrerequisiteResult(
        api_calls=sum(result.api_calls for result in results),
        rows_fetched=sum(result.rows_fetched for result in results),
        rows_inserted=sum(result.rows_inserted for result in results),
        review_required=any(result.status == "partial_failed" for result in results),
        jobs=tuple(
            {
                "job": result.job,
                "run_id": result.run_id,
                "status": result.status,
                "api_calls": result.api_calls,
            }
            for result in results
        ),
    )


def _latest_successful_job(job_name: str, *, market: str):
    return select(func.max(ingestion_task_run.c.finished_at)).where(
        ingestion_task_run.c.job_name == job_name,
        ingestion_task_run.c.market == market.upper(),
        ingestion_task_run.c.status.in_(("success", "partial_failed")),
    )


def _is_stale(
    value: object,
    *,
    now: datetime,
    max_age: timedelta,
) -> bool:
    if not isinstance(value, datetime):
        return True
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    return now - value > max_age
