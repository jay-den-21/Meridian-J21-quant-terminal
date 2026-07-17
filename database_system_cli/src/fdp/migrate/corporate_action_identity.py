"""Stock-only, event-date reconciliation for canonical corporate actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.engine import Connection, Engine

from fdp.sources.eodhd.corporate_action_identity import (
    CorporateActionIdentityResolver,
)
from fdp.storage.tables import (
    US_SHARE_SCHEMA,
    corporate_action,
    data_quality_check_run,
    data_quality_issue,
    instrument,
)

DEFAULT_CHUNK_SIZE = 1_000
PAYLOAD_COLUMNS = (
    "action_type",
    "action_date",
    "declaration_date",
    "record_date",
    "payment_date",
    "period",
    "cash_amount",
    "unadjusted_cash_amount",
    "currency",
    "split_ratio",
    "split_numerator",
    "split_denominator",
    "source",
)


@dataclass(frozen=True)
class CorporateActionIdentityPlan:
    """Read-only inventory before stock-only identity reconciliation."""

    total_rows: int
    current_stock_rows: int
    current_non_stock_rows: int
    dated_candidates: int
    rows_to_move_to_stock: int
    rows_to_merge_into_stock: int
    rows_to_remove_non_stock: int
    rows_to_quarantine: int
    conflicting_merges: int


@dataclass(frozen=True)
class CorporateActionIdentityResult:
    """Committed facts from stock-only corporate-action reconciliation."""

    status: str
    check_run_id: int
    rows_moved_to_stock: int
    rows_merged_into_stock: int
    rows_removed_non_stock: int
    rows_quarantined: int
    conflicting_merges: int
    remaining_non_stock_rows: int
    remaining_identity_conflicts: int


def plan_corporate_action_identity_reconcile(
    connection: Connection,
) -> CorporateActionIdentityPlan:
    """Classify current rows without mutating canonical or audit tables."""
    resolver = CorporateActionIdentityResolver.from_connection(connection, market="US")
    asset_types = _instrument_asset_types(connection)
    total_rows, stock_rows, non_stock_rows = _scope_counts(connection)
    counters = {
        "dated_candidates": 0,
        "rows_to_move_to_stock": 0,
        "rows_to_merge_into_stock": 0,
        "rows_to_remove_non_stock": 0,
        "rows_to_quarantine": 0,
        "conflicting_merges": 0,
    }
    moved_from_non_stock = 0
    merged_from_non_stock = 0
    stock_rows_with_non_stock_owner = 0
    for row in _candidate_rows(connection, resolver):
        counters["dated_candidates"] += 1
        source_asset_type = asset_types[int(row["instrument_id"])]
        resolution = resolver.resolve(
            provider_symbol=str(row["provider_symbol"]),
            action_date=row["action_date"],
        )
        target = resolution.instrument
        if target is None:
            counters["rows_to_quarantine"] += 1
            continue
        if str(target["asset_type"]) != "stock":
            if source_asset_type == "stock":
                stock_rows_with_non_stock_owner += 1
                counters["rows_to_quarantine"] += 1
            continue
        if int(target["instrument_id"]) == int(row["instrument_id"]):
            continue
        existing = _target_row(
            connection,
            instrument_id=int(target["instrument_id"]),
            row=row,
        )
        if existing is None:
            counters["rows_to_move_to_stock"] += 1
            if source_asset_type != "stock":
                moved_from_non_stock += 1
        else:
            counters["rows_to_merge_into_stock"] += 1
            if source_asset_type != "stock":
                merged_from_non_stock += 1
            if not _payload_matches(row, existing):
                counters["conflicting_merges"] += 1
                counters["rows_to_quarantine"] += 1

    counters["rows_to_remove_non_stock"] = (
        non_stock_rows
        - moved_from_non_stock
        - merged_from_non_stock
        + stock_rows_with_non_stock_owner
    )

    return CorporateActionIdentityPlan(
        total_rows=total_rows,
        current_stock_rows=stock_rows,
        current_non_stock_rows=non_stock_rows,
        **counters,
    )


def reconcile_corporate_action_identities(
    engine: Engine,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> CorporateActionIdentityResult:
    """Move dated stock events, archive unsafe rows, and remove all non-stock events."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    with engine.begin() as connection:
        resolver = CorporateActionIdentityResolver.from_connection(connection, market="US")
        asset_types = _instrument_asset_types(connection)
        check_run_id = _create_check_run(connection)

    try:
        return _execute_corporate_action_identity_reconcile(
            engine,
            resolver=resolver,
            asset_types=asset_types,
            check_run_id=check_run_id,
            chunk_size=chunk_size,
        )
    except Exception as exc:
        _mark_check_run_failed(engine, check_run_id=check_run_id, error=exc)
        raise


