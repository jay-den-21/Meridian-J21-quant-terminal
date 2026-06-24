"""Reusable script entrypoint for historical US ETF daily OHLCV."""

from datetime import date

from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import HistoricalDailyPriceLoadResult, load_etf_daily_prices


def get_etf_daily(
    connection: Connection,
    client: EodhdClient,
    *,
    symbols: list[str],
    date_from: date,
    date_to: date,
    market: str = "US",
) -> HistoricalDailyPriceLoadResult:
    """Load ETF daily bars through the historical daily price ingest service.

    Input: database connection, EODHD client, ETF symbols, and date range.
    Output: historical daily price load summary.
    Flow: symbols -> instrument lookup -> EODHD historical EOD -> daily price upsert.
    """
    return load_etf_daily_prices(
        connection,
        client,
        symbols=symbols,
        date_from=date_from,
        date_to=date_to,
        market=market,
    )
