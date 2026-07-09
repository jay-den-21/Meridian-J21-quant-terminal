from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.sql import quoted_name

US_SHARE_SCHEMA = "us_share"
# Current A-share schema is "a_share"; the legacy local program/database name was "qtdb_pro".
A_SHARE_SCHEMA = "a_share"
SYSTEM_SCHEMA = quoted_name("system", True)

metadata = MetaData()

# us_share.instrument example row:
# - instrument_id: 1
# - market: "US"
# - symbol: "AAPL"
# - provider: "EODHD"
# - provider_symbol: "AAPL.US"
# - name: "Apple Inc."
# - exchange: "NASDAQ"
# - asset_type: "stock"
# - currency: "USD"
# - is_active: True
# - listed_date: date(1980, 12, 12)
# - delisted_date: None
# - created_at: datetime(2026, 5, 26, 21, 30, 0)
# - updated_at: datetime(2026, 5, 26, 21, 30, 0)
instrument = Table(
    "instrument",
    metadata,
    Column("instrument_id", BigInteger, primary_key=True, autoincrement=True),
    Column("market", String(16), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("provider", String(32), nullable=False),
    Column("provider_symbol", String(128), nullable=False),
    Column("name", String(255), nullable=False),
    Column("exchange", String(64), nullable=False),
    Column("asset_type", String(32), nullable=False),
    Column("currency", String(16), nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column("listed_date", Date),
    Column("delisted_date", Date),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    ),
    UniqueConstraint("provider", "provider_symbol", name="uq_instrument_provider_symbol"),
    Index("ix_instrument_market_symbol", "market", "symbol"),
    schema=US_SHARE_SCHEMA,
)


def _instrument_view(name: str) -> Table:
    """Define a read-only SQLAlchemy handle for an `instrument` asset-type view."""
    return Table(
        name,
        metadata,
        Column("instrument_id", BigInteger, primary_key=True),
        Column("market", String(16), nullable=False),
        Column("symbol", String(64), nullable=False),
        Column("provider", String(32), nullable=False),
        Column("provider_symbol", String(128), nullable=False),
        Column("name", String(255), nullable=False),
        Column("exchange", String(64), nullable=False),
        Column("asset_type", String(32), nullable=False),
        Column("currency", String(16), nullable=False),
        Column("is_active", Boolean, nullable=False),
        Column("listed_date", Date),
        Column("delisted_date", Date),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
        schema=US_SHARE_SCHEMA,
        info={"is_view": True},
    )


stock_instrument = _instrument_view("stock_instrument")
etf_instrument = _instrument_view("etf_instrument")
index_instrument = _instrument_view("index_instrument")

# us_share.instrument_identifier_history example row:
# - identifier_history_id: 1
# - instrument_id: 1
# - id_type: "provider_symbol"
# - id_value: "FB.US"
# - valid_from: None
# - valid_to: date(2022, 6, 8)
# - source: "EODHD_SYMBOL_CHANGE_HISTORY"
# - created_at: datetime(2026, 5, 28, 10, 0, 0)
# - updated_at: datetime(2026, 5, 28, 10, 0, 0)
instrument_identifier_history = Table(
    "instrument_identifier_history",
    metadata,
    Column("identifier_history_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "instrument_id",
        BigInteger,
        ForeignKey(f"{US_SHARE_SCHEMA}.instrument.instrument_id"),
        nullable=False,
    ),
    Column("id_type", String(64), nullable=False),
    Column("id_value", String(128), nullable=False),
    Column("valid_from", Date),
    Column("valid_to", Date),
    Column("source", String(64), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    ),
    UniqueConstraint(
        "instrument_id",
        "id_type",
        "id_value",
        "valid_from",
        "source",
        name="uq_identifier_history_identity",
    ),
    Index("ix_identifier_history_value", "id_type", "id_value"),
    schema=US_SHARE_SCHEMA,
)

# us_share.instrument_lifecycle_event example row:
# - lifecycle_event_id: 1
# - instrument_id: 1
# - event_type: "delisted"
# - event_date: date(2024, 5, 20)
# - symbol: "OLD"
# - provider_symbol: "OLD.US"
# - source: "EODHD_DELISTED_EXCHANGE_SYMBOLS"
# - event_key: "delisted:OLD.US:2024-05-20"
instrument_lifecycle_event = Table(
    "instrument_lifecycle_event",
    metadata,
    Column("lifecycle_event_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "instrument_id",
        BigInteger,
        ForeignKey(f"{US_SHARE_SCHEMA}.instrument.instrument_id"),
        nullable=False,
    ),
    Column("event_type", String(32), nullable=False),
    Column("event_date", Date),
    Column("symbol", String(64), nullable=False),
    Column("provider_symbol", String(128), nullable=False),
    Column("source", String(64), nullable=False),
    Column("event_key", String(255), nullable=False),
    Column("details", Text),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    ),
    UniqueConstraint("source", "event_key", name="uq_lifecycle_event_source_key"),
    Index("ix_lifecycle_event_provider_symbol", "provider_symbol"),
    Index("ix_lifecycle_event_type_date", "event_type", "event_date"),
    schema=US_SHARE_SCHEMA,
)


