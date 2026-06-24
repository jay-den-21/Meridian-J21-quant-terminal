"""Missing data quality checks."""

from datetime import date

from sqlalchemy import Select, Table, and_, distinct, exists, func, literal, select

from fdp.storage.tables import instrument, market_calendar, stock_daily_price


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


def missing_loaded_daily_price_dates(
    *,
    date_from: date,
    date_to: date,
    price_table: Table = stock_daily_price,
) -> Select:
    """Build a query for gaps among instruments already loaded in a price table.

    Input: inclusive date range and one asset-specific daily price table.
    Output: missing trading dates for instruments with at least one row in scope.
    Flow: loaded instruments -> trading calendar -> anti-exists price row -> gaps.
    """
    loaded_instruments = (
        select(distinct(price_table.c.instrument_id).label("instrument_id"))
        .where(price_table.c.trade_date.between(date_from, date_to))
        .subquery("loaded_instruments")
    )
    price_exists = exists(
        select(literal(1)).where(
            price_table.c.instrument_id == loaded_instruments.c.instrument_id,
            price_table.c.trade_date == market_calendar.c.calendar_date,
        )
    )
    return (
        select(
            loaded_instruments.c.instrument_id,
            instrument.c.symbol,
            market_calendar.c.calendar_date.label("trade_date"),
        )
        .select_from(
            loaded_instruments.join(
                instrument,
                instrument.c.instrument_id == loaded_instruments.c.instrument_id,
            ).join(
                market_calendar,
                and_(
                    instrument.c.instrument_id == loaded_instruments.c.instrument_id,
                    market_calendar.c.calendar_date.between(date_from, date_to),
                ),
            )
        )
        .where(
            market_calendar.c.is_trading_day.is_(True),
            ~price_exists,
        )
        .order_by(loaded_instruments.c.instrument_id, market_calendar.c.calendar_date)
    )


def loaded_daily_price_instruments(
    *,
    date_from: date,
    date_to: date,
    price_table: Table = stock_daily_price,
) -> Select:
    """Build a query for instruments with at least one loaded row in scope.

    Input: inclusive date range and one asset-specific daily price table.
    Output: distinct loaded instrument ids and display symbols.
    Flow: price table date range -> group by instrument_id -> loaded instrument scope.
    """
    return (
        select(
            price_table.c.instrument_id,
            func.min(price_table.c.symbol).label("symbol"),
        )
        .where(price_table.c.trade_date.between(date_from, date_to))
        .group_by(price_table.c.instrument_id)
        .order_by(price_table.c.instrument_id)
    )
