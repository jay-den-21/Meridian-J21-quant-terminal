"""Calendar alignment data quality checks."""

from datetime import date

from sqlalchemy import Select, Table, select

from fdp.storage.tables import market_calendar, stock_daily_price


def price_rows_on_non_trading_days(
    *,
    date_from: date,
    date_to: date,
    price_table: Table = stock_daily_price,
) -> Select:
    """Build a query for price rows whose date is marked non-trading.

    Input: inclusive date range and one asset-specific daily price table.
    Output: SQLAlchemy select returning price rows on non-trading calendar dates.
    Flow: price table -> join market_calendar -> keep is_trading_day = false.
    """
    return (
        select(price_table)
        .join(market_calendar, price_table.c.trade_date == market_calendar.c.calendar_date)
        .where(
            price_table.c.trade_date.between(date_from, date_to),
            market_calendar.c.is_trading_day.is_(False),
        )
        .order_by(price_table.c.trade_date, price_table.c.provider_symbol)
    )
