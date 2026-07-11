"""EODHD historical daily price ingest workflows."""

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.identity import (
    DatedInstrumentIdentityResolver,
    InstrumentIdentityResolution,
)
from fdp.sources.eodhd.ingest.common import (
    InstrumentStatus,
    create_task_run,
    finish_task_run,
    historical_price_status,
    index_instrument_rows,
    load_active_instruments,
    load_active_instruments_by_ids,
    load_active_instruments_by_provider_symbols,
    normalize_provider_symbols,
    normalize_symbols,
    now_utc,
    record_api_call,
)
from fdp.sources.eodhd.ingest.models import (
    BulkDailyPriceLoadResult,
    HistoricalDailyPriceLoadResult,
    HistoricalDailyPriceUnitResult,
)
from fdp.sources.eodhd.prices import RejectedDailyPriceRow, parse_daily_price_rows
from fdp.storage.upsert import (
    build_bulk_unmatched_daily_price_observation_upsert,
    build_daily_price_upsert,
    build_instrument_upsert,
)

BULK_DAILY_UPSERT_CHUNK_SIZE = 1000


def load_historical_daily_prices(
    connection: Connection,
    client: EodhdClient,
    *,
    symbols: list[str],
    date_from: date,
    date_to: date,
    market: str = "US",
    include_inactive: bool = False,
    instrument_status: InstrumentStatus = "active",
) -> HistoricalDailyPriceLoadResult:
    """Load historical daily EOD prices for an explicit stock/ETF symbol list.

    Input: active database instruments selected by current standard symbols.
    Output: `HistoricalDailyPriceLoadResult` with API, parse, and write counts.
    Flow: symbols -> stock/ETF instruments -> EODHD `/eod/{provider_symbol}` -> split-table upsert.
    """
    return _load_symbol_daily_prices(
        connection,
        client,
        symbols=symbols,
        date_from=date_from,
        date_to=date_to,
        market=market,
        asset_types=["stock", "etf", "fund"],
        include_inactive=include_inactive,
        instrument_status=instrument_status,
        job_name="eodhd_historical_daily_price",
        target_table="stock_daily_price,etf_daily_price,fund_daily_price",
    )


def load_stock_daily_prices(
    connection: Connection,
    client: EodhdClient,
    *,
    symbols: list[str],
    date_from: date,
    date_to: date,
    market: str = "US",
    include_inactive: bool = False,
    instrument_status: InstrumentStatus = "active",
) -> HistoricalDailyPriceLoadResult:
    """Load historical daily EOD prices for stock symbols only.

    Input: active database instruments selected by current stock symbols.
    Output: `HistoricalDailyPriceLoadResult` with API, parse, and write counts.
    Flow: symbols -> stock instruments -> EODHD `/eod/{provider_symbol}` -> stock table upsert.
    """
    return _load_symbol_daily_prices(
        connection,
        client,
        symbols=symbols,
        date_from=date_from,
        date_to=date_to,
        market=market,
        asset_types=["stock"],
        include_inactive=include_inactive,
        instrument_status=instrument_status,
        job_name="eodhd_stock_daily_price",
        target_table="stock_daily_price",
    )


def load_etf_daily_prices(
    connection: Connection,
    client: EodhdClient,
    *,
    symbols: list[str],
    date_from: date,
    date_to: date,
    market: str = "US",
    include_inactive: bool = False,
    instrument_status: InstrumentStatus = "active",
) -> HistoricalDailyPriceLoadResult:
    """Load historical daily EOD prices for ETF symbols only.

    Input: active database instruments selected by current ETF symbols.
    Output: `HistoricalDailyPriceLoadResult` with API, parse, and write counts.
    Flow: symbols -> ETF instruments -> EODHD `/eod/{provider_symbol}` -> ETF table upsert.
    """
    return _load_symbol_daily_prices(
        connection,
        client,
        symbols=symbols,
        date_from=date_from,
        date_to=date_to,
        market=market,
        asset_types=["etf"],
        include_inactive=include_inactive,
        instrument_status=instrument_status,
        job_name="eodhd_etf_daily_price",
        target_table="etf_daily_price",
    )


