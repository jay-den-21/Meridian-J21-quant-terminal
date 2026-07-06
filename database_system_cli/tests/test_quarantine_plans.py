from datetime import date
from decimal import Decimal
from typing import Any

from fdp.quarantine import (
    CONFIRMED,
    DEDUPE_DAILY_PRICE_ROWS,
    EXECUTED,
    FAILED,
    PENDING_CONFIRMATION,
    QUARANTINE_DAILY_PRICE_ROW,
    confirm_quarantine_plan,
    create_daily_price_quarantine_plans,
    execute_quarantine_plan,
    list_quarantine_plans,
    preview_quarantine_plan_source_rows,
)
from fdp.storage.tables import (
    data_quality_issue,
    quarantine_plan,
    quarantined_daily_price_row,
)


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
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount


class FakeQuarantineConnection:
    def __init__(
        self,
        select_rows: list[list[dict[str, Any]]],
        *,
        delete_rowcount: int | None = None,
    ) -> None:
        self.select_rows = select_rows
        self.delete_rowcount = delete_rowcount
        self.statements: list[Any] = []

    def execute(self, statement):
        self.statements.append(statement)
        if getattr(statement, "is_delete", False):
            return FakeWriteResult(
                self.delete_rowcount if self.delete_rowcount is not None else 1
            )
        if getattr(statement, "is_insert", False) or getattr(statement, "is_update", False):
            return FakeWriteResult()
        return FakeSelectResult(self.select_rows.pop(0))


def test_create_daily_price_quarantine_plans_maps_bad_rows() -> None:
    connection = FakeQuarantineConnection(
        select_rows=[
            [_issue_row(9001, "stock_daily_price", "invalid_ohlcv", "AAPL", date(2026, 1, 5))],
            [],
        ]
    )

    result = create_daily_price_quarantine_plans(
        connection,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        asset_types=["stock"],
    )

    assert result.eligible_issues == 1
    assert result.existing_plans == 0
    assert result.plans_created == 1
    assert result.created_plans[0].status == PENDING_CONFIRMATION
    assert result.created_plans[0].action_type == QUARANTINE_DAILY_PRICE_ROW
    assert _table_was_inserted(connection, quarantine_plan)


def test_create_daily_price_quarantine_plans_maps_duplicate_groups_to_dedupe() -> None:
    connection = FakeQuarantineConnection(
        select_rows=[
            [_issue_row(9001, "stock_daily_price", "duplicate_key", None, date(2026, 1, 5))],
            [],
        ]
    )

    result = create_daily_price_quarantine_plans(
        connection,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        issue_types=["duplicate_key"],
        asset_types=["stock"],
    )

    assert result.eligible_issues == 1
    assert result.plans_created == 1
    assert result.created_plans[0].action_type == DEDUPE_DAILY_PRICE_ROWS
    assert _table_was_inserted(connection, quarantine_plan)


def test_create_daily_price_quarantine_plans_skips_existing_plan() -> None:
    connection = FakeQuarantineConnection(
        select_rows=[
            [_issue_row(9001, "stock_daily_price", "invalid_ohlcv", "AAPL", date(2026, 1, 5))],
            [{"issue_id": 9001, "action_type": QUARANTINE_DAILY_PRICE_ROW}],
        ]
    )

    result = create_daily_price_quarantine_plans(
        connection,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        asset_types=["stock"],
    )

    assert result.eligible_issues == 1
    assert result.existing_plans == 1
    assert result.plans_created == 0
    assert all(getattr(statement, "table", None) is not quarantine_plan for statement in connection.statements)


