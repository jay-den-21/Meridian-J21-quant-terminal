"""drop legacy us_share snapshot tables

Revision ID: 0011_drop_us_share_snapshots
Revises: 0010_app_log_snapshots
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa


revision: str = "0011_drop_us_share_snapshots"
down_revision: str | None = "0010_app_log_snapshots"
branch_labels = None
depends_on = None


APP_LOG_SCHEMA = "app_log"
LEGACY_SCHEMA = "us_share"

SNAPSHOT_TABLES = (
    "instrument_search_snapshot",
    "instrument_search_result",
    "screener_snapshot",
    "screener_snapshot_member",
    "quote_snapshot",
    "live_ohlcv_snapshot",
    "websocket_event",
)


def upgrade() -> None:
    for table_name in SNAPSHOT_TABLES:
        _assert_copy_count_matches(table_name)

    for table_name in (
        "instrument_search_result",
        "screener_snapshot_member",
        "quote_snapshot",
        "live_ohlcv_snapshot",
        "websocket_event",
        "instrument_search_snapshot",
        "screener_snapshot",
    ):
        op.execute(f"DROP TABLE IF EXISTS {LEGACY_SCHEMA}.{table_name}")


def downgrade() -> None:
    _create_legacy_instrument_search_tables()
    _create_legacy_screener_tables()
    _create_legacy_quote_snapshot()
    _create_legacy_live_ohlcv_snapshot()
    _create_legacy_websocket_event()
    _copy_app_log_rows_back()


def _assert_copy_count_matches(table_name: str) -> None:
    if not _table_exists(LEGACY_SCHEMA, table_name):
        return
    if not _table_exists(APP_LOG_SCHEMA, table_name):
        raise RuntimeError(f"app_log.{table_name} is missing; refusing to drop legacy table")
    legacy_count = _table_count(LEGACY_SCHEMA, table_name)
    app_log_count = _table_count(APP_LOG_SCHEMA, table_name)
    if legacy_count != app_log_count:
        raise RuntimeError(
            f"copy count mismatch for {table_name}: "
            f"us_share={legacy_count}, app_log={app_log_count}"
        )


def _create_legacy_instrument_search_tables() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS us_share.instrument_search_snapshot (
          search_snapshot_id BIGINT NOT NULL AUTO_INCREMENT,
          query_text VARCHAR(255) NOT NULL,
          query_hash VARCHAR(64) NOT NULL,
          limit_value INT NULL,
          exchange VARCHAR(32) NULL,
          asset_type VARCHAR(32) NULL,
          bonds_only TINYINT(1) NOT NULL DEFAULT 0,
          source VARCHAR(32) NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (search_snapshot_id),
          KEY ix_search_snapshot_query_hash (query_hash)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS us_share.instrument_search_result (
          search_result_id BIGINT NOT NULL AUTO_INCREMENT,
          search_snapshot_id BIGINT NOT NULL,
          `row_number` INT NOT NULL,
          code VARCHAR(128) NOT NULL,
          exchange VARCHAR(64) NULL,
          name VARCHAR(255) NULL,
          asset_type VARCHAR(64) NULL,
          country VARCHAR(128) NULL,
          currency VARCHAR(16) NULL,
          isin VARCHAR(32) NULL,
          previous_close DECIMAL(20,6) NULL,
          previous_close_date DATE NULL,
          is_primary TINYINT(1) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (search_result_id),
          UNIQUE KEY uq_search_result_snapshot_rank (search_snapshot_id, `row_number`),
          KEY ix_search_result_code_exchange (code, exchange),
          CONSTRAINT instrument_search_result_ibfk_1
            FOREIGN KEY (search_snapshot_id)
            REFERENCES us_share.instrument_search_snapshot (search_snapshot_id)
        )
        """
    )


