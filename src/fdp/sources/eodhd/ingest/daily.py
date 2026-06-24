"""EODHD historical daily price ingest workflows."""

from datetime import date

from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest.common import (
    create_task_run,
    finish_task_run,
    historical_price_status,
    index_instrument_rows,
    load_active_instruments,
    load_active_instruments_by_provider_symbols,
    normalize_provider_symbols,
    normalize_symbols,
    record_api_call,
)
from fdp.sources.eodhd.ingest.models import HistoricalDailyPriceLoadResult
from fdp.sources.eodhd.prices import RejectedDailyPriceRow, parse_daily_price_rows
from fdp.storage.upsert import (
    build_etf_daily_price_upsert,
    build_index_daily_price_upsert,
    build_instrument_upsert,
    build_stock_daily_price_upsert,
)

PRICE_UPSERT_BUILDERS = {
    "stock": build_stock_daily_price_upsert,
    "etf": build_etf_daily_price_upsert,
    "index": build_index_daily_price_upsert,
}


def load_historical_daily_prices(
    connection: Connection,
    client: EodhdClient,
    *,
    symbols: list[str],
    date_from: date,
    date_to: date,
    market: str = "US",
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
        asset_types=["stock", "etf"],
        job_name="eodhd_historical_daily_price",
        target_table="stock_daily_price,etf_daily_price",
    )


def load_stock_daily_prices(
    connection: Connection,
    client: EodhdClient,
    *,
    symbols: list[str],
    date_from: date,
    date_to: date,
    market: str = "US",
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
        job_name="eodhd_etf_daily_price",
        target_table="etf_daily_price",
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
    )
    found_symbols = {row["symbol"] for row in instruments}
    missing_symbols = [symbol for symbol in normalized_symbols if symbol not in found_symbols]

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
            connection.execute(PRICE_UPSERT_BUILDERS[asset_type](parsed_rows.accepted))
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