def test_create_daily_price_quarantine_plans_skips_wrong_target_schema() -> None:
    connection = FakeQuarantineConnection(
        select_rows=[
            [
                _issue_row(
                    9001,
                    "stock_daily_price",
                    "invalid_ohlcv",
                    "AAPL",
                    date(2026, 1, 5),
                    target_schema="system",
                )
            ],
        ]
    )

    result = create_daily_price_quarantine_plans(
        connection,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        asset_types=["stock"],
    )

    assert result.eligible_issues == 0
    assert result.plans_created == 0
    assert all(getattr(statement, "table", None) is not quarantine_plan for statement in connection.statements)


def test_list_quarantine_plans_returns_preview_records() -> None:
    connection = FakeQuarantineConnection(
        select_rows=[
            [
                {
                    "quarantine_plan_id": 8001,
                    "issue_id": 9001,
                    "market": "US",
                    "action_type": QUARANTINE_DAILY_PRICE_ROW,
                    "target_schema": "us_share",
                    "target_table": "stock_daily_price",
                    "instrument_id": 123,
                    "symbol": "AAPL",
                    "provider_symbol": None,
                    "date_from": date(2026, 1, 5),
                    "date_to": date(2026, 1, 5),
                    "status": PENDING_CONFIRMATION,
                    "row_count": 0,
                    "issue_type": "invalid_ohlcv",
                }
            ],
        ]
    )

    rows = list_quarantine_plans(connection, statuses=[PENDING_CONFIRMATION], limit=10)

    assert len(rows) == 1
    assert rows[0].quarantine_plan_id == 8001
    assert rows[0].issue_id == 9001
    assert rows[0].action_type == QUARANTINE_DAILY_PRICE_ROW


def test_confirm_quarantine_plan_requires_open_issue() -> None:
    context = _plan_context("invalid_ohlcv")
    context["status"] = PENDING_CONFIRMATION
    context["issue_status"] = "resolved"
    connection = FakeQuarantineConnection(select_rows=[[context]])

    try:
        confirm_quarantine_plan(connection, quarantine_plan_id=8001)
    except ValueError as exc:
        assert "expected 'open'" in str(exc)
    else:
        raise AssertionError("expected confirm_quarantine_plan to reject non-open issues")

    assert all(not getattr(statement, "is_update", False) for statement in connection.statements)


def test_preview_quarantine_plan_source_rows_returns_current_bad_rows() -> None:
    bad_row = _price_row(
        1, open_=Decimal("10"), high=Decimal("9"), low=Decimal("8"), close=Decimal("10")
    )
    connection = FakeQuarantineConnection(
        select_rows=[
            [_plan_context("invalid_ohlcv")],
            [bad_row],
        ]
    )

    rows = preview_quarantine_plan_source_rows(connection, quarantine_plan_id=8001)

    assert rows == [
        {
            "source_primary_key": 1,
            "instrument_id": 123,
            "symbol": "AAPL",
            "provider_symbol": "AAPL.US",
            "trade_date": date(2026, 1, 5),
            "open": Decimal("10"),
            "high": Decimal("9"),
            "low": Decimal("8"),
            "close": Decimal("10"),
            "adjusted_close": Decimal("10"),
            "volume": 100,
        }
    ]


def test_execute_quarantine_plan_archives_then_deletes_invalid_ohlcv_row() -> None:
    bad_row = _price_row(
        1, open_=Decimal("10"), high=Decimal("9"), low=Decimal("8"), close=Decimal("10")
    )
    connection = FakeQuarantineConnection(
        select_rows=[
            [_plan_context("invalid_ohlcv")],
            [bad_row],
            [],
        ]
    )

    result = execute_quarantine_plan(connection, quarantine_plan_id=8001)

    assert result.status == EXECUTED
    assert result.issue_resolved is True
    assert result.rows_quarantined == 1
    assert _table_was_inserted(connection, quarantined_daily_price_row)
    assert _table_was_updated(connection, quarantine_plan)
    assert _table_was_updated(connection, data_quality_issue)
    assert any(getattr(statement, "is_delete", False) for statement in connection.statements)
    assert _statement_index(connection, "insert", quarantined_daily_price_row) < _statement_index(
        connection,
        "delete",
        None,
    )


