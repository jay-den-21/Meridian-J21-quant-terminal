"""Simplify market calendar for daily US EOD data.

Revision ID: 0004_simplify_market_calendar
Revises: 0003_daily_price_symbols
Create Date: 2026-05-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_simplify_market_calendar"
down_revision: str | None = "0003_daily_price_symbols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_market_calendar_date",
        "market_calendar",
        schema="us_share",
        type_="unique",
    )
    op.drop_column("market_calendar", "market", schema="us_share")
    op.drop_column("market_calendar", "exchange", schema="us_share")
    op.drop_column("market_calendar", "early_close_time", schema="us_share")
    op.drop_column("market_calendar", "timezone", schema="us_share")
    op.create_unique_constraint(
        "uq_market_calendar_date",
        "market_calendar",
        ["calendar_date"],
        schema="us_share",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_market_calendar_date",
        "market_calendar",
        schema="us_share",
        type_="unique",
    )
    op.add_column(
        "market_calendar",
        sa.Column("timezone", sa.String(length=64), server_default="America/New_York", nullable=False),
        schema="us_share",
    )
    op.add_column(
        "market_calendar",
        sa.Column("early_close_time", sa.Time(), nullable=True),
        schema="us_share",
    )
    op.add_column(
        "market_calendar",
        sa.Column("exchange", sa.String(length=64), server_default="US", nullable=False),
        schema="us_share",
    )
    op.add_column(
        "market_calendar",
        sa.Column("market", sa.String(length=16), server_default="US", nullable=False),
        schema="us_share",
    )
    op.create_unique_constraint(
        "uq_market_calendar_date",
        "market_calendar",
        ["market", "exchange", "calendar_date"],
        schema="us_share",
    )
