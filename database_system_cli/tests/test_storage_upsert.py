from datetime import date
from decimal import Decimal

from sqlalchemy.dialects import mysql

from fdp.storage.upsert import (
    build_bulk_unmatched_daily_price_observation_upsert,
    build_crypto_daily_price_upsert,
    build_etf_daily_price_upsert,
    build_forex_daily_price_upsert,
    build_fund_daily_price_upsert,
    build_identifier_history_upsert,
    build_identifier_mapping_unmatched_upsert,
    build_identity_resolution_audit_upsert,
    build_index_daily_price_upsert,
    build_instrument_upsert,
    build_instrument_lifecycle_event_upsert,
    build_market_calendar_upsert,
    build_stock_daily_price_upsert,
)


def test_instrument_upsert_uses_mysql_duplicate_key_update() -> None:
    statement = build_instrument_upsert(
        {
            "market": "US",
            "symbol": "AAPL",
            "provider": "EODHD",
            "provider_symbol": "AAPL.US",
            "name": "Apple Inc.",
            "exchange": "NASDAQ",
            "asset_type": "stock",
            "currency": "USD",
            "is_active": True,
            "listed_date": date(1980, 12, 12),
            "delisted_date": None,
        }
    )

    sql = str(statement.compile(dialect=mysql.dialect()))
    update_clause = sql.split("ON DUPLICATE KEY UPDATE", maxsplit=1)[1]

    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "provider_symbol = VALUES(provider_symbol)" not in update_clause
    assert "updated_at = CURRENT_TIMESTAMP" in update_clause


def test_asset_daily_price_upserts_target_split_tables() -> None:
    row = {
        "instrument_id": 1,
        "symbol": "AAPL",
        "provider_symbol": "AAPL.US",
        "trade_date": date(2024, 1, 2),
        "open": Decimal("100.00"),
        "high": Decimal("101.00"),
        "low": Decimal("99.00"),
        "close": Decimal("100.50"),
        "adjusted_close": Decimal("100.45"),
        "volume": 1_000_000,
        "currency": "USD",
        "source": "EODHD",
    }

    builders_and_tables = [
        (build_stock_daily_price_upsert, "stock_daily_price"),
        (build_etf_daily_price_upsert, "etf_daily_price"),
        (build_fund_daily_price_upsert, "fund_daily_price"),
        (build_index_daily_price_upsert, "index_daily_price"),
        (build_forex_daily_price_upsert, "forex_daily_price"),
        (build_crypto_daily_price_upsert, "crypto_daily_price"),
    ]

    for builder, table_name in builders_and_tables:
        sql = str(builder(row).compile(dialect=mysql.dialect()))

        assert f"INSERT INTO us_share.{table_name}" in sql
        assert "ON DUPLICATE KEY UPDATE" in sql
        assert "adjusted_close = VALUES(adjusted_close)" in sql


def test_identifier_history_upsert_updates_valid_to() -> None:
    statement = build_identifier_history_upsert(
        {
            "instrument_id": 1,
            "id_type": "provider_symbol",
            "id_value": "FB.US",
            "valid_from": None,
            "valid_to": date(2022, 6, 8),
            "source": "EODHD_SYMBOL_CHANGE_HISTORY",
        }
    )

    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "valid_to = VALUES(valid_to)" in sql
    assert "updated_at = CURRENT_TIMESTAMP" in sql


def test_identifier_mapping_unmatched_upsert_keeps_first_seen_identity() -> None:
    statement = build_identifier_mapping_unmatched_upsert(
        {
            "last_run_id": 1,
            "market": "US",
            "provider_symbol": "UNKNOWN.US",
            "isin": "US0378331005",
            "raw_payload": "{}",
            "mapping_fingerprint": "f" * 64,
            "reason": "missing_instrument",
            "resolution_status": "pending",
            "source": "EODHD_ID_MAPPING",
        }
    )

    sql = str(statement.compile(dialect=mysql.dialect()))
    update_clause = sql.split("ON DUPLICATE KEY UPDATE", maxsplit=1)[1]

    assert "INSERT INTO `system`.identifier_mapping_unmatched_observation" in sql
    assert "last_run_id = VALUES(last_run_id)" in update_clause
    assert "reason = VALUES(reason)" in update_clause
    assert "last_seen_at = CURRENT_TIMESTAMP" in update_clause
    assert "last_seen_at = VALUES(last_seen_at)" not in update_clause
    assert "first_seen_at" not in update_clause
    assert "mapping_fingerprint" not in update_clause


def test_identity_resolution_audit_upsert_widens_observed_interval() -> None:
    statement = build_identity_resolution_audit_upsert(
        {
            "instrument_id": 1,
            "provider_symbol": "FB.US",
            "market": "US",
            "source": "EODHD",
            "match_method": "identifier_history",
            "confidence": "high",
            "evidence_type": "dated_provider_symbol_history",
            "resolver_version": "v1",
            "observed_from": date(2022, 1, 3),
            "observed_to": date(2022, 1, 3),
            "first_run_id": 71,
            "last_run_id": 71,
            "reason": "dated identifier history winner",
            "supersedes_audit_id": 70,
        }
    )

    sql = str(statement.compile(dialect=mysql.dialect()))
    update_clause = sql.split("ON DUPLICATE KEY UPDATE", maxsplit=1)[1]

    assert "INSERT INTO `system`.instrument_identity_resolution_audit" in sql
    assert "observed_from = least(" in update_clause
    assert "observed_to = greatest(" in update_clause
    assert "last_run_id = VALUES(last_run_id)" in update_clause
    assert "supersedes_audit_id = coalesce(" in update_clause
    assert "first_run_id" not in update_clause


def test_lifecycle_event_upsert_targets_source_event_key() -> None:
    statement = build_instrument_lifecycle_event_upsert(
        {
            "instrument_id": 1,
            "event_type": "delisted",
            "event_date": date(2024, 5, 20),
            "symbol": "OLD",
            "provider_symbol": "OLD.US",
            "source": "EODHD_DELISTED_EXCHANGE_SYMBOLS",
            "event_key": "delisted:OLD.US:2024-05-20",
            "details": "asset_type=stock;exchange=NYSE;currency=USD",
        }
    )

    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "event_type = VALUES(event_type)" in sql
    assert "provider_symbol = VALUES(provider_symbol)" in sql
    assert "updated_at = CURRENT_TIMESTAMP" in sql


def test_market_calendar_upsert_updates_calendar_flags() -> None:
    statement = build_market_calendar_upsert(
        {
            "calendar_date": date(2026, 11, 27),
            "is_trading_day": True,
            "source": "EODHD_EXCHANGE_DETAILS",
        }
    )

    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "is_trading_day = VALUES(is_trading_day)" in sql
    assert "source = VALUES(source)" in sql


def test_bulk_unmatched_upsert_preserves_classification_state() -> None:
    statement = build_bulk_unmatched_daily_price_observation_upsert(
        {
            "run_id": 1,
            "market": "US",
            "exchange": "US",
            "provider_symbol": "OLD.US",
            "symbol": "OLD",
            "trade_date": date(2024, 1, 2),
            "raw_payload": "{}",
            "classification_status": "unresolved",
            "source": "EODHD",
        }
    )

    sql = str(statement.compile(dialect=mysql.dialect()))
    update_clause = sql.split("ON DUPLICATE KEY UPDATE", maxsplit=1)[1]

    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "raw_payload = VALUES(raw_payload)" in update_clause
    assert "classification_status = VALUES(classification_status)" not in update_clause
    assert "matched_instrument_id = VALUES(matched_instrument_id)" not in update_clause
