"""Missing data quality checks."""

from datetime import date

from sqlalchemy import Select, Table, exists, literal, select

from fdp.storage.tables import market_calendar, stock_daily_price


def missing_daily_price_dates(
    *,
    instrument_id: int,
    date_from: date,
    date_to: date,
    price_table: Table = stock_daily_price,
) -> Select:
    """Build a query for missing daily rows on trading days.

    Input: instrument id, inclusive date range, and one asset-specific price table.
    Output: SQLAlchemy select returning missing trading dates.
    Flow: market_calendar trading days -> anti-exists price table -> missing dates.
    """
    price_exists = exists(
        select(literal(1)).where(
            price_table.c.instrument_id == instrument_id,
            price_table.c.trade_date == market_calendar.c.calendar_date,
        )
    )
    return (
        select(market_calendar.c.calendar_date)
        .where(
            market_calendar.c.calendar_date.between(date_from, date_to),
            market_calendar.c.is_trading_day.is_(True),
            ~price_exists,
        )
        .order_by(market_calendar.c.calendar_date)
    )
