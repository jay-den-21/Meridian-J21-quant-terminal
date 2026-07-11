"""Reusable data acquisition jobs shared by CLI, menu, and Python callers."""

from fdp.get_data.bulk import BulkDailyJob, DailyRangeJob
from fdp.get_data.contracts import JobPreflight, JobResult, ProgressEvent, ProgressReporter
from fdp.get_data.historical import (
    EtfDailyJob,
    FundDailyJob,
    HistoricalDailyJob,
    IndexDailyJob,
    MarketCalendarJob,
    StockDailyJob,
)
from fdp.get_data.instruments import ActiveInstrumentsJob, DelistedInstrumentsJob
from fdp.get_data.reconcile import BulkUnmatchedReconcileJob
from fdp.get_data.runtime import JobRuntime

__all__ = [
    "ActiveInstrumentsJob",
    "BulkDailyJob",
    "BulkUnmatchedReconcileJob",
    "DailyRangeJob",
    "DelistedInstrumentsJob",
    "EtfDailyJob",
    "FundDailyJob",
    "HistoricalDailyJob",
    "IndexDailyJob",
    "JobPreflight",
    "JobResult",
    "JobRuntime",
    "MarketCalendarJob",
    "ProgressEvent",
    "ProgressReporter",
    "StockDailyJob",
]
