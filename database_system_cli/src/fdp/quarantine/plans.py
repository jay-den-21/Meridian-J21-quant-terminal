"""Quarantine-plan builders for confirmed daily-price quality cleanup."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Table, delete, select, update
from sqlalchemy.engine import Connection

from fdp.storage.tables import (
    DAILY_PRICE_TABLES,
    data_quality_issue,
    market_calendar,
    quarantine_plan,
    quarantined_daily_price_row,
)

PENDING_CONFIRMATION = "pending_confirmation"
CONFIRMED = "confirmed"
EXECUTING = "executing"
EXECUTED = "executed"
FAILED = "failed"

QUARANTINE_DAILY_PRICE_ROW = "quarantine_daily_price_row"
DEDUPE_DAILY_PRICE_ROWS = "dedupe_daily_price_rows"
QUARANTINE_ISSUE_TYPES = {
    "duplicate_key",
    "invalid_ohlcv",
    "price_on_non_trading_day",
}
ISSUE_TYPE_ACTIONS = {
    "duplicate_key": DEDUPE_DAILY_PRICE_ROWS,
    "invalid_ohlcv": QUARANTINE_DAILY_PRICE_ROW,
    "price_on_non_trading_day": QUARANTINE_DAILY_PRICE_ROW,
}

DAILY_PRICE_TARGET_TABLES = {table.name: table for table in DAILY_PRICE_TABLES.values()}


@dataclass(frozen=True)
class QuarantinePlanRecord:
    """One stored quarantine-plan row plus enough fields for operator preview."""

    quarantine_plan_id: int | None
    issue_id: int
    market: str
    action_type: str
    target_schema: str
    target_table: str
    instrument_id: int | None
    symbol: str | None
    provider_symbol: str | None
    date_from: date
    date_to: date
    status: str
    row_count: int = 0
    issue_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-serializable representation."""
        return {
            "quarantine_plan_id": self.quarantine_plan_id,
            "issue_id": self.issue_id,
            "market": self.market,
            "action_type": self.action_type,
            "target_schema": self.target_schema,
            "target_table": self.target_table,
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "provider_symbol": self.provider_symbol,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "status": self.status,
            "row_count": self.row_count,
            "issue_type": self.issue_type,
        }


@dataclass(frozen=True)
class QuarantinePlanResult:
    """Summary returned after creating daily-price quarantine plans."""

    date_from: date
    date_to: date
    issue_types: list[str]
    eligible_issues: int
    existing_plans: int
    plans_created: int
    created_plans: list[QuarantinePlanRecord]


