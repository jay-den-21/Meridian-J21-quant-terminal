"""MySQL upsert statement builders for storage-layer writes."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Table
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.sql import func
from sqlalchemy.sql.dml import Insert

from fdp.storage.tables import (
    bulk_unmatched_daily_price_observation,
    crypto_daily_price,
    etf_daily_price,
    forex_daily_price,
    fund_daily_price,
    identifier_mapping_unmatched_observation,
    index_daily_price,
    instrument,
    instrument_identifier_history,
    instrument_identity_resolution_audit,
    instrument_lifecycle_event,
    market_calendar,
    stock_daily_price,
)

Row = Mapping[str, Any]

DAILY_PRICE_UPDATE_COLUMNS = [
    "symbol",
    "provider_symbol",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "currency",
    "source",
    "source_updated_at",
    "updated_at",
]


def build_mysql_upsert(
    table: Table,
    rows: Row | Sequence[Row],
    *,
    update_columns: Sequence[str] | None = None,
) -> Insert:
    """Build a MySQL `INSERT ... ON DUPLICATE KEY UPDATE` statement.

    Input: SQLAlchemy table, one row or many rows, and optional columns to update.
    Output: MySQL insert statement that upserts on table primary/unique keys.
    Flow: rows -> INSERT values -> update column map -> ON DUPLICATE KEY UPDATE.
    """
    if not rows:
        raise ValueError("rows must not be empty")

    row_keys = set(rows.keys()) if isinstance(rows, Mapping) else set(rows[0].keys())
    if update_columns is None:
        update_columns = [
            column.name
            for column in table.columns
            if not column.primary_key and column.name in row_keys and column.name != "created_at"
        ]

    statement = insert(table).values(rows)
    update_values = {}
    for column_name in update_columns:
        if column_name in {"last_seen_at", "updated_at"} and column_name not in row_keys:
            update_values[column_name] = func.current_timestamp()
            continue
        update_values[column_name] = getattr(statement.inserted, column_name)
    return statement.on_duplicate_key_update(**update_values)


def build_instrument_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.instrument`.

    Input: parsed active instrument rows from EODHD exchange-symbol-list.
    Output: MySQL upsert that refreshes current metadata but not provider_symbol.
    Flow: instrument rows -> provider/provider_symbol unique key -> metadata update.
    """
    return build_mysql_upsert(
        instrument,
        rows,
        update_columns=[
            "market",
            "symbol",
            "name",
            "exchange",
            "asset_type",
            "currency",
            "is_active",
            "listed_date",
            "delisted_date",
            "updated_at",
        ],
    )


def build_identifier_history_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.instrument_identifier_history`.

    Input: ticker/provider-symbol history rows for one or more instruments.
    Output: MySQL upsert that only refreshes `valid_to` and `updated_at`.
    Flow: history rows -> identity unique key -> close/update validity interval.
    """
    return build_mysql_upsert(
        instrument_identifier_history,
        rows,
        update_columns=[
            "valid_to",
            "updated_at",
        ],
    )


def build_identifier_mapping_unmatched_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for unresolved EODHD ID Mapping observations.

    Input: normalized source rows keyed by source and mapping fingerprint.
    Output: MySQL upsert that refreshes current resolution evidence.
    Flow: unresolved mapping -> stable fingerprint -> pending/resolved observation.
    """
    return build_mysql_upsert(
        identifier_mapping_unmatched_observation,
        rows,
        update_columns=[
            "last_run_id",
            "market",
            "provider_symbol",
            "isin",
            "figi",
            "lei",
            "cusip",
            "cik",
            "raw_payload",
            "reason",
            "candidate_instrument_ids",
            "resolution_status",
            "resolved_instrument_id",
            "last_seen_at",
            "resolved_at",
            "updated_at",
        ],
    )


def build_identity_resolution_audit_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Aggregate repeated Bulk identity decisions into one observed interval.

    Input: one or more identity decisions with an observed date and workflow run.
    Output: MySQL upsert that widens the interval while preserving first evidence.
    Flow: strict resolver decision -> decision unique key -> interval/audit refresh.
    """
    if not rows:
        raise ValueError("rows must not be empty")
    statement = insert(instrument_identity_resolution_audit).values(rows)
    return statement.on_duplicate_key_update(
        observed_from=func.least(
            instrument_identity_resolution_audit.c.observed_from,
            statement.inserted.observed_from,
        ),
        observed_to=func.greatest(
            instrument_identity_resolution_audit.c.observed_to,
            statement.inserted.observed_to,
        ),
        last_run_id=statement.inserted.last_run_id,
        reason=statement.inserted.reason,
        supersedes_audit_id=func.coalesce(
            instrument_identity_resolution_audit.c.supersedes_audit_id,
            statement.inserted.supersedes_audit_id,
        ),
        updated_at=func.current_timestamp(),
    )


def build_instrument_lifecycle_event_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.instrument_lifecycle_event`.

    Input: instrument lifecycle event rows keyed by source/event key.
    Output: MySQL upsert that refreshes event details and timestamps.
    Flow: lifecycle rows -> unique(source, event_key) -> event metadata update.
    """
    return build_mysql_upsert(
        instrument_lifecycle_event,
        rows,
        update_columns=[
            "instrument_id",
            "event_type",
            "event_date",
            "symbol",
            "provider_symbol",
            "details",
            "updated_at",
        ],
    )


def build_stock_daily_price_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.stock_daily_price`.

    Input: stock daily OHLCV rows keyed by `instrument_id` and `trade_date`.
    Output: MySQL upsert that refreshes prices and display symbols.
    Flow: stock rows -> unique(instrument_id, trade_date) -> OHLCV update.
    """
    return build_mysql_upsert(
        stock_daily_price,
        rows,
        update_columns=DAILY_PRICE_UPDATE_COLUMNS,
    )


