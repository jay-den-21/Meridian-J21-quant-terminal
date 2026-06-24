from datetime import date

from sqlalchemy.dialects import mysql

from fdp.quality.checks.calendar_alignment import price_rows_on_non_trading_days
from fdp.quality.checks.duplicate import duplicate_daily_price_groups
from fdp.quality.checks.missing import missing_daily_price_dates
from fdp.quality.checks.ohlcv import invalid_ohlcv_rows
from fdp.storage.tables import etf_daily_price, index_daily_price


def test_duplicate_daily_price_groups_builds_identity_group_query() -> None:
    statement = duplicate_daily_price_groups(
        date_from=date(2023, 1, 1),
        date_to=date(2025, 12, 31),
    )

    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "stock_daily_price" in sql
    assert "instrument_id" in sql
    assert "trade_date" in sql
    assert "HAVING count(*) > %s" in sql


def test_missing_daily_price_dates_uses_market_calendar() -> None:
    statement = missing_daily_price_dates(
        instrument_id=1,
        date_from=date(2023, 1, 1),
        date_to=date(2025, 12, 31),
    )

    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "market_calendar" in sql
    assert "stock_daily_price" in sql
    assert "is_trading_day IS true" in sql
    assert "NOT (EXISTS" in sql


def test_invalid_ohlcv_rows_builds_basic_price_constraints() -> None:
    statement = invalid_ohlcv_rows(
        date_from=date(2023, 1, 1),
        date_to=date(2025, 12, 31),
    )

    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "stock_daily_price" in sql
    assert "high < us_share.stock_daily_price.low" in sql
    assert "volume < %s" in sql


def test_quality_checks_can_target_other_daily_price_tables() -> None:
    statement = duplicate_daily_price_groups(
        date_from=date(2023, 1, 1),
        date_to=date(2025, 12, 31),
        price_table=etf_daily_price,
    )

    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "etf_daily_price" in sql


def test_price_rows_on_non_trading_days_joins_market_calendar() -> None:
    statement = price_rows_on_non_trading_days(
        date_from=date(2023, 1, 1),
        date_to=date(2025, 12, 31),
        price_table=index_daily_price,
    )

    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "index_daily_price" in sql
    assert "market_calendar" in sql
    assert "is_trading_day IS false" in sql
