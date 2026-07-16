"""Repair-plan builders for human-confirmed data fixes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import load_daily_prices_for_instrument_ids
from fdp.storage.tables import (
    DAILY_PRICE_TABLES,
    US_SHARE_SCHEMA,
    data_quality_issue,
    instrument,
    repair_plan,
)

PENDING_CONFIRMATION = "pending_confirmation"
CONFIRMED = "confirmed"
EXECUTING = "executing"
EXECUTED = "executed"
FAILED = "failed"
BACKFILL_MISSING_DAILY_PRICE = "backfill_missing_daily_price"
ACTIVE_REPAIR_STATUSES = {PENDING_CONFIRMATION, CONFIRMED, EXECUTING}

REPAIRABLE_DAILY_PRICE_TARGETS = {
    asset_type: table.name for asset_type, table in DAILY_PRICE_TABLES.items()
}
TARGET_TABLE_TO_ASSET_TYPE = {
    table_name: asset_type for asset_type, table_name in REPAIRABLE_DAILY_PRICE_TARGETS.items()
}


@dataclass(frozen=True)
class RepairPlanRecord:
    """One stored repair-plan row plus enough fields for CLI preview."""

    repair_plan_id: int | None
    issue_id: int
    market: str
    repair_type: str
    symbol: str
    provider_symbol: str
    date_from: date
    date_to: date
    status: str
    target_table: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-serializable representation."""
        return {
            "repair_plan_id": self.repair_plan_id,
            "issue_id": self.issue_id,
            "market": self.market,
            "repair_type": self.repair_type,
            "symbol": self.symbol,
            "provider_symbol": self.provider_symbol,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "status": self.status,
            "target_table": self.target_table,
        }


@dataclass(frozen=True)
class MissingDailyPriceRepairPlanResult:
    """Summary returned after creating missing daily-price repair plans."""

    date_from: date
    date_to: date
    asset_types: list[str]
    eligible_issues: int
    existing_plans: int
    plans_created: int
    created_plans: list[RepairPlanRecord]


