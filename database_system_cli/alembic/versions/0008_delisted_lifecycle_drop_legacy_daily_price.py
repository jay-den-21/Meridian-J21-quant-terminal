"""add delisted lifecycle table and drop legacy daily_price

Revision ID: 0008_delisted_lifecycle
Revises: 0007_quarantine_workflow
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa


revision: str = "0008_delisted_lifecycle"
down_revision: str | None = "0007_quarantine_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instrument_lifecycle_event",
        sa.Column("lifecycle_event_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("provider_symbol", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["instrument_id"], ["us_share.instrument.instrument_id"]),
        sa.PrimaryKeyConstraint("lifecycle_event_id"),
        sa.UniqueConstraint("source", "event_key", name="uq_lifecycle_event_source_key"),
        schema="us_share",
    )
    op.create_index(
        "ix_lifecycle_event_provider_symbol",
        "instrument_lifecycle_event",
        ["provider_symbol"],
        schema="us_share",
    )
    op.create_index(
        "ix_lifecycle_event_type_date",
        "instrument_lifecycle_event",
        ["event_type", "event_date"],
        schema="us_share",
    )

    op.drop_index("ix_daily_price_symbol_date", table_name="daily_price", schema="us_share")
    op.drop_index("ix_daily_price_trade_date", table_name="daily_price", schema="us_share")
    op.drop_table("daily_price", schema="us_share")


def downgrade() -> None:
    op.create_table(
        "daily_price",
        sa.Column("daily_price_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("provider_symbol", sa.String(length=128), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(20, 6), nullable=False),
        sa.Column("high", sa.Numeric(20, 6), nullable=False),
        sa.Column("low", sa.Numeric(20, 6), nullable=False),
        sa.Column("close", sa.Numeric(20, 6), nullable=False),
        sa.Column("adjusted_close", sa.Numeric(20, 6), nullable=False),
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
        sa.ForeignKeyConstraint(["instrument_id"], ["us_share.instrument.instrument_id"]),
        sa.PrimaryKeyConstraint("daily_price_id"),
        sa.UniqueConstraint("instrument_id", "trade_date", name="uq_daily_price_instrument_date"),
        schema="us_share",
    )
    op.create_index(
        "ix_daily_price_symbol_date",
        "daily_price",
        ["symbol", "trade_date"],
        schema="us_share",
    )
    op.create_index("ix_daily_price_trade_date", "daily_price", ["trade_date"], schema="us_share")

    op.drop_index(
        "ix_lifecycle_event_type_date",
        table_name="instrument_lifecycle_event",
        schema="us_share",
    )
    op.drop_index(
        "ix_lifecycle_event_provider_symbol",
        table_name="instrument_lifecycle_event",
        schema="us_share",
    )
    op.drop_table("instrument_lifecycle_event", schema="us_share")