def load_fund_daily_prices(
    connection: Connection,
    client: EodhdClient,
    *,
    symbols: list[str],
    date_from: date,
    date_to: date,
    market: str = "US",
    include_inactive: bool = False,
    instrument_status: InstrumentStatus = "active",
) -> HistoricalDailyPriceLoadResult:
    """Load historical daily EOD prices for Fund symbols only."""
    return _load_symbol_daily_prices(
        connection,
        client,
        symbols=symbols,
        date_from=date_from,
        date_to=date_to,
        market=market,
        asset_types=["fund"],
        include_inactive=include_inactive,
        instrument_status=instrument_status,
        job_name="eodhd_fund_daily_price",
        target_table="fund_daily_price",
    )


def load_daily_prices_for_instrument_ids(
    connection: Connection,
    client: EodhdClient,
    *,
    instrument_ids: list[int],
    date_from: date,
    date_to: date,
    market: str = "US",
    asset_types: list[str] | None = None,
    job_name: str = "eodhd_repair_daily_price",
    target_table: str = (
        "stock_daily_price,etf_daily_price,fund_daily_price,index_daily_price"
    ),
) -> HistoricalDailyPriceLoadResult:
    """Load historical daily prices for exact database instrument ids.

    Input: immutable `instrument_id` values selected by a repair/quality workflow.
    Output: `HistoricalDailyPriceLoadResult` with API, parse, and write counts.
    Flow: instrument ids -> active EODHD instruments -> EOD API calls -> split-table upsert.
    """
    if not instrument_ids:
        raise ValueError("instrument_ids must not be empty")
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")

    unique_ids = list(dict.fromkeys(int(instrument_id) for instrument_id in instrument_ids))
    run_id = create_task_run(
        connection,
        market=market,
        job_name=job_name,
        target_table=target_table,
        date_from=date_from,
        date_to=date_to,
    )
    instruments = load_active_instruments_by_ids(
        connection,
        instrument_ids=unique_ids,
        market=market,
        asset_types=asset_types,
    )
    found_ids = {int(row["instrument_id"]) for row in instruments}
    missing_ids = [str(instrument_id) for instrument_id in unique_ids if instrument_id not in found_ids]

    return _load_daily_prices_for_instruments(
        connection,
        client,
        run_id=run_id,
        instruments=instruments,
        requested_count=len(unique_ids),
        missing_symbols=missing_ids,
        date_from=date_from,
        date_to=date_to,
    )


