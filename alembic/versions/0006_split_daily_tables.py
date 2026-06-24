"""Split daily price storage by asset type.

Revision ID: 0006_split_daily_tables
Revises: 0005_drop_calendar_early
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_split_daily_tables"
down_revision: str | None = "0005_drop_calendar_early"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICE_COLUMNS = (
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
)

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
    _create_daily_price_table(
        "stock_daily_price",
        "stock_daily_price_id",
        "uq_stock_daily_price_instrument_date",
        "ix_stock_daily_price_symbol_date",
        "ix_stock_daily_price_trade_date",
    )
    _create_daily_price_table(
        "etf_daily_price",
        "etf_daily_price_id",
        "uq_etf_daily_price_instrument_date",
        "ix_etf_daily_price_symbol_date",
        "ix_etf_daily_price_trade_date",
    )
    _create_daily_price_table(
        "index_daily_price",
        "index_daily_price_id",
        "uq_index_daily_price_instrument_date",
        "ix_index_daily_price_symbol_date",
        "ix_index_daily_price_trade_date",
    )

    _copy_legacy_daily_price("stock_daily_price", "stock")
    _copy_legacy_daily_price("etf_daily_price", "etf")
    _copy_legacy_daily_price("index_daily_price", "index")

    _create_instrument_view("stock_instrument", "stock")
    _create_instrument_view("etf_instrument", "etf")
    _create_instrument_view("index_instrument", "index")


def downgrade() -> None:
    for view_name in ("index_instrument", "etf_instrument", "stock_instrument"):
        op.execute(sa.text(f"DROP VIEW IF EXISTS us_share.{view_name}"))

    _drop_daily_price_table(
        "index_daily_price",
        "ix_index_daily_price_symbol_date",
        "ix_index_daily_price_trade_date",
    )
    _drop_daily_price_table(
        "etf_daily_price",
        "ix_etf_daily_price_symbol_date",
        "ix_etf_daily_price_trade_date",
    )
    _drop_daily_price_table(
        "stock_daily_price",
        "ix_stock_daily_price_symbol_date",
        "ix_stock_daily_price_trade_date",
    )


def _create_daily_price_table(
    table_name: str,
    id_column: str,
    unique_name: str,
    symbol_index_name: str,
    trade_date_index_name: str,
) -> None:
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
        sa.Column("volume", sa.BigInteger(), nullable=False),
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
        sa.ForeignKeyConstraint(["instrument_id"], ["us_share.instrument.instrument_id"]),
        sa.PrimaryKeyConstraint(id_column),
        sa.UniqueConstraint("instrument_id", "trade_date", name=unique_name),
        schema="us_share",
    )
    op.create_index(
        symbol_index_name,
        table_name,
        ["symbol", "trade_date"],
        unique=False,
        schema="us_share",
    )
    op.create_index(
        trade_date_index_name,
        table_name,
        ["trade_date"],
        unique=False,
        schema="us_share",
    )


def _drop_daily_price_table(
    table_name: str,
    symbol_index_name: str,
    trade_date_index_name: str,
) -> None:
    op.drop_index(trade_date_index_name, table_name=table_name, schema="us_share")
    op.drop_index(symbol_index_name, table_name=table_name, schema="us_share")
    op.drop_table(table_name, schema="us_share")


def _copy_legacy_daily_price(table_name: str, asset_type: str) -> None:
    column_sql = ", ".join(PRICE_COLUMNS)
    select_sql = ", ".join(f"dp.{column}" for column in PRICE_COLUMNS)
    op.execute(
        sa.text(
            f"""
            INSERT IGNORE INTO us_share.{table_name} ({column_sql})
            SELECT {select_sql}
            FROM us_share.daily_price AS dp
            JOIN us_share.instrument AS i
              ON i.instrument_id = dp.instrument_id
            WHERE i.asset_type = '{asset_type}'
            """
        )
    )


def _create_instrument_view(view_name: str, asset_type: str) -> None:
    column_sql = ", ".join(INSTRUMENT_VIEW_COLUMNS)
    op.execute(sa.text(f"DROP VIEW IF EXISTS us_share.{view_name}"))
    op.execute(
        sa.text(
            f"""
            CREATE VIEW us_share.{view_name} AS
            SELECT {column_sql}
            FROM us_share.instrument
            WHERE asset_type = '{asset_type}'
            """
        )
    )
