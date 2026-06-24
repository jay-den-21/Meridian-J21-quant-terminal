"""Create initial platform schemas and tables.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS us_share")
    op.execute("CREATE SCHEMA IF NOT EXISTS a_share")
    op.execute("CREATE SCHEMA IF NOT EXISTS `system`")

    op.create_table(
        "instrument",
        sa.Column("instrument_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_symbol", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("listed_date", sa.Date(), nullable=True),
        sa.Column("delisted_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("instrument_id"),
        sa.UniqueConstraint("provider", "provider_symbol", name="uq_instrument_provider_symbol"),
        schema="us_share",
    )
    op.create_index(
        "ix_instrument_market_symbol",
        "instrument",
        ["market", "symbol"],
        unique=False,
        schema="us_share",
    )

    op.create_table(
        "daily_price",
        sa.Column("daily_price_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("adjusted_close", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["us_share.instrument.instrument_id"],
        ),
        sa.PrimaryKeyConstraint("daily_price_id"),
        sa.UniqueConstraint(
            "instrument_id",
            "trade_date",
            name="uq_daily_price_instrument_date",
        ),
        schema="us_share",
    )
    op.create_index(
        "ix_daily_price_trade_date",
        "daily_price",
        ["trade_date"],
        unique=False,
        schema="us_share",
    )

    op.create_table(
        "market_calendar",
        sa.Column("calendar_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("is_trading_day", sa.Boolean(), nullable=False),
        sa.Column("is_early_close", sa.Boolean(), nullable=False),
        sa.Column("early_close_time", sa.Time(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("calendar_id"),
        sa.UniqueConstraint("market", "exchange", "calendar_date", name="uq_market_calendar_date"),
        schema="us_share",
    )

    op.create_table(
        "ingestion_task_run",
        sa.Column("run_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("target_schema", sa.String(length=64), nullable=False),
        sa.Column("target_table", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("rows_fetched", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("rows_inserted", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("rows_updated", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("rows_rejected", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("api_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("config_hash", sa.String(length=128), nullable=True),
        sa.Column("code_version", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
        schema="system",
    )

    op.create_table(
        "api_call_log",
        sa.Column("api_call_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("provider_symbol", sa.String(length=128), nullable=True),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rows_returned", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("called_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["system.ingestion_task_run.run_id"],
        ),
        sa.PrimaryKeyConstraint("api_call_id"),
        schema="system",
    )
    op.create_index(
        "ix_api_call_log_run_id",
        "api_call_log",
        ["run_id"],
        unique=False,
        schema="system",
    )

    op.create_table(
        "data_quality_check_run",
        sa.Column("check_run_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("target_schema", sa.String(length=64), nullable=False),
        sa.Column("target_table", sa.String(length=64), nullable=False),
        sa.Column("check_scope", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("issues_found", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("check_run_id"),
        schema="system",
    )

    op.create_table(
        "data_quality_issue",
        sa.Column("issue_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("check_run_id", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("target_schema", sa.String(length=64), nullable=False),
        sa.Column("target_table", sa.String(length=64), nullable=False),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["check_run_id"],
            ["system.data_quality_check_run.check_run_id"],
        ),
        sa.PrimaryKeyConstraint("issue_id"),
        schema="system",
    )
    op.create_index(
        "ix_data_quality_issue_status",
        "data_quality_issue",
        ["status"],
        unique=False,
        schema="system",
    )
    op.create_index(
        "ix_data_quality_issue_symbol_date",
        "data_quality_issue",
        ["symbol", "trade_date"],
        unique=False,
        schema="system",
    )

    op.create_table(
        "repair_plan",
        sa.Column("repair_plan_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("issue_id", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("repair_type", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("provider_symbol", sa.String(length=128), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("result_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["system.data_quality_issue.issue_id"],
        ),
        sa.PrimaryKeyConstraint("repair_plan_id"),
        schema="system",
    )
    op.create_index(
        "ix_repair_plan_status",
        "repair_plan",
        ["status"],
        unique=False,
        schema="system",
    )


def downgrade() -> None:
    op.drop_index("ix_repair_plan_status", table_name="repair_plan", schema="system")
    op.drop_table("repair_plan", schema="system")

    op.drop_index(
        "ix_data_quality_issue_symbol_date",
        table_name="data_quality_issue",
        schema="system",
    )
    op.drop_index("ix_data_quality_issue_status", table_name="data_quality_issue", schema="system")
    op.drop_table("data_quality_issue", schema="system")

    op.drop_table("data_quality_check_run", schema="system")

    op.drop_index("ix_api_call_log_run_id", table_name="api_call_log", schema="system")
    op.drop_table("api_call_log", schema="system")

    op.drop_table("ingestion_task_run", schema="system")

    op.drop_table("market_calendar", schema="us_share")

    op.drop_index("ix_daily_price_trade_date", table_name="daily_price", schema="us_share")
    op.drop_table("daily_price", schema="us_share")

    op.drop_index("ix_instrument_market_symbol", table_name="instrument", schema="us_share")
    op.drop_table("instrument", schema="us_share")

    op.execute("DROP SCHEMA IF EXISTS `system`")
    op.execute("DROP SCHEMA IF EXISTS a_share")
    op.execute("DROP SCHEMA IF EXISTS us_share")