def _create_legacy_screener_tables() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS us_share.screener_snapshot (
          snapshot_id BIGINT NOT NULL AUTO_INCREMENT,
          snapshot_name VARCHAR(128) NULL,
          query_hash VARCHAR(64) NOT NULL,
          filters_json TEXT NULL,
          signals VARCHAR(128) NULL,
          `sort` VARCHAR(128) NULL,
          limit_value INT NOT NULL,
          offset_value INT NOT NULL,
          source VARCHAR(32) NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (snapshot_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS us_share.screener_snapshot_member (
          member_id BIGINT NOT NULL AUTO_INCREMENT,
          snapshot_id BIGINT NOT NULL,
          `row_number` INT NOT NULL,
          code VARCHAR(128) NOT NULL,
          provider_symbol VARCHAR(128) NULL,
          name VARCHAR(255) NULL,
          exchange VARCHAR(64) NULL,
          currency_symbol VARCHAR(16) NULL,
          sector VARCHAR(128) NULL,
          industry VARCHAR(255) NULL,
          market_capitalization DECIMAL(28,8) NULL,
          earnings_share DECIMAL(20,8) NULL,
          dividend_yield DECIMAL(20,8) NULL,
          pe DECIMAL(20,8) NULL,
          peg DECIMAL(20,8) NULL,
          pb DECIMAL(20,8) NULL,
          ps DECIMAL(20,8) NULL,
          revenue DECIMAL(28,8) NULL,
          ebitda DECIMAL(28,8) NULL,
          roe DECIMAL(20,8) NULL,
          roa DECIMAL(20,8) NULL,
          beta DECIMAL(20,8) NULL,
          refund_1d_p DECIMAL(20,8) NULL,
          refund_5d_p DECIMAL(20,8) NULL,
          refund_ytd_p DECIMAL(20,8) NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (member_id),
          UNIQUE KEY uq_screener_member_snapshot_rank (snapshot_id, `row_number`),
          UNIQUE KEY uq_screener_member_snapshot_code (snapshot_id, code),
          KEY ix_screener_member_code (code),
          CONSTRAINT screener_snapshot_member_ibfk_1
            FOREIGN KEY (snapshot_id)
            REFERENCES us_share.screener_snapshot (snapshot_id)
        )
        """
    )


def _create_legacy_quote_snapshot() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS us_share.quote_snapshot (
          quote_snapshot_id BIGINT NOT NULL AUTO_INCREMENT,
          instrument_id BIGINT NOT NULL,
          symbol VARCHAR(64) NOT NULL,
          provider_symbol VARCHAR(128) NOT NULL,
          snapshot_timestamp DATETIME NOT NULL,
          exchange VARCHAR(64) NULL,
          iso_exchange VARCHAR(64) NULL,
          bz_exchange VARCHAR(128) NULL,
          otc_market VARCHAR(64) NULL,
          otc_tier VARCHAR(64) NULL,
          quote_type VARCHAR(32) NULL,
          name VARCHAR(255) NULL,
          company_standard_name VARCHAR(255) NULL,
          description VARCHAR(255) NULL,
          sector VARCHAR(128) NULL,
          industry VARCHAR(255) NULL,
          `open` DECIMAL(20,6) NULL,
          `high` DECIMAL(20,6) NULL,
          `low` DECIMAL(20,6) NULL,
          bid_price DECIMAL(20,6) NULL,
          bid_size BIGINT NULL,
          bid_time DATETIME NULL,
          ask_price DECIMAL(20,6) NULL,
          ask_size BIGINT NULL,
          ask_time DATETIME NULL,
          last_trade_price DECIMAL(20,6) NULL,
          last_trade_size BIGINT NULL,
          last_trade_time DATETIME NULL,
          volume BIGINT NULL,
          change_value DECIMAL(20,6) NULL,
          change_percent DECIMAL(20,8) NULL,
          previous_close_price DECIMAL(20,6) NULL,
          previous_close_date DATETIME NULL,
          fifty_day_average_price DECIMAL(20,6) NULL,
          hundred_day_average_price DECIMAL(20,6) NULL,
          two_hundred_day_average_price DECIMAL(20,6) NULL,
          average_volume BIGINT NULL,
          fifty_two_week_high DECIMAL(20,6) NULL,
          fifty_two_week_low DECIMAL(20,6) NULL,
          market_cap DECIMAL(28,8) NULL,
          shares_outstanding BIGINT NULL,
          shares_float BIGINT NULL,
          pe DECIMAL(20,8) NULL,
          forward_pe DECIMAL(20,8) NULL,
          dividend_yield DECIMAL(20,8) NULL,
          dividend DECIMAL(20,8) NULL,
          payout_ratio DECIMAL(20,8) NULL,
          eth_price DECIMAL(20,6) NULL,
          eth_volume BIGINT NULL,
          eth_time DATETIME NULL,
          currency VARCHAR(16) NULL,
          issuer_name VARCHAR(255) NULL,
          primary_listing TINYINT(1) NULL,
          short_description VARCHAR(255) NULL,
          issuer_short_name VARCHAR(255) NULL,
          source VARCHAR(32) NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (quote_snapshot_id),
          UNIQUE KEY uq_quote_snapshot_identity (source, provider_symbol, snapshot_timestamp),
          KEY instrument_id (instrument_id),
          KEY ix_quote_snapshot_provider_time (provider_symbol, snapshot_timestamp),
          KEY ix_quote_snapshot_time (snapshot_timestamp),
          CONSTRAINT quote_snapshot_ibfk_1
            FOREIGN KEY (instrument_id)
            REFERENCES us_share.instrument (instrument_id)
        )
        """
    )


def _create_legacy_live_ohlcv_snapshot() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS us_share.live_ohlcv_snapshot (
          live_ohlcv_snapshot_id BIGINT NOT NULL AUTO_INCREMENT,
          instrument_id BIGINT NOT NULL,
          symbol VARCHAR(64) NOT NULL,
          provider_symbol VARCHAR(128) NOT NULL,
          snapshot_timestamp DATETIME NOT NULL,
          gmtoffset INT NULL,
          `open` DECIMAL(20,6) NULL,
          `high` DECIMAL(20,6) NULL,
          `low` DECIMAL(20,6) NULL,
          `close` DECIMAL(20,6) NULL,
          volume BIGINT NULL,
          previous_close_price DECIMAL(20,6) NULL,
          change_value DECIMAL(20,6) NULL,
          change_percent DECIMAL(20,8) NULL,
          source VARCHAR(32) NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (live_ohlcv_snapshot_id),
          UNIQUE KEY uq_live_ohlcv_snapshot_identity
            (source, provider_symbol, snapshot_timestamp),
          KEY instrument_id (instrument_id),
          KEY ix_live_ohlcv_provider_time (provider_symbol, snapshot_timestamp),
          KEY ix_live_ohlcv_time (snapshot_timestamp),
          CONSTRAINT live_ohlcv_snapshot_ibfk_1
            FOREIGN KEY (instrument_id)
            REFERENCES us_share.instrument (instrument_id)
        )
        """
    )


def _create_legacy_websocket_event() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS us_share.websocket_event (
          websocket_event_id BIGINT NOT NULL AUTO_INCREMENT,
          instrument_id BIGINT NOT NULL,
          stream_name VARCHAR(32) NOT NULL,
          symbol VARCHAR(64) NOT NULL,
          provider_symbol VARCHAR(128) NOT NULL,
          event_timestamp DATETIME NOT NULL,
          event_hash VARCHAR(64) NOT NULL,
          price DECIMAL(20,8) NULL,
          size DECIMAL(24,8) NULL,
          bid_price DECIMAL(20,8) NULL,
          bid_size DECIMAL(24,8) NULL,
          ask_price DECIMAL(20,8) NULL,
          ask_size DECIMAL(24,8) NULL,
          trade_condition VARCHAR(32) NULL,
          is_dark_pool TINYINT(1) NULL,
          market_status VARCHAR(32) NULL,
          daily_change_percent DECIMAL(20,8) NULL,
          daily_change_value DECIMAL(20,8) NULL,
          raw_json TEXT NOT NULL,
          source VARCHAR(32) NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (websocket_event_id),
          UNIQUE KEY uq_websocket_event_identity
            (source, stream_name, symbol, event_timestamp, event_hash),
          KEY instrument_id (instrument_id),
          KEY ix_websocket_event_stream_symbol_time (stream_name, symbol, event_timestamp),
          KEY ix_websocket_event_timestamp (event_timestamp),
          CONSTRAINT websocket_event_ibfk_1
            FOREIGN KEY (instrument_id)
            REFERENCES us_share.instrument (instrument_id)
        )
        """
    )


