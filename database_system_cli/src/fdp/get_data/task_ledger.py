"""Durable task identity, lease, and work-unit helpers for resumable ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import os
import socket
from threading import Event, Lock, Thread
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from sqlalchemy import Select, func, select, update
from sqlalchemy.engine import Connection, Engine

from fdp.storage.tables import ingestion_task_run, ingestion_task_work_unit

TASK_WORKFLOW_VERSION = 1
DAILY_DATA_CONTRACT_VERSION = "eodhd-bulk-daily-v2"
DEFAULT_LEASE_SECONDS = 300
COMPLETED_UNIT_STATUSES = frozenset({"success", "reused"})
INVOCATION_TERMINAL_UNIT_STATUSES = frozenset({"success", "reused", "held"})
REUSABLE_QUALITY_STATUS = "verified"
RESUMABLE_PARENT_STATUSES = frozenset(
    {"running", "cancelled", "failed", "partial_failed"}
)


class TaskAlreadyRunningError(ValueError):
    """Raised when an equivalent task still owns a non-expired lease."""

    def __init__(self, *, run_id: int, lease_owner: str | None, lease_expires_at: object) -> None:
        self.run_id = run_id
        self.lease_owner = lease_owner
        self.lease_expires_at = lease_expires_at
        super().__init__(
            "equivalent task is already running: "
            f"run_id={run_id} owner={lease_owner or '-'} "
            f"lease_expires_at={lease_expires_at or '-'}"
        )


@dataclass(frozen=True)
class DailyTaskScope:
    """Immutable data meaning used to identify one Bulk Daily task.

    Operational knobs such as worker count, output language, rate limit, and API
    budget are deliberately absent. A symbol filter is included because a small
    filtered request cannot safely satisfy a full-exchange request.
    """

    source: str
    market: str
    exchange: str
    date_from: date
    date_to: date
    asset_types: tuple[str, ...]
    instrument_status: str
    symbols: tuple[str, ...] = ()
    data_contract_version: str = DAILY_DATA_CONTRACT_VERSION

    @classmethod
    def create(
        cls,
        *,
        source: str,
        market: str,
        exchange: str,
        date_from: date,
        date_to: date,
        asset_types: Sequence[str],
        instrument_status: str,
        symbols: Sequence[str] = (),
        data_contract_version: str = DAILY_DATA_CONTRACT_VERSION,
    ) -> DailyTaskScope:
        if date_to < date_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        normalized_assets = tuple(sorted({str(value).strip().lower() for value in asset_types}))
        if not normalized_assets:
            raise ValueError("asset_types must not be empty")
        normalized_symbols = tuple(
            sorted({str(value).strip().upper() for value in symbols if str(value).strip()})
        )
        return cls(
            source=source.strip().lower(),
            market=market.strip().upper(),
            exchange=exchange.strip().upper(),
            date_from=date_from,
            date_to=date_to,
            asset_types=normalized_assets,
            instrument_status=instrument_status.strip().lower(),
            symbols=normalized_symbols,
            data_contract_version=data_contract_version,
        )

    def payload(self) -> dict[str, object]:
        return {
            "source": self.source,
            "market": self.market,
            "exchange": self.exchange,
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "asset_types": list(self.asset_types),
            "instrument_status": self.instrument_status,
            "symbols": list(self.symbols),
            "data_contract_version": self.data_contract_version,
        }

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(self.payload())

    def unit_fingerprint(self, trade_date: date) -> str:
        return stable_fingerprint(
            {
                "source": self.source,
                "market": self.market,
                "exchange": self.exchange,
                "trade_date": trade_date.isoformat(),
                "asset_types": list(self.asset_types),
                "instrument_status": self.instrument_status,
                "symbols": list(self.symbols),
                "data_contract_version": self.data_contract_version,
            }
        )

    @property
    def series_fingerprint(self) -> str:
        return stable_fingerprint(
            {
                "source": self.source,
                "market": self.market,
                "exchange": self.exchange,
                "asset_types": list(self.asset_types),
                "instrument_status": self.instrument_status,
                "symbols": list(self.symbols),
                "data_contract_version": self.data_contract_version,
            }
        )


@dataclass(frozen=True)
class WorkUnitState:
    work_unit_id: int
    run_id: int
    unit_key: str
    unit_fingerprint: str
    series_fingerprint: str
    status: str
    attempt_count: int
    reused_from_work_unit_id: int | None
    rows_fetched: int
    rows_published: int
    rows_pending: int
    rows_rejected: int
    api_calls: int
    api_units: int
    quality_status: str | None
    metrics: dict[str, object]

    @property
    def trade_date(self) -> date:
        return date.fromisoformat(self.unit_key)

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> WorkUnitState:
        metrics = row.get("metrics_json")
        return cls(
            work_unit_id=int(row["work_unit_id"]),
            run_id=int(row["run_id"]),
            unit_key=str(row["unit_key"]),
            unit_fingerprint=str(row["unit_fingerprint"]),
            series_fingerprint=str(row["series_fingerprint"]),
            status=str(row["status"]),
            attempt_count=int(row.get("attempt_count") or 0),
            reused_from_work_unit_id=(
                int(row["reused_from_work_unit_id"])
                if row.get("reused_from_work_unit_id") is not None
                else None
            ),
            rows_fetched=int(row.get("rows_fetched") or 0),
            rows_published=int(row.get("rows_published") or 0),
            rows_pending=int(row.get("rows_pending") or 0),
            rows_rejected=int(row.get("rows_rejected") or 0),
            api_calls=int(row.get("api_calls") or 0),
            api_units=int(row.get("api_units") or 0),
            quality_status=(
                str(row["quality_status"])
                if row.get("quality_status") is not None
                else None
            ),
            metrics=dict(metrics) if isinstance(metrics, Mapping) else {},
        )


@dataclass(frozen=True)
class TaskAcquisition:
    run_id: int
    task_fingerprint: str
    work_units: tuple[WorkUnitState, ...]
    resumed: bool
    no_op: bool
    new_run: bool
    reused_work_units: int
    supersedes_run_id: int | None
    checkpoint: dict[str, object]

    @property
    def pending_work_units(self) -> tuple[WorkUnitState, ...]:
        return tuple(
            unit
            for unit in self.work_units
            if unit.status not in COMPLETED_UNIT_STATUSES
        )


@dataclass(frozen=True)
class DailyTaskEstimate:
    """Read-only estimate of provider work still required for one task scope."""

    work_units_total: int
    provider_work_units: int
    reusable_work_units: int
    exact_no_op: bool
    existing_run_id: int | None


def stable_fingerprint(payload: Mapping[str, object]) -> str:
    """Return a deterministic SHA-256 fingerprint for JSON-compatible values."""
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    """Return a naive UTC timestamp suitable for MySQL DATETIME columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def default_lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"