def test_execute_quarantine_plan_fails_when_delete_rowcount_mismatches() -> None:
    bad_row = _price_row(
        1, open_=Decimal("10"), high=Decimal("9"), low=Decimal("8"), close=Decimal("10")
    )
    connection = FakeQuarantineConnection(
        select_rows=[
            [_plan_context("invalid_ohlcv")],
            [bad_row],
        ],
        delete_rowcount=0,
    )

    result = execute_quarantine_plan(connection, quarantine_plan_id=8001)

    assert result.status == FAILED
    assert result.issue_resolved is False
    assert result.rows_quarantined == 1
    assert result.rows_deleted == 0
    assert _table_was_inserted(connection, quarantined_daily_price_row)
    assert not _table_was_updated(connection, data_quality_issue)


def test_execute_quarantine_plan_dedupes_duplicate_key_group() -> None:
    keeper_row = _price_row(1)
    duplicate_row_1 = _price_row(2)
    duplicate_row_2 = _price_row(3)
    connection = FakeQuarantineConnection(
        select_rows=[
            [_plan_context("duplicate_key")],
            [keeper_row, duplicate_row_1, duplicate_row_2],
            [keeper_row],
        ],
        delete_rowcount=2,
    )

    result = execute_quarantine_plan(connection, quarantine_plan_id=8001)

    assert result.status == EXECUTED
    assert result.action_type == DEDUPE_DAILY_PRICE_ROWS
    assert result.issue_resolved is True
    assert result.rows_quarantined == 2
    assert result.rows_deleted == 2
    assert _table_was_inserted(connection, quarantined_daily_price_row)
    assert _statement_index(connection, "insert", quarantined_daily_price_row) < _statement_index(
        connection,
        "delete",
        None,
    )


def test_execute_quarantine_plan_rejects_conflicting_duplicate_key_payloads() -> None:
    keeper_row = _price_row(1, close=Decimal("10"))
    conflicting_row = _price_row(2, close=Decimal("10.50"))
    connection = FakeQuarantineConnection(
        select_rows=[
            [_plan_context("duplicate_key")],
            [keeper_row, conflicting_row],
        ]
    )

    try:
        execute_quarantine_plan(connection, quarantine_plan_id=8001)
    except ValueError as exc:
        assert "conflicting price payloads" in str(exc)
    else:
        raise AssertionError("expected conflicting duplicate payloads to require manual review")

    assert not _table_was_inserted(connection, quarantined_daily_price_row)
    assert not any(getattr(statement, "is_delete", False) for statement in connection.statements)


def test_execute_quarantine_plan_resolves_stale_duplicate_issue_without_delete() -> None:
    keeper_row = _price_row(1)
    connection = FakeQuarantineConnection(
        select_rows=[
            [_plan_context("duplicate_key")],
            [keeper_row],
            [keeper_row],
        ]
    )

    result = execute_quarantine_plan(connection, quarantine_plan_id=8001)

    assert result.status == EXECUTED
    assert result.issue_resolved is True
    assert result.rows_quarantined == 0
    assert not _table_was_inserted(connection, quarantined_daily_price_row)
    assert not any(getattr(statement, "is_delete", False) for statement in connection.statements)


def test_execute_quarantine_plan_deletes_non_trading_row_only_when_calendar_still_non_trading() -> (
    None
):
    price_row = _price_row(1)
    connection = FakeQuarantineConnection(
        select_rows=[
            [_plan_context("price_on_non_trading_day")],
            [price_row],
            [{"is_trading_day": False}],
            [],
            [{"is_trading_day": False}],
        ]
    )

    result = execute_quarantine_plan(connection, quarantine_plan_id=8001)

    assert result.status == EXECUTED
    assert result.issue_resolved is True
    assert result.rows_quarantined == 1
    assert _statement_index(connection, "insert", quarantined_daily_price_row) < _statement_index(
        connection,
        "delete",
        None,
    )