def build_etf_daily_price_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.etf_daily_price`.

    Input: ETF daily OHLCV rows keyed by `instrument_id` and `trade_date`.
    Output: MySQL upsert that refreshes prices and display symbols.
    Flow: ETF rows -> unique(instrument_id, trade_date) -> OHLCV update.
    """
    return build_mysql_upsert(
        etf_daily_price,
        rows,
        update_columns=DAILY_PRICE_UPDATE_COLUMNS,
    )


def build_fund_daily_price_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.fund_daily_price`."""
    return build_mysql_upsert(
        fund_daily_price,
        rows,
        update_columns=DAILY_PRICE_UPDATE_COLUMNS,
    )


def build_index_daily_price_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.index_daily_price`.

    Input: index daily OHLCV rows keyed by `instrument_id` and `trade_date`.
    Output: MySQL upsert that refreshes prices and display symbols.
    Flow: index rows -> unique(instrument_id, trade_date) -> OHLCV update.
    """
    return build_mysql_upsert(
        index_daily_price,
        rows,
        update_columns=DAILY_PRICE_UPDATE_COLUMNS,
    )


def build_forex_daily_price_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.forex_daily_price`."""
    return build_mysql_upsert(
        forex_daily_price,
        rows,
        update_columns=DAILY_PRICE_UPDATE_COLUMNS,
    )


def build_crypto_daily_price_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.crypto_daily_price`."""
    return build_mysql_upsert(
        crypto_daily_price,
        rows,
        update_columns=DAILY_PRICE_UPDATE_COLUMNS,
    )


DAILY_PRICE_UPSERT_BUILDERS = {
    "stock": build_stock_daily_price_upsert,
    "etf": build_etf_daily_price_upsert,
    "fund": build_fund_daily_price_upsert,
    "index": build_index_daily_price_upsert,
    "forex": build_forex_daily_price_upsert,
    "crypto": build_crypto_daily_price_upsert,
}


def build_daily_price_upsert(asset_type: str, rows: Row | Sequence[Row]) -> Insert:
    """Build a daily-price upsert for one canonical asset type."""
    try:
        builder = DAILY_PRICE_UPSERT_BUILDERS[asset_type]
    except KeyError as exc:
        supported = ", ".join(DAILY_PRICE_UPSERT_BUILDERS)
        raise ValueError(f"unsupported daily-price asset type {asset_type!r}: {supported}") from exc
    return builder(rows)


def build_market_calendar_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `us_share.market_calendar`.

    Input: generated daily calendar rows keyed by `calendar_date`.
    Output: MySQL upsert that refreshes trading-day flags and source metadata.
    Flow: calendar rows -> unique(calendar_date) -> flag/source update.
    """
    return build_mysql_upsert(
        market_calendar,
        rows,
        update_columns=[
            "is_trading_day",
            "source",
            "updated_at",
        ],
    )


def build_bulk_unmatched_daily_price_observation_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Build the upsert for `system.bulk_unmatched_daily_price_observation`.

    Input: unmatched EODHD Bulk EOD rows keyed by source/provider_symbol/trade_date.
    Output: MySQL upsert that refreshes raw observation fields without resetting classification.
    Flow: unmatched rows -> raw staging table -> later classifier/route workflow.
    """
    return build_mysql_upsert(
        bulk_unmatched_daily_price_observation,
        rows,
        update_columns=[
            "run_id",
            "market",
            "exchange",
            "symbol",
            "name",
            "eodhd_type",
            "open",
            "high",
            "low",
            "close",
            "adjusted_close",
            "volume",
            "currency",
            "raw_payload",
            "last_seen_at",
            "updated_at",
        ],
    )


def build_classified_bulk_observation_upsert(rows: Row | Sequence[Row]) -> Insert:
    """Upsert deterministic duplicate/ambiguity classifications from the ingest batch."""
    return build_mysql_upsert(
        bulk_unmatched_daily_price_observation,
        rows,
        update_columns=[
            "run_id",
            "market",
            "exchange",
            "symbol",
            "name",
            "eodhd_type",
            "open",
            "high",
            "low",
            "close",
            "adjusted_close",
            "volume",
            "currency",
            "raw_payload",
            "classification_status",
            "classified_asset_type",
            "matched_instrument_id",
            "reason",
            "last_seen_at",
            "updated_at",
        ],
    )
