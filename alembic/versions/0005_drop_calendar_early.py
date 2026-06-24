"""Drop early-close flag from daily market calendar.

Revision ID: 0005_drop_calendar_early
Revises: 0004_simplify_market_calendar
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0005_drop_calendar_early"
down_revision: str | None = "0004_simplify_market_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = _market_calendar_columns()
    if "is_early_close" in columns:
        op.drop_column("market_calendar", "is_early_close", schema="us_share")


def downgrade() -> None:
    columns = _market_calendar_columns()
    if "is_early_close" not in columns:
        op.add_column(
            "market_calendar",
            sa.Column("is_early_close", sa.Boolean(), server_default=sa.text("0"), nullable=False),
            schema="us_share",
        )


def _market_calendar_columns() -> set[str]:
    bind = op.get_bind()
    return {
        column["name"]
        for column in inspect(bind).get_columns("market_calendar", schema="us_share")
    }
