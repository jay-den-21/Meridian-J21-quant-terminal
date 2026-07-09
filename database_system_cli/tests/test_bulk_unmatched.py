from datetime import date
from decimal import Decimal
from typing import Any

from fdp.bulk_unmatched import (
    classify_bulk_unmatched_observations,
    route_bulk_unmatched_observations,
)
from fdp.storage.tables import bulk_unmatched_daily_price_observation, stock_daily_price


class FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class FakeSelectResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeMappings:
        return FakeMappings(self.rows)


class FakeConnection:
    def __init__(self, select_results: list[list[dict[str, Any]]]) -> None:
        self.select_results = select_results
        self.statements: list[Any] = []

    def execute(self, statement):
        self.statements.append(statement)
        if getattr(statement, "is_select", False):
            return FakeSelectResult(self.select_results.pop(0))
        return object()


def test_classify_bulk_unmatched_uses_strict_provider_symbol_match() -> None:
    connection = FakeConnection(
        [
            [
                {
                    "observation_id": 1,
                    "provider_symbol": "OLD.US",
                    "eodhd_type": "Common Stock",
                },
                {
                    "observation_id": 2,
                    "provider_symbol": "PREF.US",
                    "eodhd_type": "Preferred Stock",
                },
            ],
            [{"instrument_id": 77, "asset_type": "stock"}],
            [],
        ]
    )

    result = classify_bulk_unmatched_observations(
        connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
    )

    assert result.scanned == 2
    assert result.matched == 1
    assert result.non_price_asset == 1
    update_values = [
        statement.compile().params
        for statement in connection.statements
        if getattr(statement, "is_update", False)
    ]
    assert {params["classification_status"] for params in update_values} == {
        "matched",
        "non_price_asset",
    }


def test_route_bulk_unmatched_writes_price_rows_only_when_executed() -> None:
    route_row = {
        "observation_id": 1,
        "trade_date": date(2024, 1, 2),
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10.5"),
        "adjusted_close": Decimal("10.5"),
        "volume": 1000,
        "instrument_id": 77,
        "symbol": "OLD",
        "provider_symbol": "OLD.US",
        "asset_type": "stock",
        "currency": "USD",
    }
    dry_connection = FakeConnection([[route_row]])

    dry_result = route_bulk_unmatched_observations(
        dry_connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        dry_run=True,
    )

    assert dry_result.routeable == 1
    assert dry_result.rows_inserted == 0
    assert all(getattr(statement, "table", None) is not stock_daily_price for statement in dry_connection.statements)

    execute_connection = FakeConnection([[route_row]])
    executed = route_bulk_unmatched_observations(
        execute_connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        dry_run=False,
    )

    assert executed.routeable == 1
    assert executed.rows_inserted == 1
    assert executed.routed == 1
    statement_tables = [getattr(statement, "table", None) for statement in execute_connection.statements]
    assert stock_daily_price in statement_tables
    assert bulk_unmatched_daily_price_observation in statement_tables
