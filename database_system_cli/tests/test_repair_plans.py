from datetime import date
from typing import Any

from fdp.repair import (
    CONFIRMED,
    EXECUTED,
    PENDING_CONFIRMATION,
    create_missing_daily_price_repair_plans,
    execute_repair_plan,
    list_repair_plans,
)
from fdp.sources.eodhd.ingest.models import HistoricalDailyPriceLoadResult
from fdp.storage.tables import data_quality_issue, repair_plan


class FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class FakeSelectResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeMappings:
        return FakeMappings(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class FakeWriteResult:
    rowcount = 1


class FakeRepairConnection:
    def __init__(self, select_rows: list[list[dict[str, Any]]]) -> None:
        self.select_rows = select_rows
        self.statements: list[Any] = []

    def execute(self, statement):
        self.statements.append(statement)
        if getattr(statement, "is_insert", False) or getattr(statement, "is_update", False):
            return FakeWriteResult()
        return FakeSelectResult(self.select_rows.pop(0))


def test_create_missing_daily_price_repair_plans_inserts_pending_plan() -> None:
    connection = FakeRepairConnection(
        select_rows=[
            [_missing_issue_row(9001)],
            [],
        ]
    )

    result = create_missing_daily_price_repair_plans(
        connection,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        asset_types=["stock"],
    )

    assert result.eligible_issues == 1
    assert result.existing_plans == 0
    assert result.plans_created == 1
    assert result.created_plans[0].status == PENDING_CONFIRMATION
    assert result.created_plans[0].provider_symbol == "AAPL.US"
    assert sum(getattr(statement, "table", None) is repair_plan for statement in connection.statements) == 1


def test_create_missing_daily_price_repair_plans_skips_existing_plan() -> None:
    connection = FakeRepairConnection(
        select_rows=[
            [_missing_issue_row(9001)],
            [{"target_table": "stock_daily_price", "instrument_id": 123, "trade_date": date(2026, 1, 5)}],
        ]
    )

    result = create_missing_daily_price_repair_plans(
        connection,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        asset_types=["stock"],
    )

    assert result.eligible_issues == 1
    assert result.existing_plans == 1
    assert result.plans_created == 0
    assert all(getattr(statement, "table", None) is not repair_plan for statement in connection.statements)


def test_create_missing_daily_price_repair_plans_dedupes_logical_issue_key() -> None:
    connection = FakeRepairConnection(
        select_rows=[
            [_missing_issue_row(9001), _missing_issue_row(9002)],
            [],
        ]
    )

    result = create_missing_daily_price_repair_plans(
        connection,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        asset_types=["stock"],
    )

    assert result.eligible_issues == 2
    assert result.plans_created == 1
    assert _table_write_count(connection, repair_plan) == 1


def test_list_repair_plans_returns_preview_records() -> None:
    connection = FakeRepairConnection(
        select_rows=[
            [
                {
                    "repair_plan_id": 7001,
                    "issue_id": 9001,
                    "market": "US",
                    "repair_type": "backfill_missing_daily_price",
                    "symbol": "AAPL",
                    "provider_symbol": "AAPL.US",
                    "date_from": date(2026, 1, 5),
                    "date_to": date(2026, 1, 5),
                    "status": PENDING_CONFIRMATION,
                }
            ],
        ]
    )

    rows = list_repair_plans(connection, statuses=[PENDING_CONFIRMATION], limit=10)

    assert len(rows) == 1
    assert rows[0].repair_plan_id == 7001
    assert rows[0].issue_id == 9001
    assert rows[0].status == PENDING_CONFIRMATION


def test_execute_repair_plan_backfills_and_resolves_issue(monkeypatch) -> None:
    load_calls: list[dict[str, Any]] = []
    repair_plan_updates_at_load: list[int] = []

    def fake_load_daily_prices_for_instrument_ids(connection, client, **kwargs):
        repair_plan_updates_at_load.append(_table_write_count(connection, repair_plan))
        load_calls.append(kwargs)
        return HistoricalDailyPriceLoadResult(
            run_id=42,
            status="success",
            symbols_requested=1,
            symbols_loaded=1,
            rows_fetched=1,
            rows_inserted=1,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
            error_message=None,
        )

    monkeypatch.setattr(
        "fdp.repair.plans.load_daily_prices_for_instrument_ids",
        fake_load_daily_prices_for_instrument_ids,
    )
    connection = FakeRepairConnection(
        select_rows=[
            [_execution_context(status=CONFIRMED)],
            [{"instrument_id": 123}],
        ]
    )

    result = execute_repair_plan(connection, object(), repair_plan_id=7001)

    assert result.status == EXECUTED
    assert result.issue_resolved is True
    assert result.ingest_run_id == 42
    assert load_calls == [
        {
            "instrument_ids": [123],
            "date_from": date(2026, 1, 5),
            "date_to": date(2026, 1, 5),
            "market": "US",
            "asset_types": ["stock"],
            "job_name": "eodhd_repair_daily_price",
            "target_table": "stock_daily_price",
        }
    ]
    assert repair_plan_updates_at_load == [1]
    updated_tables = [getattr(statement, "table", None) for statement in connection.statements]
    assert repair_plan in updated_tables
    assert data_quality_issue in updated_tables


def test_execute_repair_plan_rejects_stale_provider_symbol(monkeypatch) -> None:
    load_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "fdp.repair.plans.load_daily_prices_for_instrument_ids",
        lambda connection, client, **kwargs: load_calls.append(kwargs),
    )
    connection = FakeRepairConnection(
        select_rows=[
            [
                _execution_context(
                    status=CONFIRMED,
                    provider_symbol="AAPL.US",
                    current_provider_symbol="AAPL1.US",
                )
            ],
        ]
    )

    try:
        execute_repair_plan(connection, object(), repair_plan_id=7001)
    except ValueError as exc:
        assert "provider_symbol" in str(exc)
        assert "stale" in str(exc)
    else:
        raise AssertionError("expected stale provider_symbol to reject execution")

    assert load_calls == []
    assert all(not getattr(statement, "is_update", False) for statement in connection.statements)