def load_bulk_daily_prices(
    connection: Connection,
    client: EodhdClient,
    *,
    exchange: str = "US",
    trade_date: date | None = None,
    symbols: list[str] | None = None,
    market: str = "US",
    asset_types: list[str] | None = None,
    instrument_status: InstrumentStatus = "active",
    identity_resolver: DatedInstrumentIdentityResolver | None = None,
) -> BulkDailyPriceLoadResult:
    """Load one-day bulk EOD prices through point-in-time instrument identity.

    Input: EODHD exchange, optional trade date, optional symbols, and market scope.
    Output: `BulkDailyPriceLoadResult` with API, match, parse, and write counts.
    Flow: bulk API -> dated identifier history/current identity -> parse -> split-table upsert.
    """
    normalized_exchange = exchange.strip().upper()
    normalized_asset_types = asset_types or ["stock", "etf", "fund"]
    normalized_symbols = normalize_symbols(symbols or [])
    run_id = create_task_run(
        connection,
        market=market,
        job_name="eodhd_bulk_daily_price",
        target_table=",".join(f"{asset_type}_daily_price" for asset_type in normalized_asset_types),
        date_from=trade_date,
        date_to=trade_date,
    )

    response = client.get_bulk_eod(
        normalized_exchange,
        trade_date=trade_date,
        symbols=normalized_symbols or None,
    )
    record_api_call(
        connection,
        run_id=run_id,
        response=response,
        date_from=trade_date,
        date_to=trade_date,
    )
    if not response.success:
        finish_task_run(
            connection,
            run_id=run_id,
            status="failed",
            rows_fetched=0,
            rows_inserted=0,
            rows_updated=0,
            rows_rejected=0,
            api_calls=1,
            error_message=response.error_message,
        )
        return BulkDailyPriceLoadResult(
            run_id=run_id,
            status="failed",
            exchange=normalized_exchange,
            trade_date=trade_date,
            rows_fetched=0,
            rows_matched=0,
            rows_inserted=0,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
            unmatched_rows=0,
            error_message=response.error_message,
            status_code=response.status_code,
        )

    active_identity_resolver = identity_resolver or DatedInstrumentIdentityResolver.from_connection(
        connection,
        market=market,
        asset_types=normalized_asset_types,
        instrument_status=instrument_status,
    )

    accepted_by_asset_type: dict[str, list[dict[str, object]]] = {}
    unmatched_observations: list[dict[str, object]] = []
    rejected_rows: list[RejectedDailyPriceRow] = []
    unmatched_rows = 0
    rows_matched = 0

    for index, row in enumerate(response.payload):
        try:
            symbol = _bulk_row_symbol(row)
        except ValueError as exc:
            rejected_rows.append(
                RejectedDailyPriceRow(
                    index=index,
                    provider_symbol="",
                    reason=str(exc),
                    row=row,
                )
            )
            continue

        provider_symbol = _bulk_row_provider_symbol(symbol, exchange=normalized_exchange)
        try:
            observed_trade_date = _bulk_row_trade_date(
                row,
                fallback_trade_date=trade_date,
            )
        except ValueError as exc:
            rejected_rows.append(
                RejectedDailyPriceRow(
                    index=index,
                    provider_symbol=provider_symbol,
                    reason=str(exc),
                    row=row,
                )
            )
            continue

        resolution = active_identity_resolver.resolve(
            provider_symbol=provider_symbol,
            trade_date=observed_trade_date,
            eodhd_type=_first_present(row, "type", "Type"),
        )
        instrument_row = resolution.instrument
        if instrument_row is None:
            try:
                unmatched_observations.append(
                    _bulk_unmatched_observation_row(
                        row,
                        run_id=run_id,
                        market=market,
                        exchange=normalized_exchange,
                        symbol=symbol,
                        provider_symbol=provider_symbol,
                        fallback_trade_date=trade_date,
                        reason=_identity_resolution_reason(resolution),
                    )
                )
            except ValueError as exc:
                rejected_rows.append(
                    RejectedDailyPriceRow(
                        index=index,
                        provider_symbol=provider_symbol,
                        reason=str(exc),
                        row=row,
                    )
                )
                continue
            unmatched_rows += 1
            continue

        rows_matched += 1
        parsed_rows = parse_daily_price_rows(
            [row],
            instrument_id=instrument_row["instrument_id"],
            symbol=symbol,
            provider_symbol=provider_symbol,
            currency=instrument_row["currency"],
        )
        rejected_rows.extend(parsed_rows.rejected)
        if parsed_rows.accepted:
            asset_type = str(instrument_row["asset_type"])
            accepted_by_asset_type.setdefault(asset_type, []).extend(parsed_rows.accepted)

    rows_inserted = _upsert_daily_price_chunks(connection, accepted_by_asset_type)
    if unmatched_observations:
        connection.execute(build_bulk_unmatched_daily_price_observation_upsert(unmatched_observations))
    rows_rejected = len(rejected_rows) + unmatched_rows
    status, error_message = _bulk_daily_price_status(
        rows_inserted=rows_inserted,
        rejected_rows=len(rejected_rows),
        unmatched_rows=unmatched_rows,
    )
    finish_task_run(
        connection,
        run_id=run_id,
        status=status,
        rows_fetched=response.rows_returned,
        rows_inserted=rows_inserted,
        rows_updated=0,
        rows_rejected=rows_rejected,
        api_calls=1,
        error_message=error_message,
    )

    return BulkDailyPriceLoadResult(
        run_id=run_id,
        status=status,
        exchange=normalized_exchange,
        trade_date=trade_date,
        rows_fetched=response.rows_returned,
        rows_matched=rows_matched,
        rows_inserted=rows_inserted,
        rows_rejected=rows_rejected,
        api_calls=1,
        rejected_rows=rejected_rows,
        unmatched_rows=unmatched_rows,
        error_message=error_message,
        status_code=response.status_code,
    )


