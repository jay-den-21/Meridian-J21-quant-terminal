"""EODHD market calendar ingest workflow."""

from datetime import date

from sqlalchemy.engine import Connection

from fdp.sources.eodhd.calendar import build_market_calendar_rows
from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest.common import (
    create_task_run,
    finish_task_run,
    holiday_count,
    record_api_call,
    single_payload,
)
from fdp.sources.eodhd.ingest.models import MarketCalendarLoadResult
from fdp.storage.upsert import build_market_calendar_upsert


def load_market_calendar(
    connection: Connection,
    client: EodhdClient,
    *,
    date_from: date,
    date_to: date,
    market: str = "US",
) -> MarketCalendarLoadResult:
    """Load a daily market calendar from EODHD exchange-details.

    Input: market and inclusive date range.
    Output: `MarketCalendarLoadResult` with generated row and API counts.
    Flow: exchange details -> daily calendar rows -> market_calendar upsert.
    """
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")

    run_id = create_task_run(
        connection,
        market=market,
        job_name="eodhd_market_calendar",
        target_table="market_calendar",
        date_from=date_from,
        date_to=date_to,
    )

    details_response = client.get_exchange_details(market, date_from=date_from, date_to=date_to)
    record_api_call(
        connection,
        run_id=run_id,
        response=details_response,
        date_from=date_from,
        date_to=date_to,
    )
    if not details_response.success:
        error_message = details_response.error_message or "EODHD exchange details request failed"
        finish_task_run(
            connection,
            run_id=run_id,
            status="failed",
            rows_fetched=0,
            rows_inserted=0,
            rows_updated=0,
            rows_rejected=0,
            api_calls=1,
            error_message=error_message,
        )
        return MarketCalendarLoadResult(
            run_id=run_id,
            status="failed",
            rows_fetched=0,
            rows_inserted=0,
            rows_rejected=0,
            api_calls=1,
            error_message=error_message,
        )

    exchange_details = single_payload(details_response)
    calendar_rows = build_market_calendar_rows(
        exchange_details,
        date_from=date_from,
        date_to=date_to,
        market=market,
    )
    connection.execute(build_market_calendar_upsert(calendar_rows))

    rows_fetched = holiday_count(exchange_details)
    finish_task_run(
        connection,
        run_id=run_id,
        status="success",
        rows_fetched=rows_fetched,
        rows_inserted=len(calendar_rows),
        rows_updated=0,
        rows_rejected=0,
        api_calls=1,
        error_message=None,
    )

    return MarketCalendarLoadResult(
        run_id=run_id,
        status="success",
        rows_fetched=rows_fetched,
        rows_inserted=len(calendar_rows),
        rows_rejected=0,
        api_calls=1,
        error_message=None,
    )
