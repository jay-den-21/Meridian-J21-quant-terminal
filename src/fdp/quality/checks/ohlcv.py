"""OHLCV data quality checks."""

from datetime import date

from sqlalchemy import Select, Table, or_, select

from fdp.storage.tables import stock_daily_price


def invalid_ohlcv_rows(
    *,
    date_from: date,
    date_to: date,
    price_table: Table = stock_daily_price,
) -> Select:
    """Build a query for invalid OHLCV rows.

    Input: inclusive date range and one asset-specific daily price table.
    Output: SQLAlchemy select returning rows that violate basic OHLCV constraints.
    Flow: price table -> non-negative/high-low/open-close constraints -> invalid rows.
    """
    return select(price_table).where(
        price_table.c.trade_date.between(date_from, date_to),
        or_(
            price_table.c.open < 0,
            price_table.c.high < 0,
            price_table.c.low < 0,
            price_table.c.close < 0,
            price_table.c.adjusted_close < 0,
            price_table.c.volume < 0,
            price_table.c.high < price_table.c.low,
            price_table.c.high < price_table.c.open,
            price_table.c.high < price_table.c.close,
            price_table.c.low > price_table.c.open,
            price_table.c.low > price_table.c.close,
        ),
    )
