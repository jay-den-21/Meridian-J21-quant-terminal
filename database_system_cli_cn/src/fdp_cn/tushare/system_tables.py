"""CN-owned checkpoint and API audit tables."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.sql import quoted_name


SYSTEM_SCHEMA = quoted_name("system_cn", True)
metadata = MetaData()

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
    Column("checkpoint_json", JSON),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    schema=SYSTEM_SCHEMA,
)

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
    Column(
        "called_at", DateTime, nullable=False, server_default=func.current_timestamp()
    ),
    Column("duration_ms", Integer),
    Index("ix_api_call_log_run_id", "run_id"),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    schema=SYSTEM_SCHEMA,
)

index_weight_stage = Table(
    "index_weight_stage",
    metadata,
    Column(
        "run_id",
        BigInteger,
        ForeignKey(f"{SYSTEM_SCHEMA}.ingestion_task_run.run_id"),
        nullable=False,
    ),
    Column("unit_key", String(128), nullable=False),
    Column("trade_date", Date, nullable=False),
    Column("index_code", String(20), nullable=False),
    Column("con_code", String(20), nullable=False),
    Column("weight", Numeric(25, 8), nullable=False),
    PrimaryKeyConstraint(
        "run_id",
        "unit_key",
        "trade_date",
        "index_code",
        "con_code",
        name="pk_index_weight_stage",
    ),
    Index("ix_index_weight_stage_run_unit", "run_id", "unit_key"),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    schema=SYSTEM_SCHEMA,
)
