"""add resumable compact-swap state for high-delete Fund finalization

Revision ID: 0014_fund_compact_swap
Revises: 0013_fund_split_run
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0014_fund_compact_swap"
down_revision: str | None = "0013_fund_split_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fund_daily_price_split_run",
        sa.Column("finalize_strategy", sa.String(length=32), nullable=True),
        schema="system",
    )
    op.add_column(
        "fund_daily_price_split_run",
        sa.Column("rows_compacted", sa.BigInteger(), server_default="0", nullable=False),
        schema="system",
    )
    op.add_column(
        "fund_daily_price_split_run",
        sa.Column("compact_last_source_id", sa.BigInteger(), server_default="0", nullable=False),
        schema="system",
    )
    op.add_column(
        "fund_daily_price_split_run",
        sa.Column("compact_verification_fingerprint", sa.String(length=64), nullable=True),
        schema="system",
    )
    op.add_column(
        "fund_daily_price_split_run",
        sa.Column("compact_verification_details", sa.Text(), nullable=True),
        schema="system",
    )
    op.add_column(
        "fund_daily_price_split_run",
        sa.Column("compact_verified_at", sa.DateTime(), nullable=True),
        schema="system",
    )
    op.add_column(
        "fund_daily_price_split_run",
        sa.Column("swapped_at", sa.DateTime(), nullable=True),
        schema="system",
    )


def downgrade() -> None:
    active = op.get_bind().execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM `system`.fund_daily_price_split_run
            WHERE finalize_strategy IS NOT NULL
               OR rows_compacted != 0
               OR compact_last_source_id != 0
               OR compact_verification_fingerprint IS NOT NULL
               OR compact_verification_details IS NOT NULL
               OR compact_verified_at IS NOT NULL
               OR swapped_at IS NOT NULL
            """
        )
    ).scalar_one()
    if int(active) > 0:
        raise RuntimeError("refusing downgrade while compact-swap evidence exists")
    op.drop_column("fund_daily_price_split_run", "swapped_at", schema="system")
    op.drop_column("fund_daily_price_split_run", "compact_verified_at", schema="system")
    op.drop_column("fund_daily_price_split_run", "compact_verification_details", schema="system")
    op.drop_column("fund_daily_price_split_run", "compact_verification_fingerprint", schema="system")
    op.drop_column("fund_daily_price_split_run", "compact_last_source_id", schema="system")
    op.drop_column("fund_daily_price_split_run", "rows_compacted", schema="system")
    op.drop_column("fund_daily_price_split_run", "finalize_strategy", schema="system")