def test_execute_quarantine_plan_fails_stale_non_trading_issue_without_delete() -> None:
    price_row = _price_row(1)
    connection = FakeQuarantineConnection(
        select_rows=[
            [_plan_context("price_on_non_trading_day")],
            [price_row],
            [{"is_trading_day": True}],
            [price_row],
        ]
    )

    result = execute_quarantine_plan(connection, quarantine_plan_id=8001)

    assert result.status == FAILED
    assert result.issue_resolved is False
    assert result.rows_quarantined == 0
    assert not _table_was_inserted(connection, quarantined_daily_price_row)
    assert not any(getattr(statement, "is_delete", False) for statement in connection.statements)
    assert not _table_was_updated(connection, data_quality_issue)


def test_execute_quarantine_plan_requires_confirmed_status() -> None:
    context = _plan_context("invalid_ohlcv")
    context["status"] = PENDING_CONFIRMATION
    connection = FakeQuarantineConnection(select_rows=[[context]])

    try:
        execute_quarantine_plan(connection, quarantine_plan_id=8001)
    except ValueError as exc:
        assert "expected 'confirmed'" in str(exc)
    else:
        raise AssertionError("expected execute_quarantine_plan to reject unconfirmed plans")

    assert all(not getattr(statement, "is_update", False) for statement in connection.statements)


def _issue_row(
    issue_id: int,
    target_table: str,
    issue_type: str,
    symbol: str | None,
    trade_date: date,
    *,
    target_schema: str = "us_share",
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "market": "US",
        "target_schema": target_schema,
        "target_table": target_table,
        "issue_type": issue_type,
        "instrument_id": 123,
        "symbol": symbol,
        "trade_date": trade_date,
    }


def _plan_context(issue_type: str) -> dict[str, Any]:
    action_type = (
        DEDUPE_DAILY_PRICE_ROWS if issue_type == "duplicate_key" else QUARANTINE_DAILY_PRICE_ROW
    )
    return {
        "quarantine_plan_id": 8001,
        "issue_id": 9001,
        "market": "US",
        "action_type": action_type,
        "target_schema": "us_share",
        "target_table": "stock_daily_price",
        "instrument_id": 123,
        "symbol": "AAPL",
        "provider_symbol": "AAPL.US",
        "date_from": date(2026, 1, 5),
        "date_to": date(2026, 1, 5),
        "status": CONFIRMED,
        "row_count": 0,
        "issue_type": issue_type,
        "issue_status": "open",
    }


def _price_row(
    primary_key: int,
    *,
    open_: Decimal = Decimal("10"),
    high: Decimal = Decimal("11"),
    low: Decimal = Decimal("9"),
    close: Decimal = Decimal("10"),
) -> dict[str, Any]:
    return {
        "stock_daily_price_id": primary_key,
        "instrument_id": 123,
        "symbol": "AAPL",
        "provider_symbol": "AAPL.US",
        "trade_date": date(2026, 1, 5),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "adjusted_close": close,
        "volume": 100,
        "currency": "USD",
        "source": "EODHD",
    }


def _table_was_inserted(connection: FakeQuarantineConnection, table) -> bool:
    return any(getattr(statement, "is_insert", False) and statement.table is table for statement in connection.statements)


def _table_was_updated(connection: FakeQuarantineConnection, table) -> bool:
    return any(getattr(statement, "is_update", False) and statement.table is table for statement in connection.statements)


def _statement_index(connection: FakeQuarantineConnection, kind: str, table) -> int:
    for index, statement in enumerate(connection.statements):
        if kind == "insert" and getattr(statement, "is_insert", False) and statement.table is table:
            return index
        if kind == "delete" and getattr(statement, "is_delete", False):
            return index
    raise AssertionError(f"{kind} statement for {table} not found")