def _asset_daily_price_table(
    table_name: str,
    id_column: str,
    unique_name: str,
    symbol_index_name: str,
    trade_date_index_name: str,
) -> Table:
    """Define one asset-specific daily OHLCV table with the common price shape."""
    return Table(
        table_name,
        metadata,
        Column(id_column, BigInteger, primary_key=True, autoincrement=True),
        Column(
            "instrument_id",
            BigInteger,
            ForeignKey(f"{US_SHARE_SCHEMA}.instrument.instrument_id"),
            nullable=False,
        ),
        Column("symbol", String(64), nullable=False),
        Column("provider_symbol", String(128), nullable=False),
        Column("trade_date", Date, nullable=False),
        Column("open", Numeric(20, 6), nullable=False),
        Column("high", Numeric(20, 6), nullable=False),
        Column("low", Numeric(20, 6), nullable=False),
        Column("close", Numeric(20, 6), nullable=False),
        Column("adjusted_close", Numeric(20, 6), nullable=False),
        Column("volume", BigInteger, nullable=False),
        Column("currency", String(16), nullable=False),
        Column("source", String(32), nullable=False),
        Column("source_updated_at", DateTime),
        Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
        Column(
            "updated_at",
            DateTime,
            nullable=False,
            server_default=func.current_timestamp(),
            server_onupdate=func.current_timestamp(),
        ),
        UniqueConstraint("instrument_id", "trade_date", name=unique_name),
        Index(symbol_index_name, "symbol", "trade_date"),
        Index(trade_date_index_name, "trade_date"),
        schema=US_SHARE_SCHEMA,
    )


stock_daily_price = _asset_daily_price_table(
    "stock_daily_price",
    "stock_daily_price_id",
    "uq_stock_daily_price_instrument_date",
    "ix_stock_daily_price_symbol_date",
    "ix_stock_daily_price_trade_date",
)
etf_daily_price = _asset_daily_price_table(
    "etf_daily_price",
    "etf_daily_price_id",
    "uq_etf_daily_price_instrument_date",
    "ix_etf_daily_price_symbol_date",
    "ix_etf_daily_price_trade_date",
)
index_daily_price = _asset_daily_price_table(
    "index_daily_price",
    "index_daily_price_id",
    "uq_index_daily_price_instrument_date",
    "ix_index_daily_price_symbol_date",
    "ix_index_daily_price_trade_date",
)

# us_share.market_calendar example row:
# - calendar_id: 1
# - calendar_date: date(2026, 5, 22)
# - is_trading_day: True
# - source: "EODHD"
# - created_at: datetime(2026, 5, 20, 12, 0, 0)
# - updated_at: datetime(2026, 5, 20, 12, 0, 0)
market_calendar = Table(
    "market_calendar",
    metadata,
    Column("calendar_id", BigInteger, primary_key=True, autoincrement=True),
    Column("calendar_date", Date, nullable=False),
    Column("is_trading_day", Boolean, nullable=False),
    Column("source", String(32), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    ),
    UniqueConstraint("calendar_date", name="uq_market_calendar_date"),
    schema=US_SHARE_SCHEMA,
)