def _execute_corporate_action_identity_reconcile(
    engine: Engine,
    *,
    resolver: CorporateActionIdentityResolver,
    asset_types: dict[int, str],
    check_run_id: int,
    chunk_size: int,
) -> CorporateActionIdentityResult:
    """Execute resumable chunk transactions after the audit run exists."""

    moved = 0
    merged = 0
    removed_non_stock = 0
    quarantined = 0
    conflicting = 0
    last_id = 0
    bounded_symbols = resolver.bounded_provider_symbols
    while bounded_symbols:
        with engine.begin() as connection:
            rows = _next_candidate_chunk(
                connection,
                bounded_symbols=bounded_symbols,
                last_id=last_id,
                chunk_size=chunk_size,
            )
            if not rows:
                break
            for row in rows:
                resolution = resolver.resolve(
                    provider_symbol=str(row["provider_symbol"]),
                    action_date=row["action_date"],
                )
                target = resolution.instrument
                source_id = int(row["corporate_action_id"])
                source_asset_type = asset_types[int(row["instrument_id"])]
                if target is None:
                    _record_identity_issue(
                        connection,
                        check_run_id=check_run_id,
                        row=row,
                        issue_type="corporate_action_identity_unresolved",
                        reason=resolution.reason or "unresolved owner",
                        candidate_ids=resolution.candidate_instrument_ids,
                        canonical_action=(
                            "keep_unresolved_stock"
                            if source_asset_type == "stock"
                            else "delete_unresolved_non_stock"
                        ),
                    )
                    quarantined += 1
                    continue
                if str(target["asset_type"]) != "stock":
                    if source_asset_type == "stock":
                        _record_identity_issue(
                            connection,
                            check_run_id=check_run_id,
                            row=row,
                            issue_type="corporate_action_non_stock_dated_owner",
                            reason=(
                                "dated identifier history resolves the event to "
                                f"instrument_id={target['instrument_id']} "
                                f"asset_type={target['asset_type']}"
                            ),
                            candidate_ids=(int(target["instrument_id"]),),
                            canonical_action="delete_stock_row_with_non_stock_owner",
                        )
                        _delete_source(connection, source_id)
                        removed_non_stock += 1
                        quarantined += 1
                    continue
                target_id = int(target["instrument_id"])
                if target_id == int(row["instrument_id"]):
                    continue
                existing = _target_row(connection, instrument_id=target_id, row=row)
                if existing is not None:
                    if not _payload_matches(row, existing):
                        _record_identity_issue(
                            connection,
                            check_run_id=check_run_id,
                            row=row,
                            issue_type="corporate_action_identity_payload_conflict",
                            reason=(
                                "dated owner already has a different canonical payload; "
                                f"target_corporate_action_id={existing['corporate_action_id']}"
                            ),
                            candidate_ids=(target_id,),
                            canonical_action="keep_existing_stock_delete_conflict",
                        )
                        quarantined += 1
                        conflicting += 1
                    _delete_source(connection, source_id)
                    merged += 1
                    continue
                result = connection.execute(
                    update(corporate_action)
                    .where(corporate_action.c.corporate_action_id == source_id)
                    .values(instrument_id=target_id, symbol=str(target["symbol"]))
                )
                if result.rowcount != 1:
                    raise RuntimeError(
                        f"corporate-action move count mismatch for id={source_id}"
                    )
                moved += 1
            last_id = int(rows[-1]["corporate_action_id"])

    while True:
        with engine.begin() as connection:
            source_ids = [
                int(value)
                for value in connection.execute(
                    select(corporate_action.c.corporate_action_id)
                    .select_from(
                        corporate_action.join(
                            instrument,
                            corporate_action.c.instrument_id == instrument.c.instrument_id,
                        )
                    )
                    .where(instrument.c.asset_type != "stock")
                    .order_by(corporate_action.c.corporate_action_id)
                    .limit(chunk_size)
                ).scalars()
            ]
            if not source_ids:
                break
            result = connection.execute(
                delete(corporate_action).where(
                    corporate_action.c.corporate_action_id.in_(source_ids)
                )
            )
            if result.rowcount != len(source_ids):
                raise RuntimeError(
                    "non-stock corporate-action delete count mismatch: "
                    f"expected={len(source_ids)} actual={result.rowcount}"
                )
            removed_non_stock += len(source_ids)

    with engine.begin() as connection:
        remaining_non_stock = _scope_counts(connection)[2]
        remaining_conflicts = _remaining_identity_conflicts(connection, resolver)
        check_status = (
            "success"
            if remaining_non_stock == 0 and remaining_conflicts == 0
            else "failed"
        )
        error_parts = []
        if remaining_non_stock:
            error_parts.append(f"remaining_non_stock_rows={remaining_non_stock}")
        if remaining_conflicts:
            error_parts.append(f"remaining_identity_conflicts={remaining_conflicts}")
        connection.execute(
            update(data_quality_check_run)
            .where(data_quality_check_run.c.check_run_id == check_run_id)
            .values(
                status=check_status,
                finished_at=_now_utc(),
                issues_found=quarantined,
                error_message="; ".join(error_parts) or None,
            )
        )
    status = (
        "completed"
        if remaining_non_stock == 0 and remaining_conflicts == 0
        else "partial_failed"
    )
    return CorporateActionIdentityResult(
        status=status,
        check_run_id=check_run_id,
        rows_moved_to_stock=moved,
        rows_merged_into_stock=merged,
        rows_removed_non_stock=removed_non_stock,
        rows_quarantined=quarantined,
        conflicting_merges=conflicting,
        remaining_non_stock_rows=remaining_non_stock,
        remaining_identity_conflicts=remaining_conflicts,
    )


