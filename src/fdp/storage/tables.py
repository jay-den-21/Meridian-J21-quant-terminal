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
    Time,
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

# us_share.daily_price example row:
# - daily_price_id: 1
# - instrument_id: 1
# - trade_date: date(2026, 5, 22)
# - open: Decimal("200.150000")
# - high: Decimal("202.740000")
# - low: Decimal("199.700000")
# - close: Decimal("201.360000")
# - adjusted_close: Decimal("201.360000")
# - volume: 48750000
# - currency: "USD"
# - source: "EODHD"
# - source_updated_at: datetime(2026, 5, 23, 1, 15, 0)
# - created_at: datetime(2026, 5, 23, 1, 20, 0)
# - updated_at: datetime(2026, 5, 23, 1, 20, 0)
daily_price = Table(
    "daily_price",
    metadata,
    Column("daily_price_id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "instrument_id",
        BigInteger,
        ForeignKey(f"{US_SHARE_SCHEMA}.instrument.instrument_id"),
        nullable=False,
    ),
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
    UniqueConstraint("instrument_id", "trade_date", name="uq_daily_price_instrument_date"),
    Index("ix_daily_price_trade_date", "trade_date"),
    schema=US_SHARE_SCHEMA,
)

# us_share.market_calendar example row:
# - calendar_id: 1
# - market: "US"
# - exchange: "NASDAQ"
# - calendar_date: date(2026, 5, 22)
# - is_trading_day: True
# - is_early_close: False
# - early_close_time: None
# - timezone: "America/New_York"
# - source: "EODHD"
# - created_at: datetime(2026, 5, 20, 12, 0, 0)
# - updated_at: datetime(2026, 5, 20, 12, 0, 0)
market_calendar = Table(
    "market_calendar",
    metadata,
    Column("calendar_id", BigInteger, primary_key=True, autoincrement=True),
    Column("market", String(16), nullable=False),
    Column("exchange", String(64), nullable=False),
    Column("calendar_date", Date, nullable=False),
    Column("is_trading_day", Boolean, nullable=False),
    Column("is_early_close", Boolean, nullable=False),
    Column("early_close_time", Time),
    Column("timezone", String(64), nullable=False),
    Column("source", String(32), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.current_timestamp()),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    ),
    UniqueConstraint("market", "exchange", "calendar_date", name="uq_market_calendar_date"),
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
