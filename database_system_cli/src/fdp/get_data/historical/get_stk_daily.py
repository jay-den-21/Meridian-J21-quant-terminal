"""Reusable script entrypoint for historical US stock daily OHLCV."""

from datetime import date

from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.get_data.historical.base import HistoricalDailyJob
from fdp.sources.eodhd.ingest import HistoricalDailyPriceLoadResult, load_stock_daily_prices
from fdp.sources.eodhd.ingest.common import InstrumentStatus

DEFAULT_SYMBOLS: tuple[str, ...] = ()
DEFAULT_DATE_FROM: date | None = None
DEFAULT_DATE_TO: date | None = None
DEFAULT_INSTRUMENT_STATUS: InstrumentStatus = "active"


class StockDailyJob(HistoricalDailyJob):
    """Human-maintainable stock daily job with CLI/menu-overridable defaults."""

    def __init__(self) -> None:
        super().__init__(
            asset_types=("stock",),
            default_symbols=DEFAULT_SYMBOLS,
            default_date_from=DEFAULT_DATE_FROM,
            default_date_to=DEFAULT_DATE_TO,
            default_instrument_status=DEFAULT_INSTRUMENT_STATUS,
            job_module="fdp.get_data.historical.get_stk_daily",
        )


def get_stk_daily(
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
        instrument_status=instrument_status,
    )