@dataclass(frozen=True)
class RepairExecutionResult:
    """Summary returned after attempting one confirmed repair plan."""

    repair_plan_id: int
    issue_id: int
    repair_type: str
    asset_type: str
    target_table: str
    status: str
    ingest_run_id: int
    rows_fetched: int
    rows_inserted: int
    rows_rejected: int
    api_calls: int
    issue_resolved: bool
    result_message: str

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-serializable representation."""
        return {
            "repair_plan_id": self.repair_plan_id,
            "issue_id": self.issue_id,
            "repair_type": self.repair_type,
            "asset_type": self.asset_type,
            "target_table": self.target_table,
            "status": self.status,
            "ingest_run_id": self.ingest_run_id,
            "rows_fetched": self.rows_fetched,
            "rows_inserted": self.rows_inserted,
            "rows_rejected": self.rows_rejected,
            "api_calls": self.api_calls,
            "issue_resolved": self.issue_resolved,
            "result_message": self.result_message,
        }


def create_missing_daily_price_repair_plans(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    asset_types: list[str] | None = None,
    market: str = "US",
) -> MissingDailyPriceRepairPlanResult:
    """Create repair plans from open missing daily-price data-quality issues.

    Input: date range, market, and asset types to scan.
    Output: count summary and created plan previews.
    Flow: open missing_trade_date issues -> existing-plan filter -> repair_plan rows.
    """
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")

    selected_asset_types = _normalize_asset_types(asset_types)
    target_tables = [REPAIRABLE_DAILY_PRICE_TARGETS[asset_type] for asset_type in selected_asset_types]
    issue_rows = _missing_daily_price_issue_rows(
        connection,
        date_from=date_from,
        date_to=date_to,
        market=market,
        target_tables=target_tables,
    )
    issue_keys = [_issue_logical_key(row) for row in issue_rows]
    existing_issue_keys = _logical_keys_with_active_repair_plans(connection, issue_keys)

    seen_issue_keys: set[tuple[str, int, date]] = set()
    created_plans: list[RepairPlanRecord] = []
    for row in issue_rows:
        issue_key = _issue_logical_key(row)
        if issue_key in seen_issue_keys or issue_key in existing_issue_keys:
            continue
        seen_issue_keys.add(issue_key)
        created_plans.append(_repair_plan_record_from_issue(row))
    if created_plans:
        connection.execute(
            repair_plan.insert().values([_insert_row_from_record(record) for record in created_plans])
        )

    return MissingDailyPriceRepairPlanResult(
        date_from=date_from,
        date_to=date_to,
        asset_types=selected_asset_types,
        eligible_issues=len(issue_rows),
        existing_plans=len(existing_issue_keys),
        plans_created=len(created_plans),
        created_plans=created_plans,
    )


def list_repair_plans(
    connection: Connection,
    *,
    statuses: list[str] | None = None,
    limit: int = 50,
) -> list[RepairPlanRecord]:
    """List repair plans for operator review."""
    if limit <= 0:
        raise ValueError("limit must be positive")

    statement = (
        select(
            repair_plan.c.repair_plan_id,
            repair_plan.c.issue_id,
            repair_plan.c.market,
            repair_plan.c.repair_type,
            repair_plan.c.symbol,
            repair_plan.c.provider_symbol,
            repair_plan.c.date_from,
            repair_plan.c.date_to,
            repair_plan.c.status,
            data_quality_issue.c.target_table,
        )
        .select_from(
            repair_plan.join(data_quality_issue, repair_plan.c.issue_id == data_quality_issue.c.issue_id)
        )
        .order_by(repair_plan.c.created_at.desc(), repair_plan.c.repair_plan_id.desc())
        .limit(limit)
    )
    if statuses:
        statement = statement.where(repair_plan.c.status.in_(statuses))

    return [_repair_plan_record_from_plan(row) for row in connection.execute(statement).mappings()]


def get_repair_plan(connection: Connection, *, repair_plan_id: int) -> RepairPlanRecord:
    """Return one repair plan or raise when the id is unknown."""
    row = connection.execute(
        select(
            repair_plan.c.repair_plan_id,
            repair_plan.c.issue_id,
            repair_plan.c.market,
            repair_plan.c.repair_type,
            repair_plan.c.symbol,
            repair_plan.c.provider_symbol,
            repair_plan.c.date_from,
            repair_plan.c.date_to,
            repair_plan.c.status,
            data_quality_issue.c.target_table,
        )
        .select_from(
            repair_plan.join(data_quality_issue, repair_plan.c.issue_id == data_quality_issue.c.issue_id)
        )
        .where(repair_plan.c.repair_plan_id == repair_plan_id)
    ).mappings().first()
    if row is None:
        raise ValueError(f"repair plan {repair_plan_id} not found")
    return _repair_plan_record_from_plan(row)


def confirm_repair_plan(connection: Connection, *, repair_plan_id: int) -> RepairPlanRecord:
    """Mark a pending repair plan as confirmed by the operator."""
    context = _get_repair_execution_context(connection, repair_plan_id=repair_plan_id)
    current = _repair_plan_record_from_plan(context)
    if current.status != PENDING_CONFIRMATION:
        raise ValueError(
            f"repair plan {repair_plan_id} has status {current.status!r}; "
            f"expected {PENDING_CONFIRMATION!r}"
        )
    if str(context["issue_status"]) != "open":
        raise ValueError(
            f"linked issue {current.issue_id} has status {context['issue_status']!r}; "
            "expected 'open'"
        )
    _validate_repair_execution_context(current, context)

    connection.execute(
        update(repair_plan)
        .where(repair_plan.c.repair_plan_id == repair_plan_id)
        .values(status=CONFIRMED, confirmed_at=_now_utc())
    )
    return get_repair_plan(connection, repair_plan_id=repair_plan_id)


def execute_repair_plan(
    connection: Connection,
    client: EodhdClient,
    *,
    repair_plan_id: int,
) -> RepairExecutionResult:
    """Execute one confirmed missing daily-price repair plan.

    Input: confirmed `repair_plan_id` and an EODHD client.
    Output: execution summary plus final plan/issue status.
    Flow: confirmed plan -> exact instrument backfill -> row-exists check -> close issue.
    """
    context = _get_repair_execution_context(connection, repair_plan_id=repair_plan_id)
    plan = _repair_plan_record_from_plan(context)
    instrument_id = int(context["instrument_id"])
    issue_status = str(context["issue_status"])
    target_table = str(context["target_table"])
    asset_type = _asset_type_for_target_table(target_table)

    if plan.status != CONFIRMED:
        raise ValueError(f"repair plan {repair_plan_id} has status {plan.status!r}; expected {CONFIRMED!r}")
    if issue_status != "open":
        raise ValueError(f"linked issue {plan.issue_id} has status {issue_status!r}; expected 'open'")
    if plan.repair_type != BACKFILL_MISSING_DAILY_PRICE:
        raise ValueError(f"unsupported repair_type {plan.repair_type!r}")
    _validate_repair_execution_context(plan, context)
    _claim_repair_plan(connection, repair_plan_id=repair_plan_id)

    load_result = load_daily_prices_for_instrument_ids(
        connection,
        client,
        instrument_ids=[instrument_id],
        date_from=plan.date_from,
        date_to=plan.date_to,
        market=plan.market,
        asset_types=[asset_type],
        job_name="eodhd_repair_daily_price",
        target_table=target_table,
    )
    issue_resolved = _daily_price_row_exists(
        connection,
        target_table=target_table,
        instrument_id=instrument_id,
        trade_date=plan.date_from,
    )
    result_message = _repair_result_message(
        ingest_run_id=load_result.run_id,
        load_status=load_result.status,
        rows_fetched=load_result.rows_fetched,
        rows_inserted=load_result.rows_inserted,
        rows_rejected=load_result.rows_rejected,
        error_message=load_result.error_message,
        issue_resolved=issue_resolved,
    )

    final_status = EXECUTED if issue_resolved else FAILED
    _mark_repair_plan_finished(
        connection,
        repair_plan_id=repair_plan_id,
        status=final_status,
        result_message=result_message,
    )
    if issue_resolved:
        _mark_missing_daily_price_issues_resolved(
            connection,
            market=plan.market,
            target_table=target_table,
            instrument_id=instrument_id,
            trade_date=plan.date_from,
        )

    return RepairExecutionResult(
        repair_plan_id=repair_plan_id,
        issue_id=plan.issue_id,
        repair_type=plan.repair_type,
        asset_type=asset_type,
        target_table=target_table,
        status=final_status,
        ingest_run_id=load_result.run_id,
        rows_fetched=load_result.rows_fetched,
        rows_inserted=load_result.rows_inserted,
        rows_rejected=load_result.rows_rejected,
        api_calls=load_result.api_calls,
        issue_resolved=issue_resolved,
        result_message=result_message,
    )


def _missing_daily_price_issue_rows(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str,
    target_tables: list[str],
) -> list[dict[str, Any]]:
    statement = (
        select(
            data_quality_issue.c.issue_id,
            data_quality_issue.c.market,
            data_quality_issue.c.target_schema,
            data_quality_issue.c.target_table,
            data_quality_issue.c.instrument_id,
            data_quality_issue.c.symbol.label("issue_symbol"),
            data_quality_issue.c.trade_date,
            instrument.c.symbol.label("instrument_symbol"),
            instrument.c.provider_symbol,
        )
        .select_from(
            data_quality_issue.join(
                instrument,
                data_quality_issue.c.instrument_id == instrument.c.instrument_id,
            )
        )
        .where(
            data_quality_issue.c.issue_type == "missing_trade_date",
            data_quality_issue.c.status == "open",
            data_quality_issue.c.market == market,
            data_quality_issue.c.target_schema == US_SHARE_SCHEMA,
            data_quality_issue.c.target_table.in_(target_tables),
            data_quality_issue.c.instrument_id.is_not(None),
            data_quality_issue.c.trade_date.is_not(None),
            data_quality_issue.c.trade_date.between(date_from, date_to),
        )
        .order_by(
            data_quality_issue.c.target_table,
            data_quality_issue.c.symbol,
            data_quality_issue.c.trade_date,
            data_quality_issue.c.issue_id,
        )
    )
    return [dict(row) for row in connection.execute(statement).mappings()]


def _issue_logical_key(row: dict[str, Any]) -> tuple[str, int, date]:
    trade_date = row["trade_date"]
    if not isinstance(trade_date, date):
        raise ValueError(f"issue {row['issue_id']} has invalid trade_date")
    return (str(row["target_table"]), int(row["instrument_id"]), trade_date)


def _logical_keys_with_active_repair_plans(
    connection: Connection,
    issue_keys: list[tuple[str, int, date]],
) -> set[tuple[str, int, date]]:
    if not issue_keys:
        return set()
    target_tables = sorted({target_table for target_table, _, _ in issue_keys})
    instrument_ids = sorted({instrument_id for _, instrument_id, _ in issue_keys})
    trade_dates = sorted({trade_date for _, _, trade_date in issue_keys})
    rows = connection.execute(
        select(
            data_quality_issue.c.target_table,
            data_quality_issue.c.instrument_id,
            data_quality_issue.c.trade_date,
        )
        .select_from(
            repair_plan.join(data_quality_issue, repair_plan.c.issue_id == data_quality_issue.c.issue_id)
        )
        .where(
            repair_plan.c.status.in_(sorted(ACTIVE_REPAIR_STATUSES)),
            data_quality_issue.c.issue_type == "missing_trade_date",
            data_quality_issue.c.status == "open",
            data_quality_issue.c.target_schema == US_SHARE_SCHEMA,
            data_quality_issue.c.target_table.in_(target_tables),
            data_quality_issue.c.instrument_id.in_(instrument_ids),
            data_quality_issue.c.trade_date.in_(trade_dates),
        )
    ).mappings()
    expected = set(issue_keys)
    return {
        (str(row["target_table"]), int(row["instrument_id"]), row["trade_date"])
        for row in rows
        if (str(row["target_table"]), int(row["instrument_id"]), row["trade_date"]) in expected
    }


def _repair_plan_record_from_issue(row: dict[str, Any]) -> RepairPlanRecord:
    issue_id = int(row["issue_id"])
    trade_date = row["trade_date"]
    if not isinstance(trade_date, date):
        raise ValueError(f"issue {issue_id} has invalid trade_date")

    issue_symbol = row.get("issue_symbol")
    instrument_symbol = row.get("instrument_symbol")
    symbol = str(issue_symbol or instrument_symbol)
    provider_symbol = str(row["provider_symbol"])

    return RepairPlanRecord(
        repair_plan_id=None,
        issue_id=issue_id,
        market=str(row["market"]),
        repair_type=BACKFILL_MISSING_DAILY_PRICE,
        symbol=symbol,
        provider_symbol=provider_symbol,
        date_from=trade_date,
        date_to=trade_date,
        status=PENDING_CONFIRMATION,
        target_table=str(row["target_table"]),
    )


def _repair_plan_record_from_plan(row: Any) -> RepairPlanRecord:
    target_table = row.get("target_table") if hasattr(row, "get") else None
    return RepairPlanRecord(
        repair_plan_id=int(row["repair_plan_id"]),
        issue_id=int(row["issue_id"]),
        market=str(row["market"]),
        repair_type=str(row["repair_type"]),
        symbol=str(row["symbol"]),
        provider_symbol=str(row["provider_symbol"]),
        date_from=row["date_from"],
        date_to=row["date_to"],
        status=str(row["status"]),
        target_table=str(target_table) if target_table is not None else None,
    )


def _insert_row_from_record(record: RepairPlanRecord) -> dict[str, object]:
    return {
        "issue_id": record.issue_id,
        "market": record.market,
        "repair_type": record.repair_type,
        "symbol": record.symbol,
        "provider_symbol": record.provider_symbol,
        "date_from": record.date_from,
        "date_to": record.date_to,
        "status": record.status,
    }


def _normalize_asset_types(asset_types: list[str] | None) -> list[str]:
    if asset_types is None:
        return ["stock", "etf", "fund", "index"]
    normalized = [asset_type.strip().lower() for asset_type in asset_types if asset_type.strip()]
    if not normalized:
        raise ValueError("asset_types must contain at least one asset type")
    unsupported = [asset_type for asset_type in normalized if asset_type not in REPAIRABLE_DAILY_PRICE_TARGETS]
    if unsupported:
        expected = ", ".join(REPAIRABLE_DAILY_PRICE_TARGETS)
        raise ValueError(f"unsupported asset type(s): {', '.join(unsupported)}; expected one of {expected}")
    return normalized


def _get_repair_execution_context(
    connection: Connection,
    *,
    repair_plan_id: int,
) -> dict[str, Any]:
    row = connection.execute(
        select(
            repair_plan.c.repair_plan_id,
            repair_plan.c.issue_id,
            repair_plan.c.market,
            repair_plan.c.repair_type,
            repair_plan.c.symbol,
            repair_plan.c.provider_symbol,
            repair_plan.c.date_from,
            repair_plan.c.date_to,
            repair_plan.c.status,
            data_quality_issue.c.target_schema,
            data_quality_issue.c.target_table,
            data_quality_issue.c.instrument_id,
            data_quality_issue.c.status.label("issue_status"),
            instrument.c.symbol.label("current_symbol"),
            instrument.c.provider_symbol.label("current_provider_symbol"),
            instrument.c.asset_type.label("instrument_asset_type"),
        )
        .select_from(
            repair_plan.join(
                data_quality_issue,
                repair_plan.c.issue_id == data_quality_issue.c.issue_id,
            ).join(
                instrument,
                data_quality_issue.c.instrument_id == instrument.c.instrument_id,
            )
        )
        .where(repair_plan.c.repair_plan_id == repair_plan_id)
    ).mappings().first()
    if row is None:
        raise ValueError(f"repair plan {repair_plan_id} not found")
    if row["instrument_id"] is None:
        raise ValueError(f"repair plan {repair_plan_id} is linked to an issue without instrument_id")
    return dict(row)


def _validate_repair_execution_context(plan: RepairPlanRecord, context: dict[str, Any]) -> None:
    target_schema = str(context["target_schema"])
    if target_schema != US_SHARE_SCHEMA:
        raise ValueError(
            f"unsupported repair target_schema {target_schema!r}; expected {US_SHARE_SCHEMA!r}"
        )

    current_provider_symbol = str(context["current_provider_symbol"])
    if plan.provider_symbol != current_provider_symbol:
        raise ValueError(
            f"repair plan provider_symbol {plan.provider_symbol!r} is stale; "
            f"current instrument provider_symbol is {current_provider_symbol!r}"
        )

    instrument_asset_type = str(context["instrument_asset_type"])
    expected_target_table = REPAIRABLE_DAILY_PRICE_TARGETS.get(instrument_asset_type)
    if expected_target_table != context["target_table"]:
        raise ValueError(
            f"repair target_table {context['target_table']!r} does not match "
            f"instrument asset_type {instrument_asset_type!r}"
        )


def _claim_repair_plan(connection: Connection, *, repair_plan_id: int) -> None:
    result = connection.execute(
        update(repair_plan)
        .where(
            repair_plan.c.repair_plan_id == repair_plan_id,
            repair_plan.c.status == CONFIRMED,
        )
        .values(status=EXECUTING)
    )
    rowcount = getattr(result, "rowcount", 1)
    if rowcount != 1:
        raise ValueError(f"repair plan {repair_plan_id} was already claimed or changed status")


def _asset_type_for_target_table(target_table: str) -> str:
    asset_type = TARGET_TABLE_TO_ASSET_TYPE.get(target_table)
    if asset_type is None:
        expected = ", ".join(sorted(TARGET_TABLE_TO_ASSET_TYPE))
        raise ValueError(f"unsupported repair target_table {target_table!r}; expected one of {expected}")
    return asset_type


def _daily_price_row_exists(
    connection: Connection,
    *,
    target_table: str,
    instrument_id: int,
    trade_date: date,
) -> bool:
    price_table = _daily_price_table_for_name(target_table)
    return bool(
        connection.execute(
            select(price_table.c.instrument_id)
            .where(
                price_table.c.instrument_id == instrument_id,
                price_table.c.trade_date == trade_date,
            )
            .limit(1)
        ).first()
    )


def _daily_price_table_for_name(target_table: str):
    tables = {table.name: table for table in DAILY_PRICE_TABLES.values()}
    try:
        return tables[target_table]
    except KeyError as exc:
        expected = ", ".join(sorted(tables))
        raise ValueError(f"unsupported repair target_table {target_table!r}; expected one of {expected}") from exc


def _repair_result_message(
    *,
    ingest_run_id: int,
    load_status: str,
    rows_fetched: int,
    rows_inserted: int,
    rows_rejected: int,
    error_message: str | None,
    issue_resolved: bool,
) -> str:
    parts = [
        f"ingest_run_id={ingest_run_id}",
        f"load_status={load_status}",
        f"rows_fetched={rows_fetched}",
        f"rows_inserted={rows_inserted}",
        f"rows_rejected={rows_rejected}",
        f"issue_resolved={issue_resolved}",
    ]
    if error_message:
        parts.append(f"error={error_message}")
    return "; ".join(parts)


def _mark_repair_plan_finished(
    connection: Connection,
    *,
    repair_plan_id: int,
    status: str,
    result_message: str,
) -> None:
    connection.execute(
        update(repair_plan)
        .where(repair_plan.c.repair_plan_id == repair_plan_id)
        .values(status=status, executed_at=_now_utc(), result_message=result_message)
    )


def _mark_missing_daily_price_issues_resolved(
    connection: Connection,
    *,
    market: str,
    target_table: str,
    instrument_id: int,
    trade_date: date,
) -> None:
    connection.execute(
        update(data_quality_issue)
        .where(
            data_quality_issue.c.issue_type == "missing_trade_date",
            data_quality_issue.c.status == "open",
            data_quality_issue.c.market == market,
            data_quality_issue.c.target_schema == US_SHARE_SCHEMA,
            data_quality_issue.c.target_table == target_table,
            data_quality_issue.c.instrument_id == instrument_id,
            data_quality_issue.c.trade_date == trade_date,
        )
        .values(status="resolved", resolved_at=_now_utc())
    )


def _now_utc() -> datetime:
    return datetime.now(UTC)
