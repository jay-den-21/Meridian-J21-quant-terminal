"""adopt canonical dividend and split corporate actions

Revision ID: 0017_corporate_actions
Revises: 0016_guided_bulk_reconcile
Create Date: 2026-07-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0017_corporate_actions"
down_revision: str | None = "0016_guided_bulk_reconcile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "us_share"
TABLE = "corporate_action"
UNIQUE_NAME = "uq_corporate_action_identity"
UNIQUE_COLUMNS = ["instrument_id", "action_type", "action_date", "source"]
INDEXES = {
    "ix_corporate_action_symbol_date": ["symbol", "action_date"],
    "ix_corporate_action_provider_symbol_date": ["provider_symbol", "action_date"],
}
REQUIRED_COLUMNS = {
    "corporate_action_id",
    "instrument_id",
    "symbol",
    "provider_symbol",
    "action_type",
    "action_date",
    "declaration_date",
    "record_date",
    "payment_date",
    "period",
    "cash_amount",
    "unadjusted_cash_amount",
    "currency",
    "split_ratio",
    "split_numerator",
    "split_denominator",
    "source",
    "created_at",
    "updated_at",
}


def _inspector(bind: sa.Connection) -> sa.Inspector:
    return sa.inspect(bind)


def _columns(bind: sa.Connection) -> set[str]:
    return {column["name"] for column in _inspector(bind).get_columns(TABLE, schema=SCHEMA)}


def _indexes(bind: sa.Connection) -> dict[str, list[str]]:
    return {
        index["name"]: list(index["column_names"])
        for index in _inspector(bind).get_indexes(TABLE, schema=SCHEMA)
    }


def _unique_constraints(bind: sa.Connection) -> dict[str, list[str]]:
    return {
        constraint["name"]: list(constraint["column_names"])
        for constraint in _inspector(bind).get_unique_constraints(TABLE, schema=SCHEMA)
    }


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("corporate_action_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("provider_symbol", sa.String(length=128), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("action_date", sa.Date(), nullable=False),
        sa.Column("declaration_date", sa.Date(), nullable=True),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("period", sa.String(length=32), nullable=True),
        sa.Column("cash_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("unadjusted_cash_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("split_ratio", sa.String(length=64), nullable=True),
        sa.Column("split_numerator", sa.Numeric(20, 8), nullable=True),
        sa.Column("split_denominator", sa.Numeric(20, 8), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
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
        sa.PrimaryKeyConstraint("corporate_action_id"),
        sa.UniqueConstraint(*UNIQUE_COLUMNS, name=UNIQUE_NAME),
        schema=SCHEMA,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _inspector(bind).has_table(TABLE, schema=SCHEMA):
        _create_table()
    else:
        missing = REQUIRED_COLUMNS - _columns(bind)
        if missing:
            raise RuntimeError(
                "refusing to adopt incomplete corporate_action table: "
                f"missing {sorted(missing)}"
            )

    unique_constraints = _unique_constraints(bind)
    existing_unique = unique_constraints.get(UNIQUE_NAME)
    if existing_unique is not None and existing_unique != UNIQUE_COLUMNS:
        raise RuntimeError(
            f"refusing incompatible {UNIQUE_NAME}: "
            f"expected={UNIQUE_COLUMNS} actual={existing_unique}"
        )
    if existing_unique is None:
        op.create_unique_constraint(
            UNIQUE_NAME,
            TABLE,
            UNIQUE_COLUMNS,
            schema=SCHEMA,
        )

    existing_indexes = _indexes(bind)
    for index_name, columns in INDEXES.items():
        actual = existing_indexes.get(index_name)
        if actual is not None and actual != columns:
            raise RuntimeError(
                f"refusing incompatible {index_name}: expected={columns} actual={actual}"
            )
        if actual is None:
            op.create_index(index_name, TABLE, columns, schema=SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if not _inspector(bind).has_table(TABLE, schema=SCHEMA):
        return
    row_count = int(
        bind.execute(sa.text("SELECT COUNT(*) FROM us_share.corporate_action")).scalar_one()
    )
    if row_count:
        raise RuntimeError("refusing downgrade while corporate action rows exist")
    op.drop_table(TABLE, schema=SCHEMA)