def test_execute_repair_plan_requires_confirmed_status() -> None:
    connection = FakeRepairConnection(
        select_rows=[
            [_execution_context(status=PENDING_CONFIRMATION)],
        ]
    )

    try:
        execute_repair_plan(connection, object(), repair_plan_id=7001)
    except ValueError as exc:
        assert "expected 'confirmed'" in str(exc)
    else:
        raise AssertionError("expected execute_repair_plan to reject unconfirmed plans")

    assert all(not getattr(statement, "is_update", False) for statement in connection.statements)


def _missing_issue_row(issue_id: int) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "market": "US",
        "target_schema": "us_share",
        "target_table": "stock_daily_price",
        "instrument_id": 123,
        "issue_symbol": "AAPL",
        "instrument_symbol": "AAPL",
        "provider_symbol": "AAPL.US",
        "trade_date": date(2026, 1, 5),
    }


def _execution_context(
    *,
    status: str,
    provider_symbol: str = "AAPL.US",
    current_provider_symbol: str = "AAPL.US",
) -> dict[str, Any]:
    return {
        "repair_plan_id": 7001,
        "issue_id": 9001,
        "market": "US",
        "repair_type": "backfill_missing_daily_price",
        "symbol": "AAPL",
        "provider_symbol": provider_symbol,
        "date_from": date(2026, 1, 5),
        "date_to": date(2026, 1, 5),
        "status": status,
        "target_schema": "us_share",
        "target_table": "stock_daily_price",
        "instrument_id": 123,
        "issue_status": "open",
        "current_symbol": "AAPL",
        "current_provider_symbol": current_provider_symbol,
        "instrument_asset_type": "stock",
    }


def _table_write_count(connection: FakeRepairConnection, table) -> int:
    return sum(getattr(statement, "table", None) is table for statement in connection.statements)
