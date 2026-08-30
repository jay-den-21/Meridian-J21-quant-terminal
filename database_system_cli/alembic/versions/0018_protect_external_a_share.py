"""Protect the externally owned A-share schema during downgrade.

Revision ID: 0018_protect_external_a_share
Revises: 0017_corporate_actions
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0018_protect_external_a_share"
down_revision: str | None = "0017_corporate_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

A_SHARE_SCHEMA = "a_share"

_EXTERNAL_OBJECT_COUNT = sa.text(
    """
    SELECT
        (SELECT COUNT(*)
         FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = :schema_name)
      + (SELECT COUNT(*)
         FROM information_schema.ROUTINES
         WHERE ROUTINE_SCHEMA = :schema_name)
      + (SELECT COUNT(*)
         FROM information_schema.EVENTS
         WHERE EVENT_SCHEMA = :schema_name)
    """
)


def upgrade() -> None:
    """Record the external-ownership boundary without creating A-share DDL."""


def downgrade() -> None:
    """Stop before revision 0001 can drop an externally populated schema."""

    bind = op.get_bind()
    object_count = int(
        bind.execute(
            _EXTERNAL_OBJECT_COUNT,
            {"schema_name": A_SHARE_SCHEMA},
        ).scalar_one()
    )
    if object_count:
        raise RuntimeError("refusing downgrade through externally owned nonempty a_share schema")
