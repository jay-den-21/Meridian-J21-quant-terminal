"""Historical data acquisition jobs."""

from fdp.get_data.historical.base import HistoricalDailyJob
from fdp.get_data.historical.get_etf_daily import EtfDailyJob
from fdp.get_data.historical.get_index_daily import IndexDailyJob
from fdp.get_data.historical.get_market_calendar import MarketCalendarJob
from fdp.get_data.historical.get_stk_daily import StockDailyJob

__all__ = [
    "EtfDailyJob",
    "HistoricalDailyJob",
    "IndexDailyJob",
    "MarketCalendarJob",
    "StockDailyJob",
]
