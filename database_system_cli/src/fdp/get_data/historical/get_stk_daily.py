"""Reusable script entrypoint for historical US stock daily OHLCV."""

from datetime import date

from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import HistoricalDailyPriceLoadResult, load_stock_daily_prices


def get_stk_daily(
    connection: Connection,
    client: EodhdClient,
    *,
    symbols: list[str],
    date_from: date,
    date_to: date,
    market: str = "US",
    include_inactive: bool = False,
) -> HistoricalDailyPriceLoadResult:
    """Load stock daily bars through the historical daily price ingest service.

    Input: database connection, EODHD client, stock symbols, and date range.
    Output: historical daily price load summary.
    Flow: symbols -> instrument lookup -> EODHD historical EOD -> daily price upsert.
    """
    return load_stock_daily_prices(
        connection,
        client,
        symbols=symbols,
        date_from=date_from,
        date_to=date_to,
        market=market,
        include_inactive=include_inactive,
    )
