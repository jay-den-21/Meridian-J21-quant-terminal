from datetime import date
from typing import Any

import pytest
from sqlalchemy.dialects import mysql

from fdp.research import DailyPriceReader


class FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeMappings:
        return FakeMappings(self.rows)


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.rows = [{"symbol": "AAPL", "trade_date": date(2023, 1, 3)}]

    def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.rows)


def test_daily_price_reader_uses_reader_default_dates() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from=date(2023, 1, 1),
        date_to=date(2023, 1, 31),
    )

    assert reader.resolve_date_range() == (date(2023, 1, 1), date(2023, 1, 31))


def test_daily_price_reader_method_dates_override_reader_defaults() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from=date(2020, 1, 1),
        date_to=date(2020, 1, 31),
    )

    resolved = reader.resolve_date_range(date_from="2023-01-01", date_to="2023-01-31")

    assert resolved == (date(2023, 1, 1), date(2023, 1, 31))


def test_daily_price_reader_rejects_partial_method_date_override() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from=date(2020, 1, 1),
        date_to=date(2020, 1, 31),
    )

    with pytest.raises(ValueError, match="provided together"):
        reader.resolve_date_range(date_from="2023-01-01")


def test_daily_price_reader_requires_dates_when_no_defaults_exist() -> None:
    reader = DailyPriceReader(FakeConnection())

    with pytest.raises(ValueError, match="required"):
        reader.resolve_date_range()


def test_daily_price_reader_builds_stock_query_with_identifier_history() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from=date(2023, 1, 1),
        date_to=date(2023, 1, 31),
    )

    statement = reader.build_daily_prices_query(symbols=["META"], asset_type="stock")
    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "stock_daily_price" in sql
    assert "instrument_identifier_history" in sql
    assert "adjusted_close AS analysis_close" in sql
    assert "instrument.is_active" in sql
    assert "instrument.delisted_date" in sql
    assert "asset_type = %s" in sql


def test_daily_price_reader_can_use_raw_close_as_analysis_close() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from=date(2023, 1, 1),
        date_to=date(2023, 1, 31),
    )

    statement = reader.build_daily_prices_query(
        symbols=["AAPL"],
        asset_type="stock",
        adjusted=False,
    )
    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "stock_daily_price.close AS analysis_close" in sql


def test_daily_price_reader_routes_fund_queries_to_fund_table() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from=date(2023, 1, 1),
        date_to=date(2023, 1, 31),
    )

    statement = reader.build_daily_prices_query(symbols=["VFINX"], asset_type="fund")

    assert "fund_daily_price" in str(statement.compile(dialect=mysql.dialect()))


def test_daily_price_reader_rejects_unsupported_asset_type() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from=date(2023, 1, 1),
        date_to=date(2023, 1, 31),
    )

    with pytest.raises(ValueError, match="stock, etf, fund, index, forex, crypto"):
        reader.build_daily_prices_query(symbols=["AAPL"], asset_type="bond")


def test_daily_price_reader_executes_query_and_returns_dict_rows() -> None:
    connection = FakeConnection()
    reader = DailyPriceReader(
        connection,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 1, 31),
    )

    rows = reader.get_daily_prices(symbols=["AAPL"])

    assert rows == [{"symbol": "AAPL", "trade_date": date(2023, 1, 3)}]
    assert connection.statements