def _scope_counts(connection: Connection) -> tuple[int, int, int]:
    row = connection.execute(
        select(
            func.count().label("total"),
            func.sum(case((instrument.c.asset_type == "stock", 1), else_=0)).label("stock"),
            func.sum(case((instrument.c.asset_type != "stock", 1), else_=0)).label(
                "non_stock"
            ),
        ).select_from(
            corporate_action.join(
                instrument,
                corporate_action.c.instrument_id == instrument.c.instrument_id,
            )
        )
    ).mappings().one()
    return int(row["total"] or 0), int(row["stock"] or 0), int(row["non_stock"] or 0)


def _instrument_asset_types(connection: Connection) -> dict[int, str]:
    return {
        int(row.instrument_id): str(row.asset_type)
        for row in connection.execute(
            select(instrument.c.instrument_id, instrument.c.asset_type)
        ).all()
    }


def _candidate_rows(
    connection: Connection,
    resolver: CorporateActionIdentityResolver,
) -> list[dict[str, Any]]:
    symbols = resolver.bounded_provider_symbols
    if not symbols:
        return []
    return [
        dict(row)
        for row in connection.execute(
            select(*corporate_action.c)
            .where(corporate_action.c.provider_symbol.in_(symbols))
            .order_by(corporate_action.c.corporate_action_id)
        ).mappings()
    ]


