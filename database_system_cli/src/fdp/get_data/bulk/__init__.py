"""Bulk EOD ingest jobs."""

from fdp.get_data.bulk.get_daily import BulkDailyJob
from fdp.get_data.bulk.get_daily_range import DailyRangeJob

__all__ = ["BulkDailyJob", "DailyRangeJob"]