def _load_symbol_daily_prices(
    connection: Connection,
    client: EodhdClient,
    *,
    symbols: list[str],
    date_from: date,
    date_to: date,
    market: str,
    asset_types: list[str],
    include_inactive: bool,
    instrument_status: InstrumentStatus,
    job_name: str,
    target_table: str,
) -> HistoricalDailyPriceLoadResult:
    if not symbols:
        raise ValueError("symbols must not be empty")
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")

    normalized_symbols = normalize_symbols(symbols)
    run_id = create_task_run(
        connection,
        market=market,
        job_name=job_name,
        target_table=target_table,
        date_from=date_from,
        date_to=date_to,
    )
    instruments = load_active_instruments(
        connection,
        symbols=normalized_symbols,
        market=market,
        asset_types=asset_types,
        include_inactive=include_inactive,
        instrument_status=instrument_status,
    )
    found_identifiers: set[str] = set()
    for row in instruments:
        found_identifiers.add(str(row["symbol"]).upper())
        found_identifiers.add(str(row["provider_symbol"]).upper())
    missing_symbols = [symbol for symbol in normalized_symbols if symbol not in found_identifiers]

    return _load_daily_prices_for_instruments(
        connection,
        client,
        run_id=run_id,
        instruments=instruments,
        requested_count=len(normalized_symbols),
        missing_symbols=missing_symbols,
        date_from=date_from,
        date_to=date_to,
    )


def load_index_daily_prices(
    connection: Connection,
    client: EodhdClient,
    *,
    provider_symbols: list[str],
    date_from: date,
    date_to: date,
    market: str = "US",
    currency: str = "USD",
) -> HistoricalDailyPriceLoadResult:
    """Load daily EOD prices for EODHD index provider symbols.

    Input: provider symbols such as `GSPC.INDX` plus an inclusive date range.
    Output: `HistoricalDailyPriceLoadResult` with API, parse, and write counts.
    Flow: provider symbols -> index instruments -> EOD API calls -> parse -> upsert.
    """
    normalized_symbols = normalize_provider_symbols(provider_symbols)
    if not normalized_symbols:
        raise ValueError("provider_symbols must not be empty")
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")

    run_id = create_task_run(
        connection,
        market=market,
        job_name="eodhd_index_daily_price",
        target_table="index_daily_price",
        date_from=date_from,
        date_to=date_to,
    )
    connection.execute(
        build_instrument_upsert(
            index_instrument_rows(normalized_symbols, market=market, currency=currency)
        )
    )
    instruments = load_active_instruments_by_provider_symbols(
        connection,
        provider_symbols=normalized_symbols,
        market=market,
    )
    found_provider_symbols = {row["provider_symbol"] for row in instruments}
    missing_symbols = [
        provider_symbol
        for provider_symbol in normalized_symbols
        if provider_symbol not in found_provider_symbols
    ]

    return _load_daily_prices_for_instruments(
        connection,
        client,
        run_id=run_id,
        instruments=instruments,
        requested_count=len(normalized_symbols),
        missing_symbols=missing_symbols,
        date_from=date_from,
        date_to=date_to,
    )


