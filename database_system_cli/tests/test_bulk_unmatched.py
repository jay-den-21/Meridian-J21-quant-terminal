from datetime import date
from decimal import Decimal
from typing import Any

from fdp.bulk_unmatched import (
    classify_bulk_unmatched_observations,
    route_bulk_unmatched_observations,
)
from fdp.sources.eodhd.identity import InstrumentIdentityResolution
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


class FakeClassifierResolver:
    def resolve(self, *, provider_symbol, trade_date, eodhd_type):
        if provider_symbol == "OLD.US":
            return InstrumentIdentityResolution(
                instrument={"instrument_id": 77, "asset_type": "stock"},
                matched_by="identifier_history",
                reason=None,
            )
        if provider_symbol == "VFINX.US":
            return InstrumentIdentityResolution(
                instrument={"instrument_id": 88, "asset_type": "fund"},
                matched_by="current_provider_symbol",
                reason=None,
            )
        return InstrumentIdentityResolution(
            instrument=None,
            matched_by=None,
            reason="unsupported_eodhd_type",
        )


def test_classify_bulk_unmatched_uses_strict_provider_symbol_match() -> None:
    connection = FakeConnection(
        [
            [
                {
                    "observation_id": 1,
                    "provider_symbol": "OLD.US",
                    "trade_date": date(2024, 1, 2),
                    "eodhd_type": "Common Stock",
                },
                {
                    "observation_id": 2,
                    "provider_symbol": "PREF.US",
                    "trade_date": date(2024, 1, 2),
                    "eodhd_type": "Preferred Stock",
                },
            ]
        ]
    )

    result = classify_bulk_unmatched_observations(
        connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        identity_resolver=FakeClassifierResolver(),
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


def test_classify_bulk_unmatched_preserves_dated_identity_ambiguity() -> None:
    class AmbiguousResolver:
        def resolve(self, *, provider_symbol, trade_date, eodhd_type):
            return InstrumentIdentityResolution(
                instrument=None,
                matched_by=None,
                reason="ambiguous_identifier_history",
                candidate_instrument_ids=(10, 20),
            )

    connection = FakeConnection(
        [[{
            "observation_id": 9,
            "provider_symbol": "AMB.US",
            "trade_date": date(2014, 8, 18),
            "eodhd_type": None,
        }]]
    )

    result = classify_bulk_unmatched_observations(
        connection,
        date_from=date(2014, 8, 18),
        date_to=date(2014, 8, 18),
        identity_resolver=AmbiguousResolver(),
    )

    assert result.scanned == 1
    assert result.ambiguous == 1
    assert result.unknown == 0
    update_values = next(
        statement.compile().params
        for statement in connection.statements
        if getattr(statement, "is_update", False)
    )
    assert update_values["classification_status"] == "ambiguous"
    assert update_values["reason"] == (
        "ambiguous_identifier_history;candidate_instrument_ids=10,20"
    )


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
        "observed_symbol": "OLD",
        "observed_provider_symbol": "OLD.US",
        "classification_reason": "identifier_history_match",
        "instrument_id": 77,
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


def test_route_bulk_unmatched_prefers_dated_observation_and_preserves_source_symbol() -> None:
    rows = [
        {
            "observation_id": 1,
            "trade_date": date(2014, 8, 18),
            "open": Decimal("10"),
            "high": Decimal("11"),
            "low": Decimal("9"),
            "close": Decimal("10"),
            "adjusted_close": Decimal("10"),
            "volume": 100,
            "observed_symbol": "OLD",
            "observed_provider_symbol": "OLD.US",
            "classification_reason": "identifier_history_match",
            "instrument_id": 77,
            "asset_type": "stock",
            "currency": "USD",
        },
        {
            "observation_id": 2,
            "trade_date": date(2014, 8, 18),
            "open": Decimal("90"),
            "high": Decimal("100"),
            "low": Decimal("80"),
            "close": Decimal("99"),
            "adjusted_close": Decimal("99"),
            "volume": 999,
            "observed_symbol": "NEW",
            "observed_provider_symbol": "NEW.US",
            "classification_reason": "current_provider_symbol_match",
            "instrument_id": 77,
            "asset_type": "stock",
            "currency": "USD",
        },
    ]
    connection = FakeConnection([rows])

    result = route_bulk_unmatched_observations(
        connection,
        date_from=date(2014, 8, 18),
        date_to=date(2014, 8, 18),
        dry_run=False,
    )

    assert result.routeable == 1
    assert result.rows_inserted == 1
    assert result.rows_rejected == 1
    assert result.routed == 1
    price_statement = next(
        statement
        for statement in connection.statements
        if getattr(statement, "table", None) is stock_daily_price
    )
    values = price_statement.compile().params.values()
    assert "OLD.US" in values
    assert "NEW.US" not in values
    assert any(
        statement.compile().params.get("classification_status") == "shadowed"
        for statement in connection.statements
        if getattr(statement, "is_update", False)
    )


def test_fund_bulk_type_is_routeable_when_instrument_exists() -> None:
    connection = FakeConnection(
        [
            [
                {
                    "observation_id": 2,
                    "provider_symbol": "VFINX.US",
                    "trade_date": date(2024, 1, 2),
                    "eodhd_type": "Mutual Fund",
                }
            ]
        ]
    )

    result = classify_bulk_unmatched_observations(
        connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        identity_resolver=FakeClassifierResolver(),
    )

    assert result.matched == 1
    assert result.non_price_asset == 0