def _copy_app_log_rows_back() -> None:
    _copy_back(
        "instrument_search_snapshot",
        [
            "search_snapshot_id",
            "query_text",
            "query_hash",
            "limit_value",
            "exchange",
            "asset_type",
            "bonds_only",
            "source",
            "created_at",
        ],
    )
    _copy_back(
        "instrument_search_result",
        [
            "search_result_id",
            "search_snapshot_id",
            "row_number",
            "code",
            "exchange",
            "name",
            "asset_type",
            "country",
            "currency",
            "isin",
            "previous_close",
            "previous_close_date",
            "is_primary",
            "created_at",
        ],
    )
    _copy_back(
        "screener_snapshot",
        [
            "snapshot_id",
            "snapshot_name",
            "query_hash",
            "filters_json",
            "signals",
            "sort",
            "limit_value",
            "offset_value",
            "source",
            "created_at",
        ],
    )
    _copy_back(
        "screener_snapshot_member",
        [
            "member_id",
            "snapshot_id",
            "row_number",
            "code",
            "provider_symbol",
            "name",
            "exchange",
            "currency_symbol",
            "sector",
            "industry",
            "market_capitalization",
            "earnings_share",
            "dividend_yield",
            "pe",
            "peg",
            "pb",
            "ps",
            "revenue",
            "ebitda",
            "roe",
            "roa",
            "beta",
            "refund_1d_p",
            "refund_5d_p",
            "refund_ytd_p",
            "created_at",
        ],
    )
    _copy_back(
        "quote_snapshot",
        [
            "quote_snapshot_id",
            "instrument_id",
            "symbol",
            "provider_symbol",
            "snapshot_timestamp",
            "exchange",
            "iso_exchange",
            "bz_exchange",
            "otc_market",
            "otc_tier",
            "quote_type",
            "name",
            "company_standard_name",
            "description",
            "sector",
            "industry",
            "open",
            "high",
            "low",
            "bid_price",
            "bid_size",
            "bid_time",
            "ask_price",
            "ask_size",
            "ask_time",
            "last_trade_price",
            "last_trade_size",
            "last_trade_time",
            "volume",
            "change_value",
            "change_percent",
            "previous_close_price",
            "previous_close_date",
            "fifty_day_average_price",
            "hundred_day_average_price",
            "two_hundred_day_average_price",
            "average_volume",
            "fifty_two_week_high",
            "fifty_two_week_low",
            "market_cap",
            "shares_outstanding",
            "shares_float",
            "pe",
            "forward_pe",
            "dividend_yield",
            "dividend",
            "payout_ratio",
            "eth_price",
            "eth_volume",
            "eth_time",
            "currency",
            "issuer_name",
            "primary_listing",
            "short_description",
            "issuer_short_name",
            "source",
            "created_at",
            "updated_at",
        ],
        "instrument_id IS NOT NULL",
    )
    _copy_back(
        "live_ohlcv_snapshot",
        [
            "live_ohlcv_snapshot_id",
            "instrument_id",
            "symbol",
            "provider_symbol",
            "snapshot_timestamp",
            "gmtoffset",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "previous_close_price",
            "change_value",
            "change_percent",
            "source",
            "created_at",
            "updated_at",
        ],
        "instrument_id IS NOT NULL",
    )
    _copy_back(
        "websocket_event",
        [
            "websocket_event_id",
            "instrument_id",
            "stream_name",
            "symbol",
            "provider_symbol",
            "event_timestamp",
            "event_hash",
            "price",
            "size",
            "bid_price",
            "bid_size",
            "ask_price",
            "ask_size",
            "trade_condition",
            "is_dark_pool",
            "market_status",
            "daily_change_percent",
            "daily_change_value",
            "raw_json",
            "source",
            "created_at",
            "updated_at",
        ],
        "instrument_id IS NOT NULL",
    )


def _copy_back(table_name: str, columns: list[str], where_clause: str | None = None) -> None:
    if not _table_exists(APP_LOG_SCHEMA, table_name):
        return
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    where_sql = f"WHERE {where_clause}" if where_clause else ""
    op.execute(
        f"""
        INSERT IGNORE INTO {LEGACY_SCHEMA}.{table_name} ({column_sql})
        SELECT {column_sql}
        FROM {APP_LOG_SCHEMA}.{table_name}
        {where_sql}
        """
    )


def _table_exists(schema_name: str, table_name: str) -> bool:
    connection = op.get_bind()
    count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = :schema_name
              AND TABLE_NAME = :table_name
            """
        ),
        {"schema_name": schema_name, "table_name": table_name},
    ).scalar_one()
    return bool(count)


def _table_count(schema_name: str, table_name: str) -> int:
    connection = op.get_bind()
    return int(connection.execute(sa.text(f"SELECT COUNT(*) FROM {schema_name}.{table_name}")).scalar_one())


def _quote_identifier(identifier: str) -> str:
    return f"`{identifier}`"