def _load_daily_prices_for_instruments(
    connection: Connection,
    client: EodhdClient,
    *,
    run_id: int,
    instruments: list[dict[str, object]],
    requested_count: int,
    missing_symbols: list[str],
    date_from: date,
    date_to: date,
) -> HistoricalDailyPriceLoadResult:
    rows_fetched = 0
    rows_inserted = 0
    api_calls = 0
    api_failures: list[str] = []
    rejected_rows: list[RejectedDailyPriceRow] = []

    for instrument_row in instruments:
        response = client.get_historical_eod(
            instrument_row["provider_symbol"],
            date_from=date_from,
            date_to=date_to,
        )
        api_calls += 1
        record_api_call(
            connection,
            run_id=run_id,
            response=response,
            provider_symbol=instrument_row["provider_symbol"],
            date_from=date_from,
            date_to=date_to,
        )

        if not response.success:
            api_failures.append(instrument_row["provider_symbol"])
            continue

        rows_fetched += response.rows_returned
        parsed_rows = parse_daily_price_rows(
            response.payload,
            instrument_id=instrument_row["instrument_id"],
            symbol=instrument_row["symbol"],
            provider_symbol=instrument_row["provider_symbol"],
            currency=instrument_row["currency"],
        )
        rejected_rows.extend(parsed_rows.rejected)
        if parsed_rows.accepted:
            asset_type = str(instrument_row["asset_type"])
            connection.execute(build_daily_price_upsert(asset_type, parsed_rows.accepted))
            rows_inserted += len(parsed_rows.accepted)

    rows_rejected = len(rejected_rows) + len(missing_symbols)
    status, error_message = historical_price_status(
        requested=requested_count,
        loaded=len(instruments) - len(api_failures),
        missing_symbols=missing_symbols,
        api_failures=api_failures,
        rejected_rows=len(rejected_rows),
    )
    finish_task_run(
        connection,
        run_id=run_id,
        status=status,
        rows_fetched=rows_fetched,
        rows_inserted=rows_inserted,
        rows_updated=0,
        rows_rejected=rows_rejected,
        api_calls=api_calls,
        error_message=error_message,
    )

    return HistoricalDailyPriceLoadResult(
        run_id=run_id,
        status=status,
        symbols_requested=requested_count,
        symbols_loaded=len(instruments) - len(api_failures),
        rows_fetched=rows_fetched,
        rows_inserted=rows_inserted,
        rows_rejected=rows_rejected,
        api_calls=api_calls,
        rejected_rows=rejected_rows,
        error_message=error_message,
    )


def load_historical_daily_price_unit(
    connection: Connection,
    client: EodhdClient,
    *,
    run_id: int,
    instrument_row: dict[str, object],
    date_from: date,
    date_to: date,
) -> HistoricalDailyPriceUnitResult:
    """Load one instrument without creating or finalizing its parent task run.

    Input: committed parent run id, one resolved instrument, and inclusive dates.
    Output: one unit result with API, parse, and write counts.
    Flow: provider symbol -> EODHD EOD -> API audit -> validation -> split-table upsert.
    """
    provider_symbol = str(instrument_row["provider_symbol"])
    response = client.get_historical_eod(
        provider_symbol,
        date_from=date_from,
        date_to=date_to,
    )
    record_api_call(
        connection,
        run_id=run_id,
        response=response,
        provider_symbol=provider_symbol,
        date_from=date_from,
        date_to=date_to,
    )
    if not response.success:
        return HistoricalDailyPriceUnitResult(
            provider_symbol=provider_symbol,
            status="failed",
            status_code=response.status_code,
            rows_fetched=0,
            rows_inserted=0,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
            error_message=response.error_message,
        )

    parsed_rows = parse_daily_price_rows(
        response.payload,
        instrument_id=instrument_row["instrument_id"],
        symbol=instrument_row["symbol"],
        provider_symbol=provider_symbol,
        currency=instrument_row["currency"],
    )
    rows_inserted = 0
    if parsed_rows.accepted:
        asset_type = str(instrument_row["asset_type"])
        connection.execute(build_daily_price_upsert(asset_type, parsed_rows.accepted))
        rows_inserted = len(parsed_rows.accepted)

    rows_rejected = len(parsed_rows.rejected)
    return HistoricalDailyPriceUnitResult(
        provider_symbol=provider_symbol,
        status="partial_failed" if rows_rejected else "success",
        status_code=response.status_code,
        rows_fetched=response.rows_returned,
        rows_inserted=rows_inserted,
        rows_rejected=rows_rejected,
        api_calls=1,
        rejected_rows=parsed_rows.rejected,
        error_message=(
            f"{rows_rejected} invalid EODHD price row(s) rejected"
            if rows_rejected
            else None
        ),
    )


def _bulk_row_symbol(row: dict[str, object]) -> str:
    """Return the ticker-like symbol from one EODHD bulk row."""
    value = row.get("code") or row.get("Code") or row.get("symbol") or row.get("Symbol")
    if value in (None, ""):
        raise ValueError("missing required EODHD bulk field: code")
    return str(value).strip().upper()


