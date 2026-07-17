"""Explicit registry of human-operable ingest jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fdp.get_data.bulk import BulkDailyJob, DailyRangeJob
from fdp.get_data.corporate_actions import CorporateActionsHistoryJob
from fdp.get_data.historical import (
    EtfDailyJob,
    FundDailyJob,
    IndexDailyJob,
    MarketCalendarJob,
    StockDailyJob,
)
from fdp.get_data.instruments import ActiveInstrumentsJob, DelistedInstrumentsJob
from fdp.get_data.reconcile import BulkUnmatchedReconcileJob
from fdp.get_data.reference import IdentifierMappingJob


@dataclass(frozen=True)
class IngestJobDefinition:
    key: str
    category: str
    label_key: str
    module: str
    factory: Callable[[], Any]


INGEST_JOB_DEFINITIONS = (
    IngestJobDefinition(
        "instruments",
        "instrument_master",
        "job_instruments",
        "fdp.get_data.instruments.get_instruments",
        ActiveInstrumentsJob,
    ),
    IngestJobDefinition(
        "delisted_instruments",
        "instrument_master",
        "job_delisted",
        "fdp.get_data.instruments.get_delisted_instruments",
        DelistedInstrumentsJob,
    ),
    IngestJobDefinition(
        "stock_daily",
        "historical_eod",
        "job_stock_daily",
        "fdp.get_data.historical.get_stk_daily",
        StockDailyJob,
    ),
    IngestJobDefinition(
        "etf_daily",
        "historical_eod",
        "job_etf_daily",
        "fdp.get_data.historical.get_etf_daily",
        EtfDailyJob,
    ),
    IngestJobDefinition(
        "fund_daily",
        "historical_eod",
        "job_fund_daily",
        "fdp.get_data.historical.get_fund_daily",
        FundDailyJob,
    ),
    IngestJobDefinition(
        "index_daily",
        "historical_eod",
        "job_index_daily",
        "fdp.get_data.historical.get_index_daily",
        IndexDailyJob,
    ),
    IngestJobDefinition(
        "bulk_daily",
        "bulk_eod",
        "job_bulk_daily",
        "fdp.get_data.bulk.get_daily",
        BulkDailyJob,
    ),
    IngestJobDefinition(
        "daily_range",
        "bulk_eod",
        "job_daily_range",
        "fdp.get_data.bulk.get_daily_range",
        DailyRangeJob,
    ),
    IngestJobDefinition(
        "corporate_actions",
        "corporate_actions",
        "job_corporate_actions",
        "fdp.get_data.corporate_actions.get_history",
        CorporateActionsHistoryJob,
    ),
    IngestJobDefinition(
        "market_calendar",
        "reference",
        "job_calendar",
        "fdp.get_data.historical.get_market_calendar",
        MarketCalendarJob,
    ),
    IngestJobDefinition(
        "id_mappings",
        "reference",
        "job_id_mappings",
        "fdp.get_data.reference.get_id_mappings",
        IdentifierMappingJob,
    ),
    IngestJobDefinition(
        "bulk_unmatched",
        "reconcile",
        "job_bulk_unmatched",
        "fdp.get_data.reconcile.bulk_unmatched",
        BulkUnmatchedReconcileJob,
    ),
)


def get_ingest_job_definition(key: str) -> IngestJobDefinition:
    for definition in INGEST_JOB_DEFINITIONS:
        if definition.key == key:
            return definition
    raise KeyError(f"unknown ingest job: {key}")