# system.ingestion_task_run example row:
# - run_id: 101
# - job_name: "eodhd_exchange_symbols"
# - market: "US"
# - source: "EODHD"
# - target_schema: "us_share"
# - target_table: "instrument"
# - status: "success"
# - date_from: None
# - date_to: None
# - started_at: datetime(2026, 5, 26, 21, 30, 0)
# - finished_at: datetime(2026, 5, 26, 21, 30, 8)
# - rows_fetched: 9560
# - rows_inserted: 8120
# - rows_updated: 0
# - rows_rejected: 1440
# - api_calls: 1
# - error_message: None
# - config_hash: "sha256:7f2c..."
# - code_version: "0.1.0"
ingestion_task_run = Table(
    "ingestion_task_run",
    metadata,
    Column("run_id", BigInteger, primary_key=True, autoincrement=True),
    Column("job_name", String(128), nullable=False),
    Column("market", String(16), nullable=False),
    Column("source", String(32), nullable=False),
    Column("target_schema", String(64), nullable=False),
    Column("target_table", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("date_from", Date),
    Column("date_to", Date),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Column("rows_fetched", BigInteger, nullable=False, server_default="0"),
    Column("rows_inserted", BigInteger, nullable=False, server_default="0"),
    Column("rows_updated", BigInteger, nullable=False, server_default="0"),
    Column("rows_rejected", BigInteger, nullable=False, server_default="0"),
    Column("api_calls", Integer, nullable=False, server_default="0"),
    Column("error_message", Text),
    Column("config_hash", String(128)),
    Column("code_version", String(64)),
    schema=SYSTEM_SCHEMA,
)

# system.api_call_log example row:
# - api_call_id: 501
# - run_id: 101
# - source: "EODHD"
# - endpoint: "/exchange-symbol-list/US"
# - provider_symbol: None
# - date_from: None
# - date_to: None
# - status_code: 200
# - success: True
# - retry_count: 0
# - rows_returned: 9560
# - error_message: None
# - called_at: datetime(2026, 5, 26, 21, 30, 1)
# - duration_ms: 842
api_call_log = Table(
    "api_call_log",
    metadata,
    Column("api_call_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        BigInteger,
        ForeignKey(f"{SYSTEM_SCHEMA}.ingestion_task_run.run_id"),
        nullable=False,
    ),
    Column("source", String(32), nullable=False),
    Column("endpoint", String(255), nullable=False),
    Column("provider_symbol", String(128)),
    Column("date_from", Date),
    Column("date_to", Date),
    Column("status_code", Integer),
    Column("success", Boolean, nullable=False),
    Column("retry_count", Integer, nullable=False, server_default="0"),
    Column("rows_returned", BigInteger, nullable=False, server_default="0"),
    Column("error_message", Text),
    Column("called_at", DateTime, nullable=False),
    Column("duration_ms", Integer),
    Index("ix_api_call_log_run_id", "run_id"),
    schema=SYSTEM_SCHEMA,
)

# system.data_quality_check_run example row:
# - check_run_id: 301
# - market: "US"
# - target_schema: "us_share"
# - target_table: "daily_price"
# - check_scope: "daily_price:2026-05-01..2026-05-22"
# - status: "success"
# - started_at: datetime(2026, 5, 26, 22, 0, 0)
# - finished_at: datetime(2026, 5, 26, 22, 1, 12)
# - issues_found: 3
# - error_message: None
data_quality_check_run = Table(
    "data_quality_check_run",
    metadata,
    Column("check_run_id", BigInteger, primary_key=True, autoincrement=True),
    Column("market", String(16), nullable=False),
    Column("target_schema", String(64), nullable=False),
    Column("target_table", String(64), nullable=False),
    Column("check_scope", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Column("issues_found", BigInteger, nullable=False, server_default="0"),
    Column("error_message", Text),
    schema=SYSTEM_SCHEMA,
)

# system.data_quality_issue example row:
# - issue_id: 9001
# - check_run_id: 301
# - market: "US"
# - target_schema: "us_share"
# - target_table: "daily_price"
# - issue_type: "invalid_ohlcv"
# - severity: "error"
# - instrument_id: 1
# - symbol: "AAPL"
# - trade_date: date(2026, 5, 22)
# - details: "high is lower than close"
# - status: "open"
# - created_at: datetime(2026, 5, 26, 22, 1, 0)
# - resolved_at: None
data_quality_issue = Table(
    "data_quality_issue",
    metadata,
    Column("issue_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "check_run_id",
        BigInteger,
        ForeignKey(f"{SYSTEM_SCHEMA}.data_quality_check_run.check_run_id"),
        nullable=False,
    ),
    Column("market", String(16), nullable=False),
    Column("target_schema", String(64), nullable=False),
    Column("target_table", String(64), nullable=False),
    Column("issue_type", String(64), nullable=False),
    Column("severity", String(32), nullable=False),
    Column("instrument_id", BigInteger),
    Column("symbol", String(64)),
    Column("trade_date", Date),
    Column("details", Text),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column("resolved_at", DateTime),
    Index("ix_data_quality_issue_status", "status"),
    Index("ix_data_quality_issue_symbol_date", "symbol", "trade_date"),
    schema=SYSTEM_SCHEMA,
)

# system.repair_plan example row:
# - repair_plan_id: 7001
# - issue_id: 9001
# - market: "US"
# - repair_type: "backfill_missing_daily_price"
# - symbol: "AAPL"
# - provider_symbol: "AAPL.US"
# - date_from: date(2026, 5, 22)
# - date_to: date(2026, 5, 22)
# - status: "pending_confirmation"
# - created_at: datetime(2026, 5, 26, 22, 5, 0)
# - confirmed_at: None
# - executed_at: None
# - result_message: None
repair_plan = Table(
    "repair_plan",
    metadata,
    Column("repair_plan_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "issue_id",
        BigInteger,
        ForeignKey(f"{SYSTEM_SCHEMA}.data_quality_issue.issue_id"),
        nullable=False,
    ),
    Column("market", String(16), nullable=False),
    Column("repair_type", String(64), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("provider_symbol", String(128), nullable=False),
    Column("date_from", Date, nullable=False),
    Column("date_to", Date, nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column("confirmed_at", DateTime),
    Column("executed_at", DateTime),
    Column("result_message", Text),
    Index("ix_repair_plan_status", "status"),
    schema=SYSTEM_SCHEMA,
)

# system.quarantine_plan example row:
# - quarantine_plan_id: 8001
# - issue_id: 9002
# - action_type: "quarantine_daily_price_row"
# - target_table: "stock_daily_price"
# - status: "pending_confirmation"
quarantine_plan = Table(
    "quarantine_plan",
    metadata,
    Column("quarantine_plan_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "issue_id",
        BigInteger,
        ForeignKey(f"{SYSTEM_SCHEMA}.data_quality_issue.issue_id"),
        nullable=False,
    ),
    Column("market", String(16), nullable=False),
    Column("action_type", String(64), nullable=False),
    Column("target_schema", String(64), nullable=False),
    Column("target_table", String(64), nullable=False),
    Column("instrument_id", BigInteger),
    Column("symbol", String(64)),
    Column("provider_symbol", String(128)),
    Column("date_from", Date, nullable=False),
    Column("date_to", Date, nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column("confirmed_at", DateTime),
    Column("executed_at", DateTime),
    Column("row_count", BigInteger, nullable=False, server_default="0"),
    Column("result_message", Text),
    UniqueConstraint("issue_id", "action_type", name="uq_quarantine_plan_issue_action"),
    Index("ix_quarantine_plan_status", "status"),
    schema=SYSTEM_SCHEMA,
)

# system.quarantined_daily_price_row preserves source row payloads before destructive cleanup.
quarantined_daily_price_row = Table(
    "quarantined_daily_price_row",
    metadata,
    Column("quarantined_row_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "quarantine_plan_id",
        BigInteger,
        ForeignKey(f"{SYSTEM_SCHEMA}.quarantine_plan.quarantine_plan_id"),
        nullable=False,
    ),
    Column(
        "issue_id",
        BigInteger,
        ForeignKey(f"{SYSTEM_SCHEMA}.data_quality_issue.issue_id"),
        nullable=False,
    ),
    Column("market", String(16), nullable=False),
    Column("target_schema", String(64), nullable=False),
    Column("target_table", String(64), nullable=False),
    Column("source_primary_key", BigInteger, nullable=False),
    Column("instrument_id", BigInteger),
    Column("symbol", String(64)),
    Column("provider_symbol", String(128)),
    Column("trade_date", Date),
    Column("action_type", String(64), nullable=False),
    Column("quarantine_reason", String(128), nullable=False),
    Column("row_payload", Text, nullable=False),
    Column("row_hash", String(64), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Index("ix_quarantined_daily_price_row_plan", "quarantine_plan_id"),
    Index("ix_quarantined_daily_price_row_source", "target_table", "instrument_id", "trade_date"),
    schema=SYSTEM_SCHEMA,
)

# system.bulk_unmatched_daily_price_observation preserves EODHD Bulk EOD rows that
# were not matched to the current instrument universe during the fast ingest path.
bulk_unmatched_daily_price_observation = Table(
    "bulk_unmatched_daily_price_observation",
    metadata,
    Column("observation_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        BigInteger,
        ForeignKey(f"{SYSTEM_SCHEMA}.ingestion_task_run.run_id"),
        nullable=False,
    ),
    Column("market", String(16), nullable=False),
    Column("exchange", String(32), nullable=False),
    Column("provider_symbol", String(128), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("trade_date", Date, nullable=False),
    Column("name", String(255)),
    Column("eodhd_type", String(64)),
    Column("open", Numeric(20, 6)),
    Column("high", Numeric(20, 6)),
    Column("low", Numeric(20, 6)),
    Column("close", Numeric(20, 6)),
    Column("adjusted_close", Numeric(20, 6)),
    Column("volume", BigInteger),
    Column("currency", String(16)),
    Column("raw_payload", Text, nullable=False),
    Column("classification_status", String(32), nullable=False),
    Column("classified_asset_type", String(32)),
    Column(
        "matched_instrument_id",
        BigInteger,
        ForeignKey(f"{US_SHARE_SCHEMA}.instrument.instrument_id"),
    ),
    Column("reason", Text),
    Column("source", String(32), nullable=False),
    Column("first_seen_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column(
        "last_seen_at",
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    ),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    ),
    UniqueConstraint(
        "source",
        "provider_symbol",
        "trade_date",
        name="uq_bulk_unmatched_source_symbol_date",
    ),
    Index("ix_bulk_unmatched_date_status", "trade_date", "classification_status"),
    Index("ix_bulk_unmatched_provider_symbol", "provider_symbol"),
    Index("ix_bulk_unmatched_matched_instrument", "matched_instrument_id"),
    schema=SYSTEM_SCHEMA,
)