def _bulk_row_provider_symbol(symbol: str, *, exchange: str) -> str:
    """Build a provider symbol candidate from a bulk row symbol."""
    if "." in symbol:
        return symbol
    return f"{symbol}.{exchange.strip().upper()}"


def _bulk_unmatched_observation_row(
    row: dict[str, object],
    *,
    run_id: int,
    market: str,
    exchange: str,
    symbol: str,
    provider_symbol: str,
    fallback_trade_date: date | None,
    reason: str,
) -> dict[str, object]:
    """Build one raw unmatched observation row for later classification."""
    observed_at = now_utc()
    return {
        "run_id": run_id,
        "market": market,
        "exchange": exchange,
        "provider_symbol": provider_symbol,
        "symbol": symbol,
        "trade_date": _bulk_row_trade_date(row, fallback_trade_date=fallback_trade_date),
        "name": _optional_str(row, "name", "Name"),
        "eodhd_type": _optional_str(row, "type", "Type"),
        "open": _optional_decimal(row, "open", "Open"),
        "high": _optional_decimal(row, "high", "High"),
        "low": _optional_decimal(row, "low", "Low"),
        "close": _optional_decimal(row, "close", "Close"),
        "adjusted_close": _optional_decimal(row, "adjusted_close", "adjustedClose", "Adjusted_close"),
        "volume": _optional_int(row, "volume", "Volume"),
        "currency": _optional_str(row, "currency", "Currency"),
        "raw_payload": json.dumps(row, sort_keys=True, default=str),
        "classification_status": "unresolved",
        "classified_asset_type": None,
        "matched_instrument_id": None,
        "reason": reason,
        "source": "EODHD",
        "first_seen_at": observed_at,
        "last_seen_at": observed_at,
    }


def _identity_resolution_reason(resolution: InstrumentIdentityResolution) -> str:
    """Format an unresolved identity reason with deterministic candidate ids."""
    reason = resolution.reason or "unresolved_instrument_identity"
    candidate_ids = resolution.candidate_instrument_ids
    if not candidate_ids:
        return str(reason)
    joined = ",".join(str(instrument_id) for instrument_id in candidate_ids)
    return f"{reason};candidate_instrument_ids={joined}"


def _bulk_row_trade_date(
    row: dict[str, object],
    *,
    fallback_trade_date: date | None,
) -> date:
    value = row.get("date") or row.get("Date")
    if value in (None, ""):
        if fallback_trade_date is not None:
            return fallback_trade_date
        raise ValueError("missing required EODHD bulk field: date")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("invalid date EODHD bulk field: date") from exc


def _optional_str(row: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _optional_decimal(row: dict[str, object], *keys: str) -> Decimal | None:
    value = _first_present(row, *keys)
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal EODHD bulk field: {keys[0]}") from exc


def _optional_int(row: dict[str, object], *keys: str) -> int | None:
    value = _first_present(row, *keys)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer EODHD bulk field: {keys[0]}") from exc


def _first_present(row: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _upsert_daily_price_chunks(
    connection: Connection,
    accepted_by_asset_type: dict[str, list[dict[str, object]]],
) -> int:
    """Write accepted rows to split daily price tables in bounded chunks."""
    rows_inserted = 0
    for asset_type, rows in accepted_by_asset_type.items():
        for start in range(0, len(rows), BULK_DAILY_UPSERT_CHUNK_SIZE):
            chunk = rows[start:start + BULK_DAILY_UPSERT_CHUNK_SIZE]
            connection.execute(build_daily_price_upsert(asset_type, chunk))
            rows_inserted += len(chunk)
    return rows_inserted


def _bulk_daily_price_status(
    *,
    rows_inserted: int,
    rejected_rows: int,
    unmatched_rows: int,
) -> tuple[str, str | None]:
    """Derive bulk daily task status and compact error message."""
    problems: list[str] = []
    if unmatched_rows:
        problems.append(f"{unmatched_rows} EODHD bulk row(s) had unresolved instrument identity")
    if rejected_rows:
        problems.append(f"{rejected_rows} invalid EODHD bulk price row(s) rejected")

    if not problems:
        return "success", None
    if rows_inserted == 0:
        return "failed", "; ".join(problems)
    return "partial_failed", "; ".join(problems)
