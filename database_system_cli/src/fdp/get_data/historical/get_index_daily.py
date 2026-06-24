"""Reusable script entrypoint for historical benchmark index daily OHLCV."""

from datetime import date

from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import (
    DEFAULT_INDEX_PROVIDER_SYMBOLS,
    HistoricalDailyPriceLoadResult,
    load_index_daily_prices,
)


def get_index_daily(
    connection: Connection,
    client: EodhdClient,
    *,
    provider_symbols: list[str] | None = None,
    date_from: date,
    date_to: date,
    market: str = "US",
    currency: str = "USD",
) -> HistoricalDailyPriceLoadResult:
    """Load benchmark index daily bars.

    Input: database connection, EODHD client, index provider symbols, and date range.
    Output: index daily price load summary.
    Flow: provider symbols -> index instruments -> EODHD historical EOD -> daily price upsert.
    """
    return load_index_daily_prices(
        connection,
        client,
        provider_symbols=provider_symbols or list(DEFAULT_INDEX_PROVIDER_SYMBOLS),
        date_from=date_from,
        date_to=date_to,
        market=market,
        currency=currency,
    )
