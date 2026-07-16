from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.dialects import mysql

from fdp.bulk_unmatched import (
    _canonical_overwrite_decision,
    _route_identity_resolution,
    classify_bulk_unmatched_batch,
    classify_bulk_unmatched_observations,
    inspect_bulk_unmatched_classify_snapshot,
    route_bulk_unmatched_observations,
    validate_classification_statuses,
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


class BatchExecution:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class BatchConnection(FakeConnection):
    def __init__(self, select_results: list[list[dict[str, Any]]]) -> None:
        super().__init__(select_results)
        self.executemany_parameters: list[dict[str, object]] | None = None

    def execute(self, statement, parameters=None):
        self.statements.append(statement)
        if getattr(statement, "is_select", False):
            return FakeSelectResult(self.select_results.pop(0))
        if parameters is not None:
            self.executemany_parameters = parameters
            return BatchExecution(len(parameters))
        return BatchExecution(1)


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


def test_classifier_status_allowlist_rejects_route_and_terminal_states() -> None:
    assert validate_classification_statuses(
        ["unknown", "unresolved", "unknown"]
    ) == ("unresolved", "unknown")

    with pytest.raises(ValueError, match="cannot be refreshed: routed"):
        validate_classification_statuses(["routed"])


def test_classify_snapshot_freezes_counts_and_max_ids_by_status() -> None:
    connection = FakeConnection(
        [[
            {
                "classification_status": "unresolved",
                "row_count": 8,
                "snapshot_max_observation_id": 90,
            },
            {
                "classification_status": "unknown",
                "row_count": 3,
                "snapshot_max_observation_id": 99,
            },
        ]]
    )

    snapshot = inspect_bulk_unmatched_classify_snapshot(
        connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 3),
        statuses=["unresolved", "needs_instrument", "unknown"],
    )

    assert snapshot.total == 11
    assert snapshot.status_counts == {
        "unresolved": 8,
        "needs_instrument": 0,
        "unknown": 3,
    }
    assert snapshot.snapshot_max_by_status["needs_instrument"] == 0


def test_classify_batch_marks_same_run_and_uses_one_executemany() -> None:
    connection = BatchConnection(
        [[
            {
                "observation_id": 10,
                "provider_symbol": "OLD.US",
                "trade_date": date(2024, 1, 2),
                "eodhd_type": "Common Stock",
            },
            {
                "observation_id": 11,
                "provider_symbol": "MISSING.US",
                "trade_date": date(2024, 1, 2),
                "eodhd_type": "Common Stock",
            },
        ]]
    )

    result = classify_bulk_unmatched_batch(
        connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        source_status="unresolved",
        snapshot_max_observation_id=20,
        run_id=71,
        after_trade_date=date(2024, 1, 2),
        after_observation_id=9,
        batch_size=100,
        identity_resolver=FakeClassifierResolver(),
    )

    assert result.scanned == 2
    assert result.updated == 2
    assert result.target_status_counts == {"matched": 1, "needs_instrument": 1}
    assert result.last_observation_id == 11
    assert connection.executemany_parameters is not None
    assert {row["p_observation_id"] for row in connection.executemany_parameters} == {10, 11}
    update_sql = str(connection.statements[-1])
    assert "last_classified_run_id" in update_sql
    select_sql = str(connection.statements[0])
    assert "trade_date >" in select_sql
    assert "ORDER BY" in select_sql
    assert "trade_date" in select_sql.split("ORDER BY", maxsplit=1)[1]
    mysql_select_sql = str(connection.statements[0].compile(dialect=mysql.dialect()))
    assert "FORCE INDEX (ix_bulk_unmatched_market_status_date_id)" in mysql_select_sql


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
    group_key = {"instrument_id": 77, "trade_date": date(2024, 1, 2)}
    dry_connection = FakeConnection([[group_key], [route_row], []])

    dry_result = route_bulk_unmatched_observations(
        dry_connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        dry_run=True,
    )

    assert dry_result.routeable == 1
    assert dry_result.rows_inserted == 0
    assert all(getattr(statement, "table", None) is not stock_daily_price for statement in dry_connection.statements)

    execute_connection = FakeConnection([[group_key], [route_row], []])
    executed = route_bulk_unmatched_observations(
        execute_connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        dry_run=False,
        run_id=71,
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
    connection = FakeConnection(
        [[{"instrument_id": 77, "trade_date": date(2014, 8, 18)}], rows, []]
    )

    result = route_bulk_unmatched_observations(
        connection,
        date_from=date(2014, 8, 18),
        date_to=date(2014, 8, 18),
        dry_run=False,
        run_id=72,
    )

    assert result.routeable == 1
    assert result.rows_inserted == 1
    assert result.rows_rejected == 1
    assert result.routed == 1
    assert result.groups_selected == 1
    assert result.observations_selected == 2
    assert result.shadowed == 1
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


def test_route_price_validation_failure_is_not_labeled_identity_conflict() -> None:
    group_key = {"instrument_id": 77, "trade_date": date(2024, 1, 2)}
    row = {
        "observation_id": 9,
        "trade_date": date(2024, 1, 2),
        "open": Decimal("10"),
        "high": Decimal("8"),
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
    }
    connection = FakeConnection([[group_key], [row], []])

    result = route_bulk_unmatched_observations(
        connection,
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        dry_run=True,
    )

    assert result.observations_selected == 1
    assert result.routeable == 0
    assert result.route_failed == 1
    assert result.route_failures[0].issue_type == "invalid_ohlcv"


def test_route_overwrite_allows_high_to_supersede_explicit_medium() -> None:
    row = {
        "instrument_id": 77,
        "trade_date": date(2014, 8, 18),
        "observed_provider_symbol": "OLD.US",
        "classification_reason": "identifier_history_match",
    }
    resolution = _route_identity_resolution(row)
    assert resolution is not None

    allowed, supersedes, reason = _canonical_overwrite_decision(
        row=row,
        resolution=resolution,
        existing_row={"provider_symbol": "NEW.US"},
        existing_audits={
            (77, "NEW.US"): [{
                "audit_id": 91,
                "confidence": "medium",
                "observed_from": date(2014, 8, 18),
                "observed_to": date(2014, 8, 18),
            }]
        },
    )

    assert allowed is True
    assert supersedes == 91
    assert reason == "high_supersedes_medium"


@pytest.mark.parametrize(
    ("classification_reason", "existing_audits", "expected_fragment"),
    [
        ("current_provider_symbol_match", {}, "incoming_confidence_not_high"),
        ("identifier_history_match", {}, "existing_confidence=unknown"),
        (
            "identifier_history_match",
            {
                (77, "NEW.US"): [{
                    "audit_id": 92,
                    "confidence": "high",
                    "observed_from": date(2014, 8, 18),
                    "observed_to": date(2014, 8, 18),
                }]
            },
            "existing_confidence=high",
        ),
    ],
)
def test_route_overwrite_blocks_equal_lower_or_unknown_confidence(
    classification_reason: str,
    existing_audits: dict[tuple[int, str], list[dict[str, object]]],
    expected_fragment: str,
) -> None:
    row = {
        "instrument_id": 77,
        "trade_date": date(2014, 8, 18),
        "observed_provider_symbol": "OLD.US",
        "classification_reason": classification_reason,
    }
    resolution = _route_identity_resolution(row)
    assert resolution is not None

    allowed, supersedes, reason = _canonical_overwrite_decision(
        row=row,
        resolution=resolution,
        existing_row={"provider_symbol": "NEW.US"},
        existing_audits=existing_audits,
    )

    assert allowed is False
    assert supersedes is None
    assert expected_fragment in reason


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
