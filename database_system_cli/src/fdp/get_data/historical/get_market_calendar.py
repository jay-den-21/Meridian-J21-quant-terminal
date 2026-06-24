"""Reusable script entrypoint for historical US market calendar rows."""

from datetime import date

from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import MarketCalendarLoadResult, load_market_calendar


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
