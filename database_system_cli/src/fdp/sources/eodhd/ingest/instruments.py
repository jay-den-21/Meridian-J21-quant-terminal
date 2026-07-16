"""EODHD instrument metadata ingest workflow."""

from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest.common import (
    create_task_run,
    finish_task_run,
    instrument_task_status,
    record_api_call,
)
from fdp.sources.eodhd.ingest.models import (
    SYMBOL_CHANGE_HISTORY_SOURCE,
    SYMBOL_CHANGE_HISTORY_START,
    InstrumentLoadResult,
)
from fdp.sources.eodhd.instruments import (
    SymbolChange,
    parse_exchange_symbol_rows,
    parse_symbol_change_history_rows,
)
from fdp.storage.tables import instrument
from fdp.storage.upsert import build_identifier_history_upsert, build_instrument_upsert


def load_exchange_symbols(
    connection: Connection,
    client: EodhdClient,
    *,
    market: str = "US",
    rename_from: date = SYMBOL_CHANGE_HISTORY_START,
) -> InstrumentLoadResult:
    """Load active EODHD instruments after applying explicit ticker rename events.

    Input: database connection, EODHD client, market, and rename-history start date.
    Output: `InstrumentLoadResult` with task status, row counts, and rejected rows.
    Flow: task_run -> symbol changes -> reconcile -> exchange symbols -> parse -> upsert.
    """
    run_id = create_task_run(connection, market=market)
    symbol_change_response = client.get_symbol_change_history(rename_from)
    record_api_call(connection, run_id=run_id, response=symbol_change_response)

    if not symbol_change_response.success:
        error_message = symbol_change_response.error_message or "EODHD symbol change request failed"
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
        return InstrumentLoadResult(
            run_id=run_id,
            status="failed",
            rows_fetched=0,
            rows_accepted=0,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
            error_message=error_message,
        )

    symbol_changes = parse_symbol_change_history_rows(symbol_change_response.payload, market=market)
    rows_updated = reconcile_symbol_changes(connection, symbol_changes.accepted)

    response = client.get_exchange_symbols(market)
    record_api_call(connection, run_id=run_id, response=response)
    api_calls = 2

    if not response.success:
        error_message = response.error_message or "EODHD exchange symbols request failed"
        finish_task_run(
            connection,
            run_id=run_id,
            status="failed",
            rows_fetched=0,
            rows_inserted=0,
            rows_updated=rows_updated,
            rows_rejected=0,
            api_calls=api_calls,
            error_message=error_message,
        )
        return InstrumentLoadResult(
            run_id=run_id,
            status="failed",
            rows_fetched=0,
            rows_accepted=0,
            rows_rejected=0,
            api_calls=api_calls,
            rejected_rows=[],
            error_message=error_message,
        )

    parsed_rows = parse_exchange_symbol_rows(response.payload, market=market)
    if parsed_rows.accepted:
        connection.execute(build_instrument_upsert(parsed_rows.accepted))

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
        rows_updated=rows_updated,
        rows_rejected=len(parsed_rows.rejected),
        api_calls=api_calls,
        error_message=error_message,
    )

    return InstrumentLoadResult(
        run_id=run_id,
        status=status,
        rows_fetched=response.rows_returned,
        rows_accepted=len(parsed_rows.accepted),
        rows_rejected=len(parsed_rows.rejected),
        api_calls=api_calls,
        rejected_rows=parsed_rows.rejected,
        error_message=error_message,
    )


def reconcile_symbol_changes(connection: Connection, symbol_changes: list[SymbolChange]) -> int:
    """Apply EODHD rename events to existing instruments.

    Input: parsed `SymbolChange` rows from EODHD symbol-change-history.
    Output: count of instruments whose current symbol/provider_symbol were updated.
    Flow: old/new provider_symbol lookup -> safe current update or append-only history upsert.
    """
    reconciled = 0
    for symbol_change in symbol_changes:
        existing_old = _find_eodhd_instrument_id(connection, symbol_change.old_provider_symbol)
        existing_new = _find_eodhd_instrument_id(connection, symbol_change.new_provider_symbol)

        should_update_current = existing_old is not None and (
            existing_new is None or existing_new["instrument_id"] == existing_old["instrument_id"]
        )
        if should_update_current:
            instrument_id = existing_old["instrument_id"]
            update_values = {
                "symbol": symbol_change.new_symbol,
                "provider_symbol": symbol_change.new_provider_symbol,
            }
            if symbol_change.company_name:
                update_values["name"] = symbol_change.company_name

            connection.execute(
                update(instrument)
                .where(instrument.c.instrument_id == instrument_id)
                .values(**update_values)
            )
            reconciled += 1
        elif existing_new is not None:
            instrument_id = existing_new["instrument_id"]
        else:
            continue

        history_rows = _identifier_history_rows(instrument_id, symbol_change)
        connection.execute(build_identifier_history_upsert(history_rows))

    return reconciled


def _find_eodhd_instrument_id(connection: Connection, provider_symbol: str):
    return connection.execute(
        select(instrument.c.instrument_id).where(
            instrument.c.provider == "EODHD",
            instrument.c.provider_symbol == provider_symbol,
        )
    ).mappings().first()


def _identifier_history_rows(instrument_id: int, symbol_change: SymbolChange) -> list[dict[str, object]]:
    """Build ticker/provider-symbol history rows for one rename event.

    Input: existing instrument id and one parsed symbol-change event.
    Output: four rows: old ticker, old provider_symbol, new ticker, new provider_symbol.
    Flow: rename effective date -> close old IDs -> open new IDs.
    """
    old_valid_to = symbol_change.effective - timedelta(days=1)
    return [
        {
            "instrument_id": instrument_id,
            "id_type": "ticker",
            "id_value": symbol_change.old_symbol,
            "valid_from": None,
            "valid_to": old_valid_to,
            "source": SYMBOL_CHANGE_HISTORY_SOURCE,
        },
        {
            "instrument_id": instrument_id,
            "id_type": "provider_symbol",
            "id_value": symbol_change.old_provider_symbol,
            "valid_from": None,
            "valid_to": old_valid_to,
            "source": SYMBOL_CHANGE_HISTORY_SOURCE,
        },
        {
            "instrument_id": instrument_id,
            "id_type": "ticker",
            "id_value": symbol_change.new_symbol,
            "valid_from": symbol_change.effective,
            "valid_to": None,
            "source": SYMBOL_CHANGE_HISTORY_SOURCE,
        },
        {
            "instrument_id": instrument_id,
            "id_type": "provider_symbol",
            "id_value": symbol_change.new_provider_symbol,
            "valid_from": symbol_change.effective,
            "valid_to": None,
            "source": SYMBOL_CHANGE_HISTORY_SOURCE,
        },
    ]
