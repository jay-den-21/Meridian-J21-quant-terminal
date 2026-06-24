"""Shared result models and constants for EODHD ingest workflows."""

from dataclasses import dataclass
from datetime import date

from fdp.sources.eodhd.instruments import RejectedInstrumentRow
from fdp.sources.eodhd.prices import RejectedDailyPriceRow

SYMBOL_CHANGE_HISTORY_START = date(2022, 7, 22)
SYMBOL_CHANGE_HISTORY_SOURCE = "EODHD_SYMBOL_CHANGE_HISTORY"
DEFAULT_INDEX_PROVIDER_SYMBOLS = ("GSPC.INDX", "DJI.INDX", "IXIC.INDX", "NDX.INDX")
DEFAULT_INDEX_NAMES = {
    "GSPC.INDX": "S&P 500 Index",
    "DJI.INDX": "Dow Jones Industrial Average",
    "IXIC.INDX": "NASDAQ Composite Index",
    "NDX.INDX": "NASDAQ 100 Index",
}


@dataclass(frozen=True)
class InstrumentLoadResult:
    """Summary returned by `load_exchange_symbols`.

    Input: task/API/write outcomes produced during one instrument ingest run.
    Output: compact result for CLI output and tests.
    Flow: task run -> API calls -> parser/upsert counts -> load result.
    """

    run_id: int
    status: str
    rows_fetched: int
    rows_accepted: int
    rows_rejected: int
    api_calls: int
    rejected_rows: list[RejectedInstrumentRow]
    error_message: str | None = None


@dataclass(frozen=True)
class HistoricalDailyPriceLoadResult:
    """Summary returned by historical daily price loaders.

    Input: requested symbols, EODHD API outcomes, parser counts, and write counts.
    Output: compact result for CLI output and tests.
    Flow: task run -> instrument lookup -> EOD API calls -> parse -> daily price upsert.
    """

    run_id: int
    status: str
    symbols_requested: int
    symbols_loaded: int
    rows_fetched: int
    rows_inserted: int
    rows_rejected: int
    api_calls: int
    rejected_rows: list[RejectedDailyPriceRow]
    error_message: str | None = None


@dataclass(frozen=True)
class MarketCalendarLoadResult:
    """Summary returned by `load_market_calendar`.

    Input: EODHD exchange-details outcomes and generated calendar rows.
    Output: compact result for CLI output and tests.
    Flow: task run -> exchange-details API -> calendar rows -> market_calendar upsert.
    """

    run_id: int
    status: str
    rows_fetched: int
    rows_inserted: int
    rows_rejected: int
    api_calls: int
    error_message: str | None = None
