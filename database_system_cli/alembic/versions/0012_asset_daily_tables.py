"""adopt canonical asset daily tables and add Fund storage

Revision ID: 0012_asset_daily_tables
Revises: 0011_drop_us_share_snapshots
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0012_asset_daily_tables"
down_revision: str | None = "0011_drop_us_share_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "us_share"
PRICE_COLUMNS = {
    "instrument_id",
    "symbol",
    "provider_symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "currency",
    "source",
    "source_updated_at",
    "created_at",
    "updated_at",
}
INSTRUMENT_VIEW_COLUMNS = (
    "instrument_id",
    "market",
    "symbol",
    "provider",
    "provider_symbol",
    "name",
    "exchange",
    "asset_type",
    "currency",
    "is_active",
    "listed_date",
    "delisted_date",
    "created_at",
    "updated_at",
)


def upgrade() -> None:
    _ensure_daily_price_table("fund", volume_nullable=False)
    _ensure_daily_price_table("forex", volume_nullable=True)
    _ensure_daily_price_table("crypto", volume_nullable=False)
    _create_instrument_view("etf")
    _create_instrument_view("fund")


def downgrade() -> None:
    tables = ("fund_daily_price", "forex_daily_price", "crypto_daily_price")
    non_empty = [table_name for table_name in tables if _table_count(table_name) > 0]
    if non_empty:
        joined = ", ".join(non_empty)
        raise RuntimeError(f"refusing downgrade while canonical daily tables contain data: {joined}")

    op.execute(sa.text(f"DROP VIEW IF EXISTS {SCHEMA}.fund_instrument"))
    _create_instrument_view("etf")
    for asset_type in ("crypto", "forex", "fund"):
        table_name = f"{asset_type}_daily_price"
        if _table_exists(table_name):
            op.drop_table(table_name, schema=SCHEMA)


def _ensure_daily_price_table(asset_type: str, *, volume_nullable: bool) -> None:
    table_name = f"{asset_type}_daily_price"
    if _table_exists(table_name):
        _assert_daily_price_shape(table_name)
        return

    id_column = f"{asset_type}_daily_price_id"
    op.create_table(
        table_name,
        sa.Column(id_column, sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("provider_symbol", sa.String(length=128), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("adjusted_close", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=volume_nullable),
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
        sa.ForeignKeyConstraint(["instrument_id"], [f"{SCHEMA}.instrument.instrument_id"]),
        sa.PrimaryKeyConstraint(id_column),
        sa.UniqueConstraint(
            "instrument_id",
            "trade_date",
            name=f"uq_{asset_type}_daily_price_instrument_date",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        f"ix_{asset_type}_daily_price_symbol_date",
        table_name,
        ["symbol", "trade_date"],
        schema=SCHEMA,
    )
    op.create_index(
        f"ix_{asset_type}_daily_price_trade_date",
        table_name,
        ["trade_date"],
        schema=SCHEMA,
    )


def _assert_daily_price_shape(table_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table_name, schema=SCHEMA)}
    missing = sorted(PRICE_COLUMNS - columns)
    if missing:
        raise RuntimeError(f"{SCHEMA}.{table_name} has incompatible columns; missing {missing}")
    unique_columns = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name, schema=SCHEMA)
    }
    if ("instrument_id", "trade_date") not in unique_columns:
        raise RuntimeError(
            f"{SCHEMA}.{table_name} is missing unique(instrument_id, trade_date)"
        )


def _create_instrument_view(asset_type: str) -> None:
    view_name = f"{asset_type}_instrument"
    columns = ", ".join(INSTRUMENT_VIEW_COLUMNS)
    op.execute(sa.text(f"DROP VIEW IF EXISTS {SCHEMA}.{view_name}"))
    op.execute(
        sa.text(
            f"CREATE VIEW {SCHEMA}.{view_name} AS "
            f"SELECT {columns} FROM {SCHEMA}.instrument "
            f"WHERE asset_type = '{asset_type}'"
        )
    )


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name, schema=SCHEMA)


def _table_count(table_name: str) -> int:
    if not _table_exists(table_name):
        return 0
    return int(
        op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {SCHEMA}.{table_name}")).scalar_one()
    )
