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
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.rows)


def _mysql_sql(statement: Any) -> str:
    compiled = statement.compile(
        dialect=mysql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    return " ".join(str(compiled).split())


def test_instrument_id_query_deduplicates_sorts_and_avoids_ticker_resolution() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from="2024-01-01",
        date_to="2025-12-31",
    )

    statement = reader.build_daily_prices_by_instrument_ids_query(instrument_ids=[7, 2, 7])
    sql = _mysql_sql(statement)

    assert statement.is_select
    assert "instrument.instrument_id IN (2, 7)" in sql
    assert "instrument_identifier_history" not in sql
    assert "instrument.symbol IN" not in sql
    assert "instrument.provider_symbol IN" not in sql
    assert "stock_daily_price" in sql
    assert "adjusted_close AS analysis_close" in sql
    assert "trade_date BETWEEN '2024-01-01' AND '2025-12-31'" in sql
    assert sql.endswith(
        "ORDER BY us_share.instrument.instrument_id, us_share.stock_daily_price.trade_date"
    )


def test_instrument_id_query_can_use_raw_close_and_non_stock_table() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from=date(2024, 1, 1),
        date_to=date(2025, 12, 31),
    )

    statement = reader.build_daily_prices_by_instrument_ids_query(
        instrument_ids=[11],
        asset_type="index",
        adjusted=False,
    )
    sql = _mysql_sql(statement)

    assert "index_daily_price" in sql
    assert "index_daily_price.close AS analysis_close" in sql
    assert "instrument.asset_type = 'index'" in sql


def test_empty_instrument_ids_return_without_querying() -> None:
    connection = FakeConnection()
    reader = DailyPriceReader(connection)

    rows = reader.get_daily_prices_by_instrument_ids(instrument_ids=[])

    assert rows == []
    assert connection.statements == []


def test_empty_instrument_id_builder_cannot_scan_all_rows() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from="2024-01-01",
        date_to="2025-12-31",
    )

    sql = _mysql_sql(reader.build_daily_prices_by_instrument_ids_query(instrument_ids=[]))

    assert "WHERE" in sql
    assert "false = 1" in sql


def test_instrument_id_reader_executes_select_and_returns_dict_rows() -> None:
    expected_rows = [
        {
            "instrument_id": 2,
            "price_symbol": "OLD",
            "trade_date": date(2024, 3, 15),
        }
    ]
    connection = FakeConnection(expected_rows)
    reader = DailyPriceReader(
        connection,
        date_from="2024-01-01",
        date_to="2025-12-31",
    )

    rows = reader.get_daily_prices_by_instrument_ids(instrument_ids=[2])

    assert rows == expected_rows
    assert len(connection.statements) == 1


def test_instrument_id_query_reuses_asset_type_validation() -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from="2024-01-01",
        date_to="2025-12-31",
    )

    with pytest.raises(ValueError, match="stock, etf, index"):
        reader.build_daily_prices_by_instrument_ids_query(
            instrument_ids=[1],
            asset_type="bond",
        )


@pytest.mark.parametrize("instrument_ids", [[0], [-1], [True], ["1"]])
def test_instrument_id_query_rejects_invalid_ids(instrument_ids: list[Any]) -> None:
    reader = DailyPriceReader(
        FakeConnection(),
        date_from="2024-01-01",
        date_to="2025-12-31",
    )

    with pytest.raises(ValueError, match="instrument_ids"):
        reader.build_daily_prices_by_instrument_ids_query(instrument_ids=instrument_ids)
