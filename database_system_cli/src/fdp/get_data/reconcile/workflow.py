"""Persistent run and checkpoint helpers for local Bulk reconciliation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import json
from typing import Any, Mapping

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.ingest.common import now_utc
from fdp.storage.tables import ingestion_task_run

CHECKPOINT_VERSION = 1
RECONCILE_JOB_NAME = "reconcile.bulk_unmatched"


@dataclass(frozen=True)
class ReconcileRunState:
    """One persisted workflow run and its validated checkpoint."""

    run_id: int
    status: str
    checkpoint: dict[str, Any]
    rows_fetched: int
    rows_inserted: int
    rows_updated: int
    rows_rejected: int
    api_calls: int
    error_message: str | None
    started_at: object
    finished_at: object


def new_reconcile_checkpoint(
    *,
    date_from: date,
    date_to: date,
    market: str,
    source_statuses: list[str],
    status_counts: Mapping[str, int],
    snapshot_max_by_status: Mapping[str, int],
) -> dict[str, Any]:
    """Build the versioned initial checkpoint for one immutable workflow scope."""
    first_status = source_statuses[0]
    return {
        "version": CHECKPOINT_VERSION,
        "phase": "classify",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "market": market.upper(),
        "source_statuses": list(source_statuses),
        "classify": {
            "status_counts": {key: int(value) for key, value in status_counts.items()},
            "snapshot_max_by_status": {
                key: int(value) for key, value in snapshot_max_by_status.items()
            },
            "status_index": 0,
            "current_status": first_status,
            "last_observation_id": 0,
            "last_trade_date": None,
            "rows_processed": 0,
            "batches_committed": 0,
            "target_status_counts": {},
        },
        "route": {
            "asset_types": [],
            "groups_total": None,
            "groups_processed": 0,
            "observations_selected": 0,
            "batches_committed": 0,
            "routed": 0,
            "shadowed": 0,
            "route_failed": 0,
            "rows_inserted": 0,
            "identity_audits": 0,
            "identity_quality_check_run_id": None,
            "identity_quality_issue_count": 0,
            "last_instrument_id": None,
            "last_trade_date": None,
        },
        "validation": {
            "quality_check_run_ids": [],
            "issue_count": 0,
        },
    }


def new_route_reconcile_checkpoint(
    *,
    date_from: date,
    date_to: date,
    market: str,
    asset_types: list[str],
) -> dict[str, Any]:
    """Build a route-first checkpoint for the deprecated standalone adapter."""
    checkpoint = new_reconcile_checkpoint(
        date_from=date_from,
        date_to=date_to,
        market=market,
        source_statuses=["unresolved"],
        status_counts={"unresolved": 0},
        snapshot_max_by_status={"unresolved": 0},
    )
    checkpoint["phase"] = "route"
    checkpoint["classify"]["status_index"] = 1
    checkpoint["classify"]["current_status"] = None
    checkpoint["route"]["asset_types"] = list(asset_types)
    return checkpoint


def create_reconcile_run(
    connection: Connection,
    *,
    checkpoint: Mapping[str, Any],
) -> int:
    """Persist one local workflow run and return its stable run ID.

    Input: validated initial checkpoint.
    Output: `system.ingestion_task_run.run_id`.
    Flow: immutable scope -> running task row -> durable workflow identity.
    """
    result = connection.execute(
        ingestion_task_run.insert().values(
            job_name=RECONCILE_JOB_NAME,
            market=checkpoint["market"],
            source="LOCAL",
            target_schema="system",
            target_table="bulk_unmatched_daily_price_observation",
            status="running",
            date_from=date.fromisoformat(str(checkpoint["date_from"])),
            date_to=date.fromisoformat(str(checkpoint["date_to"])),
            started_at=now_utc(),
            checkpoint_json=dict(checkpoint),
            api_calls=0,
        )
    )
    return int(result.inserted_primary_key[0])


def load_reconcile_run(connection: Connection, *, run_id: int) -> ReconcileRunState:
    """Load and validate one reconcile run without changing its status."""
    row = connection.execute(
        select(
            ingestion_task_run.c.run_id,
            ingestion_task_run.c.job_name,
            ingestion_task_run.c.status,
            ingestion_task_run.c.checkpoint_json,
            ingestion_task_run.c.rows_fetched,
            ingestion_task_run.c.rows_inserted,
            ingestion_task_run.c.rows_updated,
            ingestion_task_run.c.rows_rejected,
            ingestion_task_run.c.api_calls,
            ingestion_task_run.c.error_message,
            ingestion_task_run.c.started_at,
            ingestion_task_run.c.finished_at,
        ).where(ingestion_task_run.c.run_id == run_id)
    ).mappings().first()
    if row is None:
        raise ValueError(f"reconcile run_id {run_id} was not found")
    if row["job_name"] != RECONCILE_JOB_NAME:
        raise ValueError(f"run_id {run_id} is not a Bulk unmatched reconcile workflow")
    checkpoint = parse_reconcile_checkpoint(row["checkpoint_json"])
    return ReconcileRunState(
        run_id=int(row["run_id"]),
        status=str(row["status"]),
        checkpoint=checkpoint,
        rows_fetched=int(row["rows_fetched"] or 0),
        rows_inserted=int(row["rows_inserted"] or 0),
        rows_updated=int(row["rows_updated"] or 0),
        rows_rejected=int(row["rows_rejected"] or 0),
        api_calls=int(row["api_calls"] or 0),
        error_message=row["error_message"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def parse_reconcile_checkpoint(value: object) -> dict[str, Any]:
    """Decode one database JSON value and enforce the supported version/shape."""
    if isinstance(value, str):
        decoded = json.loads(value)
    elif isinstance(value, Mapping):
        decoded = dict(value)
    else:
        raise ValueError("reconcile run has no readable checkpoint_json")
    if decoded.get("version") != CHECKPOINT_VERSION:
        raise ValueError(
            f"unsupported reconcile checkpoint version: {decoded.get('version')!r}"
        )
    required = {
        "phase",
        "date_from",
        "date_to",
        "market",
        "source_statuses",
        "classify",
        "route",
        "validation",
    }
    missing = required - set(decoded)
    if missing:
        raise ValueError(f"reconcile checkpoint is missing fields: {sorted(missing)}")
    if decoded["phase"] not in {"classify", "route", "validation", "complete"}:
        raise ValueError(f"unsupported reconcile checkpoint phase: {decoded['phase']!r}")
    try:
        date_from = date.fromisoformat(str(decoded["date_from"]))
        date_to = date.fromisoformat(str(decoded["date_to"]))
    except ValueError as exc:
        raise ValueError("reconcile checkpoint contains an invalid date scope") from exc
    if date_to < date_from:
        raise ValueError("reconcile checkpoint date_to precedes date_from")
    if not isinstance(decoded["market"], str) or not decoded["market"].strip():
        raise ValueError("reconcile checkpoint market must be a non-empty string")
    statuses = decoded["source_statuses"]
    if not isinstance(statuses, list) or not statuses or not all(
        isinstance(status, str) and status for status in statuses
    ):
        raise ValueError("reconcile checkpoint source_statuses must be a non-empty list")
    for section in ("classify", "route", "validation"):
        if not isinstance(decoded[section], Mapping):
            raise ValueError(f"reconcile checkpoint {section} must be a mapping")
    return deepcopy(decoded)


def assert_reconcile_scope(
    checkpoint: Mapping[str, Any],
    *,
    date_from: date,
    date_to: date,
    market: str,
    source_statuses: list[str],
) -> None:
    """Reject resume attempts that would reinterpret an existing run."""
    expected = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "market": market.upper(),
        "source_statuses": list(source_statuses),
    }
    actual = {key: checkpoint.get(key) for key in expected}
    if actual != expected:
        raise ValueError(
            "resume scope does not match persisted checkpoint: "
            f"expected={actual} requested={expected}"
        )


def assert_reconcile_route_scope(
    checkpoint: Mapping[str, Any],
    *,
    date_from: date,
    date_to: date,
    market: str,
    asset_types: list[str],
) -> None:
    """Reject route resumes that change the persisted date, market, or table set."""
    expected = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "market": market.upper(),
    }
    actual = {key: checkpoint.get(key) for key in expected}
    if actual != expected:
        raise ValueError(
            "route resume scope does not match persisted checkpoint: "
            f"expected={actual} requested={expected}"
        )
    persisted_assets = list(checkpoint.get("route", {}).get("asset_types") or [])
    if persisted_assets and persisted_assets != list(asset_types):
        raise ValueError(
            "route resume asset_types do not match persisted checkpoint: "
            f"expected={persisted_assets} requested={asset_types}"
        )


def save_reconcile_checkpoint(
    connection: Connection,
    *,
    run_id: int,
    checkpoint: Mapping[str, Any],
    status: str = "running",
    rows_fetched: int | None = None,
    rows_inserted: int | None = None,
    rows_updated: int | None = None,
    rows_rejected: int | None = None,
    error_message: str | None = None,
    finished: bool = False,
) -> None:
    """Update checkpoint and aggregate facts in the caller's transaction."""
    values: dict[str, object] = {
        "checkpoint_json": dict(checkpoint),
        "status": status,
        "api_calls": 0,
        "error_message": error_message,
        "finished_at": now_utc() if finished else None,
    }
    optional = {
        "rows_fetched": rows_fetched,
        "rows_inserted": rows_inserted,
        "rows_updated": rows_updated,
        "rows_rejected": rows_rejected,
    }
    values.update({key: value for key, value in optional.items() if value is not None})
    result = connection.execute(
        update(ingestion_task_run)
        .where(
            ingestion_task_run.c.run_id == run_id,
            ingestion_task_run.c.job_name == RECONCILE_JOB_NAME,
        )
        .values(**values)
    )
    rowcount = getattr(result, "rowcount", None)
    if rowcount not in (None, -1, 1):
        raise RuntimeError(f"reconcile run {run_id} disappeared during checkpoint update")
