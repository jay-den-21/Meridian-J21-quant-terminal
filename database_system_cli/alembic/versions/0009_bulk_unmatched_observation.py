"""add bulk unmatched observation table

Revision ID: 0009_bulk_unmatched
Revises: 0008_delisted_lifecycle
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa


revision: str = "0009_bulk_unmatched"
down_revision: str | None = "0008_delisted_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bulk_unmatched_daily_price_observation",
        sa.Column("observation_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("provider_symbol", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("eodhd_type", sa.String(length=64), nullable=True),
        sa.Column("open", sa.Numeric(20, 6), nullable=True),
        sa.Column("high", sa.Numeric(20, 6), nullable=True),
        sa.Column("low", sa.Numeric(20, 6), nullable=True),
        sa.Column("close", sa.Numeric(20, 6), nullable=True),
        sa.Column("adjusted_close", sa.Numeric(20, 6), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=False),
        sa.Column("classification_status", sa.String(length=32), nullable=False),
        sa.Column("classified_asset_type", sa.String(length=32), nullable=True),
        sa.Column("matched_instrument_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["run_id"], ["system.ingestion_task_run.run_id"]),
        sa.ForeignKeyConstraint(["matched_instrument_id"], ["us_share.instrument.instrument_id"]),
        sa.PrimaryKeyConstraint("observation_id"),
        sa.UniqueConstraint(
            "source",
            "provider_symbol",
            "trade_date",
            name="uq_bulk_unmatched_source_symbol_date",
        ),
        schema="system",
    )
    op.create_index(
        "ix_bulk_unmatched_date_status",
        "bulk_unmatched_daily_price_observation",
        ["trade_date", "classification_status"],
        schema="system",
    )
    op.create_index(
        "ix_bulk_unmatched_provider_symbol",
        "bulk_unmatched_daily_price_observation",
        ["provider_symbol"],
        schema="system",
    )
    op.create_index(
        "ix_bulk_unmatched_matched_instrument",
        "bulk_unmatched_daily_price_observation",
        ["matched_instrument_id"],
        schema="system",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bulk_unmatched_matched_instrument",
        table_name="bulk_unmatched_daily_price_observation",
        schema="system",
    )
    op.drop_index(
        "ix_bulk_unmatched_provider_symbol",
        table_name="bulk_unmatched_daily_price_observation",
        schema="system",
    )
    op.drop_index(
        "ix_bulk_unmatched_date_status",
        table_name="bulk_unmatched_daily_price_observation",
        schema="system",
    )
    op.drop_table("bulk_unmatched_daily_price_observation", schema="system")