@dataclass(frozen=True)
class QuarantineExecutionResult:
    """Summary returned after executing one confirmed quarantine plan."""

    quarantine_plan_id: int
    issue_id: int
    action_type: str
    target_table: str
    status: str
    rows_quarantined: int
    rows_deleted: int
    issue_resolved: bool
    result_message: str

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-serializable representation."""
        return {
            "quarantine_plan_id": self.quarantine_plan_id,
            "issue_id": self.issue_id,
            "action_type": self.action_type,
            "target_table": self.target_table,
            "status": self.status,
            "rows_quarantined": self.rows_quarantined,
            "rows_deleted": self.rows_deleted,
            "issue_resolved": self.issue_resolved,
            "result_message": self.result_message,
        }


def create_daily_price_quarantine_plans(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    issue_types: list[str] | None = None,
    asset_types: list[str] | None = None,
    market: str = "US",
) -> QuarantinePlanResult:
    """Create quarantine plans from open daily-price quality issues.

    Input: date range, market, issue types, and asset table scope.
    Output: count summary and created plan previews.
    Flow: open bad-row issues -> existing-plan filter -> quarantine_plan rows.
    """
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")

    selected_issue_types = _normalize_issue_types(issue_types)
    target_tables = _target_tables_for_asset_types(asset_types)
    issue_rows = _quarantinable_issue_rows(
        connection,
        date_from=date_from,
        date_to=date_to,
        issue_types=selected_issue_types,
        market=market,
        target_tables=target_tables,
    )
    issue_keys = [
        (int(row["issue_id"]), _action_type_for_issue_type(str(row["issue_type"])))
        for row in issue_rows
    ]
    existing_issue_keys = _issue_keys_with_quarantine_plans(connection, issue_keys)

    created_plans = [
        _plan_record_from_issue(row)
        for row in issue_rows
        if (
            int(row["issue_id"]),
            _action_type_for_issue_type(str(row["issue_type"])),
        )
        not in existing_issue_keys
    ]
    if created_plans:
        connection.execute(
            quarantine_plan.insert().values(
                [_insert_row_from_record(record) for record in created_plans]
            )
        )

    return QuarantinePlanResult(
        date_from=date_from,
        date_to=date_to,
        issue_types=selected_issue_types,
        eligible_issues=len(issue_rows),
        existing_plans=len(existing_issue_keys),
        plans_created=len(created_plans),
        created_plans=created_plans,
    )


def list_quarantine_plans(
    connection: Connection,
    *,
    statuses: list[str] | None = None,
    limit: int = 50,
) -> list[QuarantinePlanRecord]:
    """List quarantine plans for operator review."""
    if limit <= 0:
        raise ValueError("limit must be positive")

    statement = (
        select(
            quarantine_plan.c.quarantine_plan_id,
            quarantine_plan.c.issue_id,
            quarantine_plan.c.market,
            quarantine_plan.c.action_type,
            quarantine_plan.c.target_schema,
            quarantine_plan.c.target_table,
            quarantine_plan.c.instrument_id,
            quarantine_plan.c.symbol,
            quarantine_plan.c.provider_symbol,
            quarantine_plan.c.date_from,
            quarantine_plan.c.date_to,
            quarantine_plan.c.status,
            quarantine_plan.c.row_count,
            data_quality_issue.c.issue_type,
        )
        .select_from(
            quarantine_plan.join(
                data_quality_issue,
                quarantine_plan.c.issue_id == data_quality_issue.c.issue_id,
            )
        )
        .order_by(quarantine_plan.c.created_at.desc(), quarantine_plan.c.quarantine_plan_id.desc())
        .limit(limit)
    )
    if statuses:
        statement = statement.where(quarantine_plan.c.status.in_(statuses))

    return [_plan_record_from_plan(row) for row in connection.execute(statement).mappings()]


def get_quarantine_plan(connection: Connection, *, quarantine_plan_id: int) -> QuarantinePlanRecord:
    """Return one quarantine plan or raise when the id is unknown."""
    row = (
        connection.execute(
            select(
                quarantine_plan.c.quarantine_plan_id,
                quarantine_plan.c.issue_id,
                quarantine_plan.c.market,
                quarantine_plan.c.action_type,
                quarantine_plan.c.target_schema,
                quarantine_plan.c.target_table,
                quarantine_plan.c.instrument_id,
                quarantine_plan.c.symbol,
                quarantine_plan.c.provider_symbol,
                quarantine_plan.c.date_from,
                quarantine_plan.c.date_to,
                quarantine_plan.c.status,
                quarantine_plan.c.row_count,
                data_quality_issue.c.issue_type,
            )
            .select_from(
                quarantine_plan.join(
                    data_quality_issue,
                    quarantine_plan.c.issue_id == data_quality_issue.c.issue_id,
                )
            )
            .where(quarantine_plan.c.quarantine_plan_id == quarantine_plan_id)
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ValueError(f"quarantine plan {quarantine_plan_id} not found")
    return _plan_record_from_plan(row)


def confirm_quarantine_plan(
    connection: Connection,
    *,
    quarantine_plan_id: int,
) -> QuarantinePlanRecord:
    """Mark a pending quarantine plan as confirmed by the operator."""
    context = _get_execution_context(connection, quarantine_plan_id=quarantine_plan_id)
    current = _plan_record_from_plan(context)
    issue_type = str(context["issue_type"])
    issue_status = str(context["issue_status"])
    if current.status != PENDING_CONFIRMATION:
        raise ValueError(
            f"quarantine plan {quarantine_plan_id} has status {current.status!r}; "
            f"expected {PENDING_CONFIRMATION!r}"
        )
    if issue_status != "open":
        raise ValueError(
            f"linked issue {current.issue_id} has status {issue_status!r}; expected 'open'"
        )
    _validate_issue_action_contract(issue_type=issue_type, action_type=current.action_type)
    price_table = _daily_price_table_for_name(current.target_table)
    _validate_plan_target_schema(current, price_table)

    connection.execute(
        update(quarantine_plan)
        .where(quarantine_plan.c.quarantine_plan_id == quarantine_plan_id)
        .values(status=CONFIRMED, confirmed_at=_now_utc())
    )
    return get_quarantine_plan(connection, quarantine_plan_id=quarantine_plan_id)


def preview_quarantine_plan_source_rows(
    connection: Connection,
    *,
    quarantine_plan_id: int,
) -> list[dict[str, object]]:
    """Return the current source rows that would be archived/deleted for a plan."""
    context = _get_execution_context(connection, quarantine_plan_id=quarantine_plan_id)
    plan = _plan_record_from_plan(context)
    issue_type = str(context["issue_type"])
    _validate_issue_action_contract(issue_type=issue_type, action_type=plan.action_type)
    if plan.instrument_id is None:
        raise ValueError(
            f"quarantine plan {quarantine_plan_id} is linked to an issue without instrument_id"
        )

    price_table = _daily_price_table_for_name(plan.target_table)
    _validate_plan_target_schema(plan, price_table)
    rows = _bad_row_execution_rows(
        connection,
        price_table=price_table,
        issue_type=issue_type,
        instrument_id=plan.instrument_id,
        trade_date=plan.date_from,
        lock_rows=False,
    )
    return [_source_row_preview(price_table, row) for row in rows]


def execute_quarantine_plan(
    connection: Connection,
    *,
    quarantine_plan_id: int,
) -> QuarantineExecutionResult:
    """Execute one confirmed quarantine plan.

    Input: confirmed quarantine plan id.
    Output: execution summary and final plan/issue status.
    Flow: confirmed plan -> select bad rows -> archive payloads -> delete rows -> verify.
    """
    context = _get_execution_context(connection, quarantine_plan_id=quarantine_plan_id)
    plan = _plan_record_from_plan(context)
    issue_type = str(context["issue_type"])
    issue_status = str(context["issue_status"])
    if plan.status != CONFIRMED:
        raise ValueError(
            f"quarantine plan {quarantine_plan_id} has status {plan.status!r}; "
            f"expected {CONFIRMED!r}"
        )
    if issue_status != "open":
        raise ValueError(
            f"linked issue {plan.issue_id} has status {issue_status!r}; expected 'open'"
        )
    _validate_issue_action_contract(issue_type=issue_type, action_type=plan.action_type)
    if plan.instrument_id is None:
        raise ValueError(
            f"quarantine plan {quarantine_plan_id} is linked to an issue without instrument_id"
        )

    price_table = _daily_price_table_for_name(plan.target_table)
    _validate_plan_target_schema(plan, price_table)
    _claim_quarantine_plan(connection, quarantine_plan_id=quarantine_plan_id)
    rows_to_archive = _bad_row_execution_rows(
        connection,
        price_table=price_table,
        issue_type=issue_type,
        instrument_id=plan.instrument_id,
        trade_date=plan.date_from,
        lock_rows=True,
    )
    issue_resolved = _bad_row_issue_resolved(
        connection,
        price_table=price_table,
        issue_type=issue_type,
        instrument_id=plan.instrument_id,
        trade_date=plan.date_from,
        candidate_rows=rows_to_archive,
    )

    row_count = len(rows_to_archive)
    rows_deleted = 0
    if rows_to_archive:
        _archive_daily_price_rows(
            connection,
            plan=plan,
            price_table=price_table,
            rows=rows_to_archive,
            quarantine_reason=issue_type,
        )
        rows_deleted = _delete_daily_price_rows(
            connection,
            price_table=price_table,
            rows=rows_to_archive,
        )
        if rows_deleted != row_count:
            issue_resolved = False
        else:
            issue_resolved = _post_delete_issue_resolved(
                connection,
                price_table=price_table,
                issue_type=issue_type,
                instrument_id=plan.instrument_id,
                trade_date=plan.date_from,
            )

    final_status = EXECUTED if issue_resolved else FAILED
    result_message = _execution_result_message(
        action_type=plan.action_type,
        issue_type=issue_type,
        rows_quarantined=row_count,
        rows_deleted=rows_deleted,
        issue_resolved=issue_resolved,
    )
    _mark_quarantine_plan_finished(
        connection,
        quarantine_plan_id=quarantine_plan_id,
        status=final_status,
        row_count=row_count,
        result_message=result_message,
    )
    if issue_resolved:
        _mark_issue_resolved(connection, issue_id=plan.issue_id)

    return QuarantineExecutionResult(
        quarantine_plan_id=quarantine_plan_id,
        issue_id=plan.issue_id,
        action_type=plan.action_type,
        target_table=plan.target_table,
        status=final_status,
        rows_quarantined=row_count,
        rows_deleted=rows_deleted,
        issue_resolved=issue_resolved,
        result_message=result_message,
    )


def _quarantinable_issue_rows(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    issue_types: list[str],
    market: str,
    target_tables: dict[str, Table],
) -> list[dict[str, Any]]:
    target_table_names = list(target_tables)
    statement = (
        select(
            data_quality_issue.c.issue_id,
            data_quality_issue.c.market,
            data_quality_issue.c.target_schema,
            data_quality_issue.c.target_table,
            data_quality_issue.c.issue_type,
            data_quality_issue.c.instrument_id,
            data_quality_issue.c.symbol,
            data_quality_issue.c.trade_date,
        )
        .where(
            data_quality_issue.c.issue_type.in_(issue_types),
            data_quality_issue.c.status == "open",
            data_quality_issue.c.market == market,
            data_quality_issue.c.target_table.in_(target_table_names),
            data_quality_issue.c.instrument_id.is_not(None),
            data_quality_issue.c.trade_date.is_not(None),
            data_quality_issue.c.trade_date.between(date_from, date_to),
        )
        .order_by(
            data_quality_issue.c.target_table,
            data_quality_issue.c.symbol,
            data_quality_issue.c.trade_date,
            data_quality_issue.c.issue_type,
            data_quality_issue.c.issue_id,
        )
    )
    rows = [dict(row) for row in connection.execute(statement).mappings()]
    return [
        row
        for row in rows
        if _target_schema_matches(
            str(row["target_schema"]), target_tables[str(row["target_table"])]
        )
    ]


def _issue_keys_with_quarantine_plans(
    connection: Connection,
    issue_keys: list[tuple[int, str]],
) -> set[tuple[int, str]]:
    if not issue_keys:
        return set()
    issue_ids = sorted({issue_id for issue_id, _ in issue_keys})
    rows = connection.execute(
        select(quarantine_plan.c.issue_id, quarantine_plan.c.action_type).where(
            quarantine_plan.c.issue_id.in_(issue_ids),
            quarantine_plan.c.status.in_([PENDING_CONFIRMATION, CONFIRMED]),
        )
    ).mappings()
    expected = set(issue_keys)
    return {
        (int(row["issue_id"]), str(row["action_type"]))
        for row in rows
        if (int(row["issue_id"]), str(row["action_type"])) in expected
    }


def _plan_record_from_issue(row: dict[str, Any]) -> QuarantinePlanRecord:
    issue_id = int(row["issue_id"])
    trade_date = row["trade_date"]
    if not isinstance(trade_date, date):
        raise ValueError(f"issue {issue_id} has invalid trade_date")
    issue_type = str(row["issue_type"])

    return QuarantinePlanRecord(
        quarantine_plan_id=None,
        issue_id=issue_id,
        market=str(row["market"]),
        action_type=_action_type_for_issue_type(issue_type),
        target_schema=str(row["target_schema"]),
        target_table=str(row["target_table"]),
        instrument_id=int(row["instrument_id"]) if row["instrument_id"] is not None else None,
        symbol=str(row["symbol"]) if row["symbol"] is not None else None,
        provider_symbol=None,
        date_from=trade_date,
        date_to=trade_date,
        status=PENDING_CONFIRMATION,
        issue_type=issue_type,
    )


def _plan_record_from_plan(row: Any) -> QuarantinePlanRecord:
    return QuarantinePlanRecord(
        quarantine_plan_id=int(row["quarantine_plan_id"]),
        issue_id=int(row["issue_id"]),
        market=str(row["market"]),
        action_type=str(row["action_type"]),
        target_schema=str(row["target_schema"]),
        target_table=str(row["target_table"]),
        instrument_id=int(row["instrument_id"]) if row["instrument_id"] is not None else None,
        symbol=str(row["symbol"]) if row["symbol"] is not None else None,
        provider_symbol=str(row["provider_symbol"]) if row["provider_symbol"] is not None else None,
        date_from=row["date_from"],
        date_to=row["date_to"],
        status=str(row["status"]),
        row_count=int(row["row_count"] or 0),
        issue_type=str(row["issue_type"])
        if "issue_type" in row and row["issue_type"] is not None
        else None,
    )


def _insert_row_from_record(record: QuarantinePlanRecord) -> dict[str, object]:
    return {
        "issue_id": record.issue_id,
        "market": record.market,
        "action_type": record.action_type,
        "target_schema": record.target_schema,
        "target_table": record.target_table,
        "instrument_id": record.instrument_id,
        "symbol": record.symbol,
        "provider_symbol": record.provider_symbol,
        "date_from": record.date_from,
        "date_to": record.date_to,
        "status": record.status,
    }


def _get_execution_context(
    connection: Connection,
    *,
    quarantine_plan_id: int,
) -> dict[str, Any]:
    row = (
        connection.execute(
            select(
                quarantine_plan.c.quarantine_plan_id,
                quarantine_plan.c.issue_id,
                quarantine_plan.c.market,
                quarantine_plan.c.action_type,
                quarantine_plan.c.target_schema,
                quarantine_plan.c.target_table,
                quarantine_plan.c.instrument_id,
                quarantine_plan.c.symbol,
                quarantine_plan.c.provider_symbol,
                quarantine_plan.c.date_from,
                quarantine_plan.c.date_to,
                quarantine_plan.c.status,
                quarantine_plan.c.row_count,
                data_quality_issue.c.issue_type,
                data_quality_issue.c.status.label("issue_status"),
            )
            .select_from(
                quarantine_plan.join(
                    data_quality_issue,
                    quarantine_plan.c.issue_id == data_quality_issue.c.issue_id,
                )
            )
            .where(quarantine_plan.c.quarantine_plan_id == quarantine_plan_id)
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ValueError(f"quarantine plan {quarantine_plan_id} not found")
    return dict(row)


def _bad_row_execution_rows(
    connection: Connection,
    *,
    price_table: Table,
    issue_type: str,
    instrument_id: int,
    trade_date: date,
    lock_rows: bool,
) -> list[dict[str, Any]]:
    rows = _source_rows_for_issue(
        connection,
        price_table=price_table,
        instrument_id=instrument_id,
        trade_date=trade_date,
        lock_rows=lock_rows,
    )
    if issue_type == "duplicate_key":
        return _duplicate_rows_to_archive(rows)
    if issue_type == "invalid_ohlcv":
        return [row for row in rows if _row_has_invalid_ohlcv(row)]
    if issue_type == "price_on_non_trading_day":
        if not _trade_date_is_non_trading(connection, trade_date=trade_date):
            return []
        return rows
    raise ValueError(f"unsupported quarantine issue_type {issue_type!r}")


def _bad_row_issue_resolved(
    connection: Connection,
    *,
    price_table: Table,
    issue_type: str,
    instrument_id: int,
    trade_date: date,
    candidate_rows: list[dict[str, Any]],
) -> bool:
    if candidate_rows:
        return False
    return _post_delete_issue_resolved(
        connection,
        price_table=price_table,
        issue_type=issue_type,
        instrument_id=instrument_id,
        trade_date=trade_date,
    )


def _post_delete_issue_resolved(
    connection: Connection,
    *,
    price_table: Table,
    issue_type: str,
    instrument_id: int,
    trade_date: date,
) -> bool:
    remaining_rows = _source_rows_for_issue(
        connection,
        price_table=price_table,
        instrument_id=instrument_id,
        trade_date=trade_date,
    )
    if issue_type == "duplicate_key":
        return len(remaining_rows) <= 1
    if issue_type == "invalid_ohlcv":
        return not any(_row_has_invalid_ohlcv(row) for row in remaining_rows)
    if issue_type == "price_on_non_trading_day":
        return not remaining_rows
    raise ValueError(f"unsupported quarantine issue_type {issue_type!r}")


def _trade_date_is_non_trading(connection: Connection, *, trade_date: date) -> bool:
    row = (
        connection.execute(
            select(market_calendar.c.is_trading_day).where(
                market_calendar.c.calendar_date == trade_date
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return False
    is_trading_day = row["is_trading_day"]
    return is_trading_day is False or is_trading_day == 0


def _source_rows_for_issue(
    connection: Connection,
    *,
    price_table: Table,
    instrument_id: int,
    trade_date: date,
    lock_rows: bool = False,
) -> list[dict[str, Any]]:
    pk_column = _single_primary_key_column(price_table)
    statement = (
        select(price_table)
        .where(price_table.c.instrument_id == instrument_id, price_table.c.trade_date == trade_date)
        .order_by(pk_column)
    )
    if lock_rows:
        statement = statement.with_for_update()
    return [dict(row) for row in connection.execute(statement).mappings()]


def _archive_daily_price_rows(
    connection: Connection,
    *,
    plan: QuarantinePlanRecord,
    price_table: Table,
    rows: list[dict[str, Any]],
    quarantine_reason: str,
) -> None:
    pk_column = _single_primary_key_column(price_table)
    archive_rows = []
    for row in rows:
        payload = _stable_json(row)
        archive_rows.append(
            {
                "quarantine_plan_id": plan.quarantine_plan_id,
                "issue_id": plan.issue_id,
                "market": plan.market,
                "target_schema": plan.target_schema,
                "target_table": plan.target_table,
                "source_primary_key": int(row[pk_column.name]),
                "instrument_id": row.get("instrument_id"),
                "symbol": row.get("symbol"),
                "provider_symbol": row.get("provider_symbol"),
                "trade_date": row.get("trade_date"),
                "action_type": plan.action_type,
                "quarantine_reason": quarantine_reason,
                "row_payload": payload,
                "row_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            }
        )
    connection.execute(quarantined_daily_price_row.insert().values(archive_rows))


def _delete_daily_price_rows(
    connection: Connection,
    *,
    price_table: Table,
    rows: list[dict[str, Any]],
) -> int:
    pk_column = _single_primary_key_column(price_table)
    source_ids = [int(row[pk_column.name]) for row in rows]
    result = connection.execute(delete(price_table).where(pk_column.in_(source_ids)))
    return int(getattr(result, "rowcount", len(source_ids)))


def _source_row_preview(price_table: Table, row: dict[str, Any]) -> dict[str, object]:
    pk_column = _single_primary_key_column(price_table)
    return {
        "source_primary_key": row.get(pk_column.name),
        "instrument_id": row.get("instrument_id"),
        "symbol": row.get("symbol"),
        "provider_symbol": row.get("provider_symbol"),
        "trade_date": row.get("trade_date"),
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "close": row.get("close"),
        "adjusted_close": row.get("adjusted_close"),
        "volume": row.get("volume"),
    }


def _duplicate_rows_to_archive(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) <= 1:
        return []
    first_payload = _dedupe_compare_payload(rows[0])
    conflicting_rows = [
        row for row in rows[1:] if _dedupe_compare_payload(row) != first_payload
    ]
    if conflicting_rows:
        raise ValueError(
            "duplicate_key group has conflicting price payloads; manual review required"
        )
    return rows[1:]


def _dedupe_compare_payload(row: dict[str, Any]) -> tuple[object, ...]:
    columns = (
        "instrument_id",
        "symbol",
        "provider_symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
        "currency",
        "source",
    )
    return tuple(row.get(column) for column in columns)


def _row_has_invalid_ohlcv(row: dict[str, Any]) -> bool:
    price_columns = ("open", "high", "low", "close", "adjusted_close")
    if any(_is_negative(row.get(column)) for column in price_columns):
        return True
    if _is_negative(row.get("volume")):
        return True

    high = row.get("high")
    low = row.get("low")
    open_ = row.get("open")
    close = row.get("close")
    return (
        _less_than(high, low)
        or _less_than(high, open_)
        or _less_than(high, close)
        or _greater_than(low, open_)
        or _greater_than(low, close)
    )


def _less_than(left: Any, right: Any) -> bool:
    return left is not None and right is not None and left < right


def _greater_than(left: Any, right: Any) -> bool:
    return left is not None and right is not None and left > right


def _is_negative(value: Any) -> bool:
    return value is not None and value < 0


def _single_primary_key_column(table: Table):
    columns = list(table.primary_key.columns)
    if len(columns) != 1:
        raise ValueError(f"expected one primary key column on {table.name}")
    return columns[0]


def _validate_issue_action_contract(*, issue_type: str, action_type: str) -> None:
    if issue_type not in QUARANTINE_ISSUE_TYPES:
        expected = ", ".join(sorted(QUARANTINE_ISSUE_TYPES))
        raise ValueError(f"unsupported issue_type {issue_type!r}; expected one of {expected}")
    expected_action_type = _action_type_for_issue_type(issue_type)
    if action_type != expected_action_type:
        raise ValueError(
            f"quarantine plan action_type {action_type!r} does not match "
            f"issue_type {issue_type!r}; expected {expected_action_type!r}"
        )


def _validate_plan_target_schema(plan: QuarantinePlanRecord, price_table: Table) -> None:
    if not _target_schema_matches(plan.target_schema, price_table):
        expected = f"{_schema_name(price_table)}.{price_table.name}"
        actual = f"{plan.target_schema}.{plan.target_table}"
        raise ValueError(f"unsupported quarantine target {actual!r}; expected {expected!r}")


def _target_schema_matches(target_schema: str, price_table: Table) -> bool:
    return target_schema == _schema_name(price_table)


def _schema_name(table: Table) -> str:
    return str(table.schema or "")


def _normalize_issue_types(issue_types: list[str] | None) -> list[str]:
    if issue_types is None:
        return sorted(QUARANTINE_ISSUE_TYPES)
    normalized = [issue_type.strip() for issue_type in issue_types if issue_type.strip()]
    if not normalized:
        raise ValueError("issue_types must contain at least one issue type")
    unsupported = [
        issue_type for issue_type in normalized if issue_type not in QUARANTINE_ISSUE_TYPES
    ]
    if unsupported:
        expected = ", ".join(sorted(QUARANTINE_ISSUE_TYPES))
        raise ValueError(
            f"unsupported issue type(s): {', '.join(unsupported)}; expected one of {expected}"
        )
    return normalized


def _target_tables_for_asset_types(asset_types: list[str] | None) -> dict[str, Table]:
    base = {
        asset_type: DAILY_PRICE_TABLES[asset_type]
        for asset_type in ("stock", "etf", "fund", "index")
    }
    if asset_types is None:
        selected = base
    else:
        unsupported = [asset_type for asset_type in asset_types if asset_type not in base]
        if unsupported:
            expected = ", ".join(sorted(base))
            raise ValueError(
                f"unsupported asset type(s): {', '.join(unsupported)}; expected one of {expected}"
            )
        selected = {asset_type: base[asset_type] for asset_type in asset_types}
    return {price_table.name: price_table for price_table in selected.values()}


def _daily_price_table_for_name(target_table: str) -> Table:
    try:
        return DAILY_PRICE_TARGET_TABLES[target_table]
    except KeyError as exc:
        expected = ", ".join(sorted(DAILY_PRICE_TARGET_TABLES))
        raise ValueError(
            f"unsupported quarantine target_table {target_table!r}; expected one of {expected}"
        ) from exc


def _action_type_for_issue_type(issue_type: str) -> str:
    try:
        return ISSUE_TYPE_ACTIONS[issue_type]
    except KeyError as exc:
        expected = ", ".join(sorted(ISSUE_TYPE_ACTIONS))
        raise ValueError(
            f"unsupported issue_type {issue_type!r}; expected one of {expected}"
        ) from exc


def _mark_quarantine_plan_finished(
    connection: Connection,
    *,
    quarantine_plan_id: int,
    status: str,
    row_count: int,
    result_message: str,
) -> None:
    connection.execute(
        update(quarantine_plan)
        .where(quarantine_plan.c.quarantine_plan_id == quarantine_plan_id)
        .values(
            status=status,
            executed_at=_now_utc(),
            row_count=row_count,
            result_message=result_message,
        )
    )


def _claim_quarantine_plan(connection: Connection, *, quarantine_plan_id: int) -> None:
    result = connection.execute(
        update(quarantine_plan)
        .where(
            quarantine_plan.c.quarantine_plan_id == quarantine_plan_id,
            quarantine_plan.c.status == CONFIRMED,
        )
        .values(status=EXECUTING)
    )
    rowcount = getattr(result, "rowcount", 1)
    if rowcount != 1:
        raise ValueError(f"quarantine plan {quarantine_plan_id} was already claimed or changed status")


def _mark_issue_resolved(connection: Connection, *, issue_id: int) -> None:
    connection.execute(
        update(data_quality_issue)
        .where(data_quality_issue.c.issue_id == issue_id)
        .values(status="resolved", resolved_at=_now_utc())
    )


def _execution_result_message(
    *,
    action_type: str,
    issue_type: str,
    rows_quarantined: int,
    rows_deleted: int,
    issue_resolved: bool,
) -> str:
    resolution = "resolved" if issue_resolved else "still_open"
    if rows_quarantined == 0:
        return (
            f"action={action_type} issue_type={issue_type} rows_quarantined=0 "
            f"verification={resolution}; no source rows required deletion"
        )
    return (
        f"action={action_type} issue_type={issue_type} "
        f"rows_quarantined={rows_quarantined} rows_deleted={rows_deleted} "
        f"verification={resolution}"
    )


def _stable_json(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
