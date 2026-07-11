"""Backward-compatible imports for EODHD ingest workflows.

New code should import from `fdp.sources.eodhd.ingest.*` modules. This facade keeps
older CLI/tests/imports stable while the v0.1 package layout settles.
"""

from fdp.sources.eodhd.ingest import (
    DEFAULT_INDEX_NAMES,
    DEFAULT_INDEX_PROVIDER_SYMBOLS,
    SYMBOL_CHANGE_HISTORY_SOURCE,
    SYMBOL_CHANGE_HISTORY_START,
    BulkDailyPriceLoadResult,
    DelistedInstrumentLoadResult,
    HistoricalDailyPriceLoadResult,
    InstrumentLoadResult,
    MarketCalendarLoadResult,
    load_bulk_daily_prices,
    load_daily_prices_for_instrument_ids,
    load_delisted_instruments,
    load_exchange_symbols,
    load_etf_daily_prices,
    load_fund_daily_prices,
    load_historical_daily_prices,
    load_index_daily_prices,
    load_market_calendar,
    load_stock_daily_prices,
    reconcile_symbol_changes,
)

__all__ = [
    "DEFAULT_INDEX_NAMES",
    "DEFAULT_INDEX_PROVIDER_SYMBOLS",
    "SYMBOL_CHANGE_HISTORY_SOURCE",
    "SYMBOL_CHANGE_HISTORY_START",
    "BulkDailyPriceLoadResult",
    "DelistedInstrumentLoadResult",
    "HistoricalDailyPriceLoadResult",
    "InstrumentLoadResult",
    "MarketCalendarLoadResult",
    "load_bulk_daily_prices",
    "load_daily_prices_for_instrument_ids",
    "load_delisted_instruments",
    "load_exchange_symbols",
    "load_etf_daily_prices",
    "load_fund_daily_prices",
    "load_historical_daily_prices",
    "load_index_daily_prices",
    "load_market_calendar",
    "load_stock_daily_prices",
    "reconcile_symbol_changes",
]
