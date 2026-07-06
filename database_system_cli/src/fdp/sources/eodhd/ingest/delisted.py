"""EODHD delisted/inactive instrument ingest workflow."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest.common import (
    create_task_run,
    finish_task_run,
    instrument_task_status,
    record_api_call,
)
from fdp.sources.eodhd.ingest.models import DelistedInstrumentLoadResult
from fdp.sources.eodhd.instruments import parse_exchange_symbol_rows
from fdp.storage.tables import instrument
from fdp.storage.upsert import (
    build_instrument_lifecycle_event_upsert,
    build_instrument_upsert,
)

DELISTED_SYMBOL_SOURCE = "EODHD_DELISTED_EXCHANGE_SYMBOLS"


def load_delisted_instruments(
    connection: Connection,
    client: EodhdClient,
    *,
    market: str = "US",
) -> DelistedInstrumentLoadResult:
    """Load EODHD inactive stock/ETF instruments and lifecycle events.

    Input: database connection, EODHD client, and market.
    Output: `DelistedInstrumentLoadResult` with task/API/write counts.
    Flow: `delisted=1` symbols -> inactive instruments -> lifecycle events -> task result.
    """
    run_id = create_task_run(
        connection,
        market=market,
        job_name="eodhd_delisted_instruments",
        target_table="instrument",
    )
    response = client.get_delisted_exchange_symbols(market)
    record_api_call(connection, run_id=run_id, response=response)

    if not response.success:
        error_message = response.error_message or "EODHD delisted symbols request failed"
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
        return DelistedInstrumentLoadResult(
            run_id=run_id,
            status="failed",
            rows_fetched=0,
            rows_accepted=0,
            rows_rejected=0,
            lifecycle_events_inserted=0,
            api_calls=1,
            rejected_rows=[],
            error_message=error_message,
        )

    parsed_rows = parse_exchange_symbol_rows(
        response.payload,
        market=market,
        include_inactive=True,
        force_inactive=True,
    )
    lifecycle_events_inserted = 0
    if parsed_rows.accepted:
        connection.execute(build_instrument_upsert(parsed_rows.accepted))
        lifecycle_rows = _lifecycle_event_rows(
            connection,
            instrument_rows=parsed_rows.accepted,
        )
        if lifecycle_rows:
            connection.execute(build_instrument_lifecycle_event_upsert(lifecycle_rows))
            lifecycle_events_inserted = len(lifecycle_rows)

    status, error_message = instrument_task_status(
        rows_fetched=response.rows_returned,
        rows_accepted=len(parsed_rows.accepted),
        rows_rejected=len(parsed_rows.rejected),
    )
    finish_task_run(
        connection,
        run_id=run_id,
        status=status,
        rows_fetched=response.rows_returned,
        rows_inserted=len(parsed_rows.accepted),
        rows_updated=lifecycle_events_inserted,
        rows_rejected=len(parsed_rows.rejected),
        api_calls=1,
        error_message=error_message,
    )

    return DelistedInstrumentLoadResult(
        run_id=run_id,
        status=status,
        rows_fetched=response.rows_returned,
        rows_accepted=len(parsed_rows.accepted),
        rows_rejected=len(parsed_rows.rejected),
        lifecycle_events_inserted=lifecycle_events_inserted,
        api_calls=1,
        rejected_rows=parsed_rows.rejected,
        error_message=error_message,
    )


def _lifecycle_event_rows(
    connection: Connection,
    *,
    instrument_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    provider_symbols = [str(row["provider_symbol"]) for row in instrument_rows]
    instrument_ids = _instrument_ids_by_provider_symbol(connection, provider_symbols)
    rows: list[dict[str, object]] = []

    for row in instrument_rows:
        provider_symbol = str(row["provider_symbol"])
        instrument_id = instrument_ids.get(provider_symbol)
        if instrument_id is None:
            continue
        event_date = row.get("delisted_date")
        rows.append(
            {
                "instrument_id": instrument_id,
                "event_type": "delisted",
                "event_date": event_date,
                "symbol": row["symbol"],
                "provider_symbol": provider_symbol,
                "source": DELISTED_SYMBOL_SOURCE,
                "event_key": _delisted_event_key(provider_symbol, event_date),
                "details": _event_details(row),
            }
        )
    return rows


def _instrument_ids_by_provider_symbol(
    connection: Connection,
    provider_symbols: list[str],
) -> dict[str, int]:
    result = connection.execute(
        select(instrument.c.provider_symbol, instrument.c.instrument_id).where(
            instrument.c.provider == "EODHD",
            instrument.c.provider_symbol.in_(provider_symbols),
        )
    )
    return {
        str(row["provider_symbol"]): int(row["instrument_id"])
        for row in result.mappings()
    }


def _delisted_event_key(provider_symbol: str, event_date: object) -> str:
    if isinstance(event_date, date):
        date_part = event_date.isoformat()
    else:
        date_part = "unknown"
    return f"delisted:{provider_symbol}:{date_part}"


def _event_details(row: dict[str, object]) -> str:
    return (
        f"asset_type={row['asset_type']};"
        f"exchange={row['exchange']};"
        f"currency={row['currency']}"
    )
