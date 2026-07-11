"""add durable state for the operator-controlled ETF/Fund price split

Revision ID: 0013_fund_daily_price_split_run
Revises: 0012_canonical_asset_daily_tables
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013_fund_daily_price_split_run"
down_revision: str | None = "0012_canonical_asset_daily_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fund_daily_price_split_run",
        sa.Column("fund_split_run_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_total_before", sa.BigInteger(), nullable=False),
        sa.Column("source_fund_rows", sa.BigInteger(), nullable=False),
        sa.Column("target_rows_before", sa.BigInteger(), nullable=False),
        sa.Column("rows_copied", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("rows_deleted", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("copy_last_source_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("delete_last_source_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("backup_path", sa.String(length=1024), nullable=False),
        sa.Column("backup_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("backup_sha256", sa.String(length=64), nullable=False),
        sa.Column("verification_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("verification_details", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("fund_split_run_id"),
        schema="system",
    )
    op.create_index(
        "ix_fund_daily_price_split_status",
        "fund_daily_price_split_run",
        ["status"],
        schema="system",
    )


def downgrade() -> None:
    count = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM `system`.fund_daily_price_split_run")
    ).scalar_one()
    if int(count) > 0:
        raise RuntimeError("refusing downgrade while fund daily-price split runs exist")
    op.drop_index(
        "ix_fund_daily_price_split_status",
        table_name="fund_daily_price_split_run",
        schema="system",
    )
    op.drop_table("fund_daily_price_split_run", schema="system")
