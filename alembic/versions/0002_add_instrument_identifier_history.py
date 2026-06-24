"""Add instrument identifier history.

Revision ID: 0002_identifier_history
Revises: 0001_initial_schema
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_identifier_history"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instrument_identifier_history",
        sa.Column("identifier_history_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("id_type", sa.String(length=64), nullable=False),
        sa.Column("id_value", sa.String(length=128), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
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
        sa.PrimaryKeyConstraint("identifier_history_id"),
        sa.UniqueConstraint(
            "instrument_id",
            "id_type",
            "id_value",
            "valid_from",
            "source",
            name="uq_identifier_history_identity",
        ),
        schema="us_share",
    )
    op.create_index(
        "ix_identifier_history_value",
        "instrument_identifier_history",
        ["id_type", "id_value"],
        unique=False,
        schema="us_share",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_identifier_history_value",
        table_name="instrument_identifier_history",
        schema="us_share",
    )
    op.drop_table("instrument_identifier_history", schema="us_share")