class TaskLedger:
    """Persist exact task identity, leases, and per-date work-unit checkpoints."""

    def __init__(
        self,
        *,
        lease_owner: str | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.lease_owner = lease_owner or default_lease_owner()
        self.lease_seconds = lease_seconds

    def acquire_daily_task(
        self,
        connection: Connection,
        *,
        scope: DailyTaskScope,
        trade_dates: Sequence[date],
        new_run: bool = False,
        manual: bool = False,
        now: datetime | None = None,
    ) -> TaskAcquisition:
        """Acquire/resume an exact task and create missing per-date units atomically."""
        requested_dates = tuple(sorted(set(trade_dates)))
        if not requested_dates:
            raise ValueError("trade_dates must not be empty")
        if requested_dates[0] < scope.date_from or requested_dates[-1] > scope.date_to:
            raise ValueError("trade_dates fall outside the immutable task scope")
        timestamp = now or utc_now()
        lease_expires_at = timestamp + timedelta(seconds=self.lease_seconds)
        task_fingerprint = scope.fingerprint

        active = connection.execute(
            select(ingestion_task_run)
            .where(ingestion_task_run.c.active_resume_key == task_fingerprint)
            .with_for_update()
        ).mappings().first()

        resumed = False
        supersedes_run_id: int | None = None
        if active is not None:
            active_run_id = int(active["run_id"])
            if self._lease_is_live(active, timestamp):
                raise TaskAlreadyRunningError(
                    run_id=active_run_id,
                    lease_owner=(
                        str(active["lease_owner"])
                        if active.get("lease_owner") is not None
                        else None
                    ),
                    lease_expires_at=active.get("lease_expires_at"),
                )
            if new_run:
                supersedes_run_id = active_run_id
                connection.execute(
                    update(ingestion_task_run)
                    .where(ingestion_task_run.c.run_id == active_run_id)
                    .values(
                        status="superseded",
                        active_resume_key=None,
                        lease_owner=None,
                        lease_expires_at=None,
                        heartbeat_at=timestamp,
                        finished_at=timestamp,
                        error_message="superseded by an explicit --new-run",
                    )
                )
                active = None
            else:
                resumed = True
                run_id = active_run_id
                connection.execute(
                    update(ingestion_task_run)
                    .where(ingestion_task_run.c.run_id == run_id)
                    .values(
                        status="running",
                        lease_owner=self.lease_owner,
                        lease_expires_at=lease_expires_at,
                        heartbeat_at=timestamp,
                        finished_at=None,
                        error_message=None,
                    )
                )
                connection.execute(
                    update(ingestion_task_work_unit)
                    .where(
                        ingestion_task_work_unit.c.run_id == run_id,
                        ingestion_task_work_unit.c.status == "running",
                    )
                    .values(
                        status="pending",
                        error_message="recovered after an expired task lease",
                        started_at=None,
                        finished_at=None,
                    )
                )

        completed = self._latest_completed_task(connection, task_fingerprint)
        if active is None and completed is not None and not new_run:
            run_id = int(completed["run_id"])
            work_units = self.load_work_units(connection, run_id=run_id)
            checkpoint = self._checkpoint(completed)
            return TaskAcquisition(
                run_id=run_id,
                task_fingerprint=task_fingerprint,
                work_units=tuple(work_units),
                resumed=False,
                no_op=True,
                new_run=False,
                reused_work_units=sum(unit.status == "reused" for unit in work_units),
                supersedes_run_id=None,
                checkpoint=checkpoint,
            )

        if active is None:
            if supersedes_run_id is None and new_run and completed is not None:
                supersedes_run_id = int(completed["run_id"])
            checkpoint = self._new_checkpoint(
                scope=scope,
                work_units_total=len(requested_dates),
                manual=manual,
                new_run=new_run,
            )
            result = connection.execute(
                ingestion_task_run.insert().values(
                    job_name="eodhd_bulk_daily_workflow",
                    market=scope.market,
                    source=scope.source.upper(),
                    target_schema="us_share",
                    target_table=",".join(
                        f"{asset_type}_daily_price" for asset_type in scope.asset_types
                    ),
                    status="running",
                    date_from=scope.date_from,
                    date_to=scope.date_to,
                    started_at=timestamp,
                    checkpoint_json=checkpoint,
                    task_fingerprint=task_fingerprint,
                    active_resume_key=task_fingerprint,
                    workflow_version=TASK_WORKFLOW_VERSION,
                    supersedes_run_id=supersedes_run_id,
                    lease_owner=self.lease_owner,
                    lease_expires_at=lease_expires_at,
                    heartbeat_at=timestamp,
                )
            )
            run_id = int(result.inserted_primary_key[0])
            reusable = (
                {}
                if new_run
                else self._load_reusable_units(
                    connection,
                    [scope.unit_fingerprint(value) for value in requested_dates],
                )
            )
            rows: list[dict[str, object]] = []
            for trade_date in requested_dates:
                unit_fingerprint = scope.unit_fingerprint(trade_date)
                prior = reusable.get(unit_fingerprint)
                if prior is None:
                    rows.append(
                        {
                            "run_id": run_id,
                            "unit_type": "trade_date",
                            "unit_key": trade_date.isoformat(),
                            "unit_fingerprint": unit_fingerprint,
                            "series_fingerprint": scope.series_fingerprint,
                            "status": "pending",
                            "reused_from_work_unit_id": None,
                            "evidence_run_id": None,
                            "rows_fetched": 0,
                            "rows_published": 0,
                            "rows_pending": 0,
                            "rows_rejected": 0,
                            "api_calls": 0,
                            "api_units": 0,
                            "response_hash": None,
                            "quality_status": None,
                            "metrics_json": None,
                            "error_message": None,
                            "finished_at": None,
                        }
                    )
                    continue
                rows.append(
                    {
                        "run_id": run_id,
                        "unit_type": "trade_date",
                        "unit_key": trade_date.isoformat(),
                        "unit_fingerprint": unit_fingerprint,
                        "series_fingerprint": scope.series_fingerprint,
                        "status": "reused",
                        "reused_from_work_unit_id": int(prior["work_unit_id"]),
                        "evidence_run_id": int(prior["run_id"]),
                        "rows_fetched": int(prior.get("rows_fetched") or 0),
                        "rows_published": int(prior.get("rows_published") or 0),
                        "rows_pending": int(prior.get("rows_pending") or 0),
                        "rows_rejected": int(prior.get("rows_rejected") or 0),
                        "api_calls": 0,
                        "api_units": 0,
                        "response_hash": prior.get("response_hash"),
                        "quality_status": REUSABLE_QUALITY_STATUS,
                        "metrics_json": prior.get("metrics_json"),
                        "error_message": None,
                        "finished_at": timestamp,
                    }
                )
            connection.execute(ingestion_task_work_unit.insert(), rows)
        else:
            run_id = int(active["run_id"])
            checkpoint = self._checkpoint(active)
            self._insert_missing_units(
                connection,
                run_id=run_id,
                scope=scope,
                trade_dates=requested_dates,
            )

        work_units = self.load_work_units(connection, run_id=run_id)
        expected_keys = {value.isoformat() for value in requested_dates}
        actual_keys = {unit.unit_key for unit in work_units}
        if actual_keys != expected_keys:
            raise RuntimeError(
                "persisted task work units do not match requested scope: "
                f"missing={sorted(expected_keys - actual_keys)} "
                f"unexpected={sorted(actual_keys - expected_keys)}"
            )
        return TaskAcquisition(
            run_id=run_id,
            task_fingerprint=task_fingerprint,
            work_units=tuple(work_units),
            resumed=resumed,
            no_op=False,
            new_run=new_run,
            reused_work_units=sum(unit.status == "reused" for unit in work_units),
            supersedes_run_id=supersedes_run_id,
            checkpoint=checkpoint,
        )

    def estimate_daily_task(
        self,
        connection: Connection,
        *,
        scope: DailyTaskScope,
        trade_dates: Sequence[date],
        new_run: bool = False,
    ) -> DailyTaskEstimate:
        """Estimate pending provider dates without acquiring a lease or writing rows."""
        requested_dates = tuple(sorted(set(trade_dates)))
        if not requested_dates:
            raise ValueError("trade_dates must not be empty")
        if new_run:
            return DailyTaskEstimate(
                work_units_total=len(requested_dates),
                provider_work_units=len(requested_dates),
                reusable_work_units=0,
                exact_no_op=False,
                existing_run_id=None,
            )

        active = connection.execute(
            select(ingestion_task_run).where(
                ingestion_task_run.c.active_resume_key == scope.fingerprint
            )
        ).mappings().first()
        if active is not None:
            run_id = int(active["run_id"])
            units = self.load_work_units(connection, run_id=run_id)
            expected_keys = {value.isoformat() for value in requested_dates}
            actual_keys = {unit.unit_key for unit in units}
            missing = expected_keys - actual_keys
            provider_units = sum(
                unit.unit_key in expected_keys
                and unit.status not in COMPLETED_UNIT_STATUSES
                for unit in units
            ) + len(missing)
            return DailyTaskEstimate(
                work_units_total=len(requested_dates),
                provider_work_units=provider_units,
                reusable_work_units=sum(
                    unit.unit_key in expected_keys and unit.status == "reused"
                    for unit in units
                ),
                exact_no_op=False,
                existing_run_id=run_id,
            )

        completed = self._latest_completed_task(connection, scope.fingerprint)
        if completed is not None:
            return DailyTaskEstimate(
                work_units_total=len(requested_dates),
                provider_work_units=0,
                reusable_work_units=0,
                exact_no_op=True,
                existing_run_id=int(completed["run_id"]),
            )

        fingerprints = [scope.unit_fingerprint(value) for value in requested_dates]
        reusable = self._load_reusable_units(connection, fingerprints)
        return DailyTaskEstimate(
            work_units_total=len(requested_dates),
            provider_work_units=len(requested_dates) - len(reusable),
            reusable_work_units=len(reusable),
            exact_no_op=False,
            existing_run_id=None,
        )

    def assert_no_live_equivalent_task(
        self,
        connection: Connection,
        *,
        scope: DailyTaskScope,
        now: datetime | None = None,
    ) -> None:
        """Reject an equivalent live lease before any provider request is made."""
        row = connection.execute(
            select(ingestion_task_run).where(
                ingestion_task_run.c.active_resume_key == scope.fingerprint
            )
        ).mappings().first()
        if row is not None and self._lease_is_live(row, now or utc_now()):
            raise TaskAlreadyRunningError(
                run_id=int(row["run_id"]),
                lease_owner=(
                    str(row["lease_owner"])
                    if row.get("lease_owner") is not None
                    else None
                ),
                lease_expires_at=row.get("lease_expires_at"),
            )

    def completed_daily_task(
        self,
        connection: Connection,
        *,
        scope: DailyTaskScope,
    ) -> TaskAcquisition | None:
        """Return an exact completed task without acquiring a lease or writing."""
        row = self._latest_completed_task(connection, scope.fingerprint)
        if row is None:
            return None
        run_id = int(row["run_id"])
        units = self.load_work_units(connection, run_id=run_id)
        return TaskAcquisition(
            run_id=run_id,
            task_fingerprint=scope.fingerprint,
            work_units=tuple(units),
            resumed=False,
            no_op=True,
            new_run=False,
            reused_work_units=sum(unit.status == "reused" for unit in units),
            supersedes_run_id=None,
            checkpoint=self._checkpoint(row),
        )

    def load_work_units(
        self,
        connection: Connection,
        *,
        run_id: int,
    ) -> list[WorkUnitState]:
        rows = connection.execute(
            select(ingestion_task_work_unit)
            .where(ingestion_task_work_unit.c.run_id == run_id)
            .order_by(ingestion_task_work_unit.c.unit_key)
        ).mappings()
        return [WorkUnitState.from_row(row) for row in rows]

    def recent_verified_units(
        self,
        connection: Connection,
        *,
        series_fingerprint: str,
        before_trade_date: date,
        limit: int = 5,
    ) -> list[WorkUnitState]:
        """Load the nearest prior verified dates used for thin-response checks."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = connection.execute(
            select(ingestion_task_work_unit)
            .where(
                ingestion_task_work_unit.c.series_fingerprint == series_fingerprint,
                ingestion_task_work_unit.c.unit_key < before_trade_date.isoformat(),
                ingestion_task_work_unit.c.status.in_(("success", "reused")),
                ingestion_task_work_unit.c.quality_status == REUSABLE_QUALITY_STATUS,
            )
            .order_by(ingestion_task_work_unit.c.unit_key.desc())
            .limit(limit)
        ).mappings()
        return [WorkUnitState.from_row(row) for row in rows]

    def claim_work_unit(
        self,
        connection: Connection,
        *,
        run_id: int,
        work_unit_id: int,
        now: datetime | None = None,
    ) -> WorkUnitState:
        timestamp = now or utc_now()
        self._assert_lease(connection, run_id=run_id, now=timestamp)
        result = connection.execute(
            update(ingestion_task_work_unit)
            .where(
                ingestion_task_work_unit.c.work_unit_id == work_unit_id,
                ingestion_task_work_unit.c.run_id == run_id,
                ingestion_task_work_unit.c.status.in_(
                    ("pending", "held", "failed", "cancelled")
                ),
            )
            .values(
                status="running",
                attempt_count=ingestion_task_work_unit.c.attempt_count + 1,
                started_at=timestamp,
                finished_at=None,
                error_message=None,
                updated_at=timestamp,
            )
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"work unit {work_unit_id} is not claimable for run_id={run_id}"
            )
        return self._load_work_unit(connection, work_unit_id=work_unit_id)

    def finish_work_unit(
        self,
        connection: Connection,
        *,
        run_id: int,
        work_unit_id: int,
        status: str,
        rows_fetched: int,
        rows_published: int,
        rows_pending: int,
        rows_rejected: int,
        api_calls: int,
        api_units: int,
        response_hash: str | None,
        quality_status: str | None,
        metrics: Mapping[str, object] | None = None,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> None:
        if status not in {"success", "held", "failed", "cancelled"}:
            raise ValueError(f"unsupported work-unit terminal status: {status}")
        counters = (
            rows_fetched,
            rows_published,
            rows_pending,
            rows_rejected,
            api_calls,
            api_units,
        )
        if any(value < 0 for value in counters):
            raise ValueError("work-unit counters must not be negative")
        timestamp = now or utc_now()
        result = connection.execute(
            update(ingestion_task_work_unit)
            .where(
                ingestion_task_work_unit.c.work_unit_id == work_unit_id,
                ingestion_task_work_unit.c.run_id == run_id,
                ingestion_task_work_unit.c.status == "running",
            )
            .values(
                status=status,
                rows_fetched=rows_fetched,
                rows_published=rows_published,
                rows_pending=rows_pending,
                rows_rejected=rows_rejected,
                api_calls=api_calls,
                api_units=api_units,
                response_hash=response_hash,
                quality_status=quality_status,
                metrics_json=dict(metrics or {}),
                error_message=error_message,
                finished_at=timestamp,
                updated_at=timestamp,
            )
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"work unit {work_unit_id} was not running for run_id={run_id}"
            )
        self.heartbeat(connection, run_id=run_id, now=timestamp)

    def heartbeat(
        self,
        connection: Connection,
        *,
        run_id: int,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or utc_now()
        result = connection.execute(
            update(ingestion_task_run)
            .where(
                ingestion_task_run.c.run_id == run_id,
                ingestion_task_run.c.lease_owner == self.lease_owner,
                ingestion_task_run.c.active_resume_key.is_not(None),
            )
            .values(
                heartbeat_at=timestamp,
                lease_expires_at=timestamp + timedelta(seconds=self.lease_seconds),
            )
        )
        if result.rowcount != 1:
            raise RuntimeError(f"task lease was lost for run_id={run_id}")

    def set_phase(
        self,
        connection: Connection,
        *,
        run_id: int,
        phase: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        row = connection.execute(
            select(ingestion_task_run.c.checkpoint_json).where(
                ingestion_task_run.c.run_id == run_id
            )
        ).first()
        if row is None:
            raise ValueError(f"task run_id={run_id} does not exist")
        checkpoint = self._checkpoint({"checkpoint_json": row[0]})
        checkpoint["phase"] = phase
        if details:
            checkpoint.update(dict(details))
        result = connection.execute(
            update(ingestion_task_run)
            .where(ingestion_task_run.c.run_id == run_id)
            .values(checkpoint_json=checkpoint)
        )
        if result.rowcount != 1:
            raise RuntimeError(f"task run_id={run_id} disappeared during phase update")

    def mark_units_verified(self, connection: Connection, *, run_id: int) -> None:
        timestamp = utc_now()
        connection.execute(
            update(ingestion_task_work_unit)
            .where(
                ingestion_task_work_unit.c.run_id == run_id,
                ingestion_task_work_unit.c.status.in_(("success", "reused")),
            )
            .values(
                quality_status=REUSABLE_QUALITY_STATUS,
                updated_at=timestamp,
            )
        )
        self.heartbeat(connection, run_id=run_id, now=timestamp)

    def finalize_task(
        self,
        connection: Connection,
        *,
        run_id: int,
        review_required: bool,
        cancelled: bool = False,
        error_message: str | None = None,
        details: Mapping[str, object] | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Aggregate committed units and release or preserve the resume key."""
        timestamp = now or utc_now()
        units = self.load_work_units(connection, run_id=run_id)
        if not units:
            raise RuntimeError(f"task run_id={run_id} has no work units")
        counts: dict[str, int] = {}
        for unit in units:
            counts[unit.status] = counts.get(unit.status, 0) + 1
        invocation_terminal = sum(
            counts.get(value, 0) for value in INVOCATION_TERMINAL_UNIT_STATUSES
        )
        invocation_complete = invocation_terminal == len(units)
        durable_complete = all(
            unit.status in COMPLETED_UNIT_STATUSES for unit in units
        )
        if cancelled:
            status = "cancelled"
        elif invocation_complete:
            status = "success"
        elif invocation_terminal:
            status = "partial_failed"
        else:
            status = "failed"

        row = connection.execute(
            select(ingestion_task_run.c.checkpoint_json).where(
                ingestion_task_run.c.run_id == run_id
            )
        ).first()
        if row is None:
            raise ValueError(f"task run_id={run_id} does not exist")
        checkpoint = self._checkpoint({"checkpoint_json": row[0]})
        checkpoint.update(
            {
                "phase": (
                    "complete"
                    if durable_complete
                    else "review" if invocation_complete else "fetch"
                ),
                "durable_complete": durable_complete,
                "review_required": bool(review_required),
                "work_unit_status_counts": dict(sorted(counts.items())),
                "last_finished_at": timestamp.isoformat(),
            }
        )
        if details:
            checkpoint.update(dict(details))
        rows_fetched = sum(unit.rows_fetched for unit in units)
        rows_published = sum(unit.rows_published for unit in units)
        rows_pending = sum(unit.rows_pending for unit in units)
        rows_rejected = sum(unit.rows_rejected for unit in units)
        api_calls = sum(unit.api_calls for unit in units)
        api_units = sum(unit.api_units for unit in units)
        checkpoint.update(
            {
                "rows_fetched": rows_fetched,
                "rows_published": rows_published,
                "rows_pending": rows_pending,
                "rows_rejected": rows_rejected,
                "api_calls": api_calls,
                "api_units": api_units,
            }
        )
        update_values: dict[str, object] = {
            "status": status,
            "finished_at": timestamp,
            "rows_fetched": rows_fetched,
            "rows_inserted": rows_published,
            "rows_updated": 0,
            # Preserve the legacy aggregate while checkpoint_json keeps the two
            # distinct counters available to programmatic readers.
            "rows_rejected": rows_rejected + rows_pending,
            "api_calls": api_calls,
            "error_message": error_message,
            "checkpoint_json": checkpoint,
            "lease_owner": None,
            "lease_expires_at": None,
            "heartbeat_at": timestamp,
        }
        if durable_complete:
            update_values["active_resume_key"] = None
        result = connection.execute(
            update(ingestion_task_run)
            .where(
                ingestion_task_run.c.run_id == run_id,
                ingestion_task_run.c.lease_owner == self.lease_owner,
            )
            .values(**update_values)
        )
        if result.rowcount != 1:
            raise RuntimeError(f"task lease was lost before finalizing run_id={run_id}")
        return {
            "status": status,
            "complete": durable_complete,
            "invocation_complete": invocation_complete,
            "review_required": bool(review_required),
            "work_unit_status_counts": counts,
            "rows_fetched": rows_fetched,
            "rows_published": rows_published,
            "rows_pending": rows_pending,
            "rows_rejected": rows_rejected,
            "api_calls": api_calls,
            "api_units": api_units,
            "checkpoint": checkpoint,
        }

    def task_status(self, connection: Connection, *, run_id: int) -> dict[str, object]:
        row = connection.execute(
            select(ingestion_task_run).where(ingestion_task_run.c.run_id == run_id)
        ).mappings().first()
        if row is None:
            raise ValueError(f"task run_id={run_id} does not exist")
        units = self.load_work_units(connection, run_id=run_id)
        return self._task_payload(row, units)

    def load_work_unit(
        self,
        connection: Connection,
        *,
        work_unit_id: int,
    ) -> WorkUnitState:
        """Load one work unit without exposing private persistence helpers."""
        return self._load_work_unit(connection, work_unit_id=work_unit_id)

    def list_tasks(
        self,
        connection: Connection,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement: Select[Any] = select(ingestion_task_run).where(
            ingestion_task_run.c.task_fingerprint.is_not(None)
        )
        if status is not None:
            statement = statement.where(ingestion_task_run.c.status == status)
        rows = connection.execute(
            statement.order_by(ingestion_task_run.c.run_id.desc()).limit(limit)
        ).mappings()
        return [self._task_payload(row, []) for row in rows]

    def unfinished_task_count(self, connection: Connection) -> int:
        """Count resumable tasks that still retain their active scope key."""
        return int(
            connection.execute(
                select(func.count())
                .select_from(ingestion_task_run)
                .where(
                    ingestion_task_run.c.task_fingerprint.is_not(None),
                    ingestion_task_run.c.active_resume_key.is_not(None),
                )
            ).scalar_one()
        )

    @staticmethod
    def _lease_is_live(row: Mapping[str, object], now: datetime) -> bool:
        if str(row.get("status")) != "running":
            return False
        expires_at = row.get("lease_expires_at")
        if not isinstance(expires_at, datetime):
            return True
        if expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone(UTC).replace(tzinfo=None)
        return expires_at > now

    @staticmethod
    def _checkpoint(row: Mapping[str, object]) -> dict[str, object]:
        value = row.get("checkpoint_json")
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str):
            decoded = json.loads(value)
            if isinstance(decoded, Mapping):
                return dict(decoded)
        return {}

    @staticmethod
    def _new_checkpoint(
        *,
        scope: DailyTaskScope,
        work_units_total: int,
        manual: bool,
        new_run: bool,
    ) -> dict[str, object]:
        return {
            "version": TASK_WORKFLOW_VERSION,
            "workflow": "bulk_daily",
            "phase": "fetch",
            "scope": scope.payload(),
            "work_units_total": work_units_total,
            "review_required": False,
            "invocation": {"manual": bool(manual), "new_run": bool(new_run)},
        }

    @staticmethod
    def _latest_completed_task(
        connection: Connection,
        task_fingerprint: str,
    ) -> Mapping[str, object] | None:
        return connection.execute(
            select(ingestion_task_run)
            .where(
                ingestion_task_run.c.task_fingerprint == task_fingerprint,
                ingestion_task_run.c.status == "success",
                ingestion_task_run.c.active_resume_key.is_(None),
            )
            .order_by(ingestion_task_run.c.run_id.desc())
            .limit(1)
        ).mappings().first()

    @staticmethod
    def _chunks(values: Sequence[str], size: int = 500) -> Iterable[Sequence[str]]:
        for offset in range(0, len(values), size):
            yield values[offset : offset + size]

    def _load_reusable_units(
        self,
        connection: Connection,
        unit_fingerprints: Sequence[str],
    ) -> dict[str, Mapping[str, object]]:
        reusable: dict[str, Mapping[str, object]] = {}
        for chunk in self._chunks(unit_fingerprints):
            rows = connection.execute(
                select(ingestion_task_work_unit)
                .where(
                    ingestion_task_work_unit.c.unit_fingerprint.in_(chunk),
                    ingestion_task_work_unit.c.status.in_(("success", "reused")),
                    ingestion_task_work_unit.c.quality_status
                    == REUSABLE_QUALITY_STATUS,
                )
                .order_by(ingestion_task_work_unit.c.work_unit_id.desc())
            ).mappings()
            for row in rows:
                reusable.setdefault(str(row["unit_fingerprint"]), row)
        return reusable

    @staticmethod
    def _insert_missing_units(
        connection: Connection,
        *,
        run_id: int,
        scope: DailyTaskScope,
        trade_dates: Sequence[date],
    ) -> None:
        existing = set(
            connection.execute(
                select(ingestion_task_work_unit.c.unit_key).where(
                    ingestion_task_work_unit.c.run_id == run_id
                )
            ).scalars()
        )
        rows = [
            {
                "run_id": run_id,
                "unit_type": "trade_date",
                "unit_key": trade_date.isoformat(),
                "unit_fingerprint": scope.unit_fingerprint(trade_date),
                "series_fingerprint": scope.series_fingerprint,
                "status": "pending",
            }
            for trade_date in trade_dates
            if trade_date.isoformat() not in existing
        ]
        if rows:
            connection.execute(ingestion_task_work_unit.insert(), rows)

    def _assert_lease(
        self,
        connection: Connection,
        *,
        run_id: int,
        now: datetime,
    ) -> None:
        row = connection.execute(
            select(
                ingestion_task_run.c.lease_owner,
                ingestion_task_run.c.lease_expires_at,
                ingestion_task_run.c.active_resume_key,
            ).where(ingestion_task_run.c.run_id == run_id)
        ).mappings().first()
        if row is None:
            raise ValueError(f"task run_id={run_id} does not exist")
        if row.get("lease_owner") != self.lease_owner:
            raise RuntimeError(f"task lease owner changed for run_id={run_id}")
        if row.get("active_resume_key") is None:
            raise RuntimeError(f"task run_id={run_id} is no longer resumable")
        expires_at = row.get("lease_expires_at")
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is not None:
                expires_at = expires_at.astimezone(UTC).replace(tzinfo=None)
            if expires_at <= now:
                raise RuntimeError(f"task lease expired for run_id={run_id}")

    @staticmethod
    def _load_work_unit(connection: Connection, *, work_unit_id: int) -> WorkUnitState:
        row = connection.execute(
            select(ingestion_task_work_unit).where(
                ingestion_task_work_unit.c.work_unit_id == work_unit_id
            )
        ).mappings().one()
        return WorkUnitState.from_row(row)

    @staticmethod
    def _task_payload(
        row: Mapping[str, object],
        units: Sequence[WorkUnitState],
    ) -> dict[str, object]:
        counts: dict[str, int] = {}
        for unit in units:
            counts[unit.status] = counts.get(unit.status, 0) + 1
        checkpoint = TaskLedger._checkpoint(row)
        return {
            "run_id": int(row["run_id"]),
            "job_name": str(row["job_name"]),
            "status": str(row["status"]),
            "market": str(row["market"]),
            "source": str(row["source"]),
            "date_from": row.get("date_from"),
            "date_to": row.get("date_to"),
            "task_fingerprint": row.get("task_fingerprint"),
            "active_resume_key": row.get("active_resume_key"),
            "workflow_version": row.get("workflow_version"),
            "supersedes_run_id": row.get("supersedes_run_id"),
            "lease_owner": row.get("lease_owner"),
            "lease_expires_at": row.get("lease_expires_at"),
            "heartbeat_at": row.get("heartbeat_at"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "rows_fetched": int(checkpoint.get("rows_fetched", row.get("rows_fetched")) or 0),
            "rows_published": int(
                checkpoint.get("rows_published", row.get("rows_inserted")) or 0
            ),
            "rows_pending": int(checkpoint.get("rows_pending") or 0),
            "rows_rejected": int(
                checkpoint.get("rows_rejected", row.get("rows_rejected")) or 0
            ),
            "api_calls": int(checkpoint.get("api_calls", row.get("api_calls")) or 0),
            "api_units": int(checkpoint.get("api_units") or 0),
            "checkpoint": checkpoint,
            "work_unit_status_counts": dict(sorted(counts.items())),
        }


class TaskLeaseHeartbeat:
    """Keep one durable task lease alive while work runs outside DB transactions.

    Input: SQLAlchemy engine, the lease-owning ledger, and a run ID.
    Output: periodic committed heartbeat updates or a surfaced lease-loss error.
    Flow: synchronous first pulse -> daemon heartbeat loop -> stop and verify.
    """

    def __init__(
        self,
        *,
        engine: Engine,
        ledger: TaskLedger,
        run_id: int,
        interval_seconds: float | None = None,
    ) -> None:
        default_interval = min(max(ledger.lease_seconds / 3, 1.0), 60.0)
        self.engine = engine
        self.ledger = ledger
        self.run_id = run_id
        self.interval_seconds = interval_seconds or default_interval
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._error: BaseException | None = None

    def __enter__(self) -> TaskLeaseHeartbeat:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop(raise_error=exc is None)

    def start(self) -> None:
        """Commit an immediate pulse and start the periodic heartbeat thread."""
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("task lease heartbeat is already running")
            self._pulse()
            self._thread = Thread(
                target=self._run,
                name=f"j21-task-heartbeat-{self.run_id}",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, raise_error: bool = True) -> None:
        """Stop the heartbeat thread and surface any lease/database failure."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(self.interval_seconds + 5.0, 10.0))
            if thread.is_alive():
                raise RuntimeError(
                    f"task lease heartbeat did not stop for run_id={self.run_id}"
                )
        if raise_error:
            self.raise_if_failed()

    def raise_if_failed(self) -> None:
        """Raise the first asynchronous heartbeat error, if one occurred."""
        if self._error is not None:
            raise RuntimeError(
                f"task lease heartbeat failed for run_id={self.run_id}: {self._error}"
            ) from self._error

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self._pulse()
            except BaseException as exc:  # pragma: no cover - defensive thread boundary
                self._error = exc
                self._stop.set()
                return

    def _pulse(self) -> None:
        with self.engine.begin() as connection:
            self.ledger.heartbeat(connection, run_id=self.run_id)
