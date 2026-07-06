"""add quarantine workflow tables

Revision ID: 0007_quarantine_workflow
Revises: 0006_split_daily_tables
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa


revision: str = "0007_quarantine_workflow"
down_revision: str | None = "0006_split_daily_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quarantine_plan",
        sa.Column("quarantine_plan_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("issue_id", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("target_schema", sa.String(length=64), nullable=False),
        sa.Column("target_table", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=True),
        sa.Column("provider_symbol", sa.String(length=128), nullable=True),
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
        sa.Column("row_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("result_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["issue_id"], ["system.data_quality_issue.issue_id"]),
        sa.PrimaryKeyConstraint("quarantine_plan_id"),
        sa.UniqueConstraint("issue_id", "action_type", name="uq_quarantine_plan_issue_action"),
        schema="system",
    )
    op.create_index(
        "ix_quarantine_plan_status",
        "quarantine_plan",
        ["status"],
        schema="system",
    )
    op.create_table(
        "quarantined_daily_price_row",
        sa.Column("quarantined_row_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("quarantine_plan_id", sa.BigInteger(), nullable=False),
        sa.Column("issue_id", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("target_schema", sa.String(length=64), nullable=False),
        sa.Column("target_table", sa.String(length=64), nullable=False),
        sa.Column("source_primary_key", sa.BigInteger(), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=True),
        sa.Column("provider_symbol", sa.String(length=128), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("quarantine_reason", sa.String(length=128), nullable=False),
        sa.Column("row_payload", sa.Text(), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["system.data_quality_issue.issue_id"]),
        sa.ForeignKeyConstraint(
            ["quarantine_plan_id"],
            ["system.quarantine_plan.quarantine_plan_id"],
        ),
        sa.PrimaryKeyConstraint("quarantined_row_id"),
        schema="system",
    )
    op.create_index(
        "ix_quarantined_daily_price_row_plan",
        "quarantined_daily_price_row",
        ["quarantine_plan_id"],
        schema="system",
    )
    op.create_index(
        "ix_quarantined_daily_price_row_source",
        "quarantined_daily_price_row",
        ["target_table", "instrument_id", "trade_date"],
        schema="system",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quarantined_daily_price_row_source",
        table_name="quarantined_daily_price_row",
        schema="system",
    )
    op.drop_index(
        "ix_quarantined_daily_price_row_plan",
        table_name="quarantined_daily_price_row",
        schema="system",
    )
    op.drop_table("quarantined_daily_price_row", schema="system")
    op.drop_index("ix_quarantine_plan_status", table_name="quarantine_plan", schema="system")
    op.drop_table("quarantine_plan", schema="system")