def _next_candidate_chunk(
    connection: Connection,
    *,
    bounded_symbols: tuple[str, ...],
    last_id: int,
    chunk_size: int,
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            select(*corporate_action.c)
            .where(
                corporate_action.c.provider_symbol.in_(bounded_symbols),
                corporate_action.c.corporate_action_id > last_id,
            )
            .order_by(corporate_action.c.corporate_action_id)
            .limit(chunk_size)
        ).mappings()
    ]


def _target_row(
    connection: Connection,
    *,
    instrument_id: int,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    found = connection.execute(
        select(*corporate_action.c).where(
            corporate_action.c.instrument_id == instrument_id,
            corporate_action.c.action_type == row["action_type"],
            corporate_action.c.action_date == row["action_date"],
            corporate_action.c.source == row["source"],
        )
    ).mappings().one_or_none()
    return None if found is None else dict(found)


def _payload_matches(source: dict[str, Any], target: dict[str, Any]) -> bool:
    return all(source.get(column) == target.get(column) for column in PAYLOAD_COLUMNS)


def _delete_source(connection: Connection, source_id: int) -> None:
    result = connection.execute(
        delete(corporate_action).where(
            corporate_action.c.corporate_action_id == source_id
        )
    )
    if result.rowcount != 1:
        raise RuntimeError(f"corporate-action delete count mismatch for id={source_id}")


def _create_check_run(connection: Connection) -> int:
    result = connection.execute(
        data_quality_check_run.insert().values(
            market="US",
            target_schema=US_SHARE_SCHEMA,
            target_table="corporate_action",
            check_scope="corporate_action_identity_stock_only_reconcile",
            status="running",
            started_at=_now_utc(),
        )
    )
    return int(result.inserted_primary_key[0])


def _mark_check_run_failed(
    engine: Engine,
    *,
    check_run_id: int,
    error: Exception,
) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(
                update(data_quality_check_run)
                .where(data_quality_check_run.c.check_run_id == check_run_id)
                .values(
                    status="failed",
                    finished_at=_now_utc(),
                    error_message=f"{type(error).__name__}: {error}"[:1000],
                )
            )
    except Exception as finalization_error:
        error.add_note(
            "failed to finalize corporate-action identity check run: "
            f"{type(finalization_error).__name__}: {finalization_error}"
        )


def _record_identity_issue(
    connection: Connection,
    *,
    check_run_id: int,
    row: dict[str, Any],
    issue_type: str,
    reason: str,
    candidate_ids: tuple[int, ...],
    canonical_action: str,
) -> None:
    connection.execute(
        data_quality_issue.insert().values(
            check_run_id=check_run_id,
            market="US",
            target_schema=US_SHARE_SCHEMA,
            target_table="corporate_action",
            issue_type=issue_type,
            severity="error",
            instrument_id=row["instrument_id"],
            symbol=row["symbol"],
            trade_date=row["action_date"],
            details=json.dumps(
                {
                    "reason": reason,
                    "candidate_instrument_ids": candidate_ids,
                    "canonical_action": canonical_action,
                    "canonical_row": row,
                },
                sort_keys=True,
                default=str,
            ),
            status="open",
        )
    )


def _remaining_identity_conflicts(
    connection: Connection,
    resolver: CorporateActionIdentityResolver,
) -> int:
    conflicts = 0
    for row in _candidate_rows(connection, resolver):
        resolution = resolver.resolve(
            provider_symbol=str(row["provider_symbol"]),
            action_date=row["action_date"],
        )
        target = resolution.instrument
        if (
            target is None
            or str(target["asset_type"]) != "stock"
            or int(target["instrument_id"]) != int(row["instrument_id"])
        ):
            conflicts += 1
    return conflicts


def _now_utc() -> datetime:
    return datetime.now(UTC)
