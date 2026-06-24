"""Add display symbols to daily price.

Revision ID: 0003_daily_price_symbols
Revises: 0002_identifier_history
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_daily_price_symbols"
down_revision: str | None = "0002_identifier_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_price",
        sa.Column("symbol", sa.String(length=64), nullable=False),
        schema="us_share",
    )
    op.add_column(
        "daily_price",
        sa.Column("provider_symbol", sa.String(length=128), nullable=False),
        schema="us_share",
    )
    op.create_index(
        "ix_daily_price_symbol_date",
        "daily_price",
        ["symbol", "trade_date"],
        unique=False,
        schema="us_share",
    )


def downgrade() -> None:
    op.drop_index("ix_daily_price_symbol_date", table_name="daily_price", schema="us_share")
    op.drop_column("daily_price", "provider_symbol", schema="us_share")
    op.drop_column("daily_price", "symbol", schema="us_share")

