"""Duplicate data quality checks."""

from datetime import date

from sqlalchemy import Select, Table, func, select

from fdp.storage.tables import stock_daily_price


def duplicate_daily_price_groups(
    *,
    date_from: date,
    date_to: date,
    price_table: Table = stock_daily_price,
) -> Select:
    """Build a query for duplicate `instrument_id + trade_date` daily rows.

    Input: inclusive date range and one asset-specific daily price table.
    Output: SQLAlchemy select returning duplicate groups and counts.
    Flow: price table -> group by identity key -> keep groups with count > 1.
    """
    return (
        select(
            price_table.c.instrument_id,
            price_table.c.trade_date,
            func.count().label("row_count"),
        )
        .where(price_table.c.trade_date.between(date_from, date_to))
        .group_by(price_table.c.instrument_id, price_table.c.trade_date)
        .having(func.count() > 1)
    )
