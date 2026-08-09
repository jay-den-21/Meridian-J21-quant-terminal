from contextlib import contextmanager
from datetime import date, datetime
from time import sleep

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from fdp.get_data.task_ledger import (
    DailyTaskScope,
    TaskAlreadyRunningError,
    TaskLeaseHeartbeat,
    TaskLedger,
)


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS system")
        connection.exec_driver_sql(
            """
            CREATE TABLE system.ingestion_task_run (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL,
                market TEXT NOT NULL,
                source TEXT NOT NULL,
                target_schema TEXT NOT NULL,
                target_table TEXT NOT NULL,
                status TEXT NOT NULL,
                date_from DATE,
                date_to DATE,
                started_at DATETIME NOT NULL,
                finished_at DATETIME,
                rows_fetched INTEGER NOT NULL DEFAULT 0,
                rows_inserted INTEGER NOT NULL DEFAULT 0,
                rows_updated INTEGER NOT NULL DEFAULT 0,
                rows_rejected INTEGER NOT NULL DEFAULT 0,
                api_calls INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                config_hash TEXT,
                code_version TEXT,
                checkpoint_json JSON,
                task_fingerprint TEXT,
                active_resume_key TEXT UNIQUE,
                workflow_version INTEGER,
                supersedes_run_id INTEGER,
                lease_owner TEXT,
                lease_expires_at DATETIME,
                heartbeat_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE system.ingestion_task_work_unit (
                work_unit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                unit_type TEXT NOT NULL,
                unit_key TEXT NOT NULL,
                unit_fingerprint TEXT NOT NULL,
                series_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                reused_from_work_unit_id INTEGER,
                evidence_run_id INTEGER,
                rows_fetched INTEGER NOT NULL DEFAULT 0,
                rows_published INTEGER NOT NULL DEFAULT 0,
                rows_pending INTEGER NOT NULL DEFAULT 0,
                rows_rejected INTEGER NOT NULL DEFAULT 0,
                api_calls INTEGER NOT NULL DEFAULT 0,
                api_units INTEGER NOT NULL DEFAULT 0,
                response_hash TEXT,
                quality_status TEXT,
                metrics_json JSON,
                error_message TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (run_id, unit_key)
            )
            """
        )
    return engine


def _scope(date_from: date, date_to: date) -> DailyTaskScope:
    return DailyTaskScope.create(
        source="eodhd",
        market="US",
        exchange="US",
        date_from=date_from,
        date_to=date_to,
        asset_types=["fund", "stock", "etf"],
        instrument_status="all",
    )


def _finish_success(
    ledger: TaskLedger,
    connection,
    *,
    run_id: int,
    work_unit_id: int,
) -> None:
    ledger.claim_work_unit(
        connection,
        run_id=run_id,
        work_unit_id=work_unit_id,
    )
    ledger.finish_work_unit(
        connection,
        run_id=run_id,
        work_unit_id=work_unit_id,
        status="success",
        rows_fetched=100,
        rows_published=90,
        rows_pending=10,
        rows_rejected=0,
        api_calls=1,
        api_units=100,
        response_hash="a" * 64,
        quality_status="response_verified",
        metrics={"rows_matched": 90, "asset_type_counts": {"stock": 100}},
    )


def test_task_scope_is_stable_across_asset_order_and_operational_knobs() -> None:
    first = _scope(date(2024, 1, 2), date(2024, 1, 3))
    second = DailyTaskScope.create(
        source="EODHD",
        market="us",
        exchange="us",
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 3),
        asset_types=["etf", "stock", "fund", "stock"],
        instrument_status="ALL",
    )

    assert first.fingerprint == second.fingerprint
    assert first.unit_fingerprint(date(2024, 1, 2)) == second.unit_fingerprint(
        date(2024, 1, 2)
    )


def test_interrupted_task_auto_resumes_and_completed_scope_is_no_op() -> None:
    engine = _engine()
    scope = _scope(date(2024, 1, 2), date(2024, 1, 3))
    first_ledger = TaskLedger(lease_owner="first", lease_seconds=60)
    with engine.begin() as connection:
        task = first_ledger.acquire_daily_task(
            connection,
            scope=scope,
            trade_dates=[date(2024, 1, 2), date(2024, 1, 3)],
        )
        _finish_success(
            first_ledger,
            connection,
            run_id=task.run_id,
            work_unit_id=task.work_units[0].work_unit_id,
        )
        partial = first_ledger.finalize_task(
            connection,
            run_id=task.run_id,
            review_required=False,
        )
    assert partial["status"] == "partial_failed"

    second_ledger = TaskLedger(lease_owner="second", lease_seconds=60)
    with engine.begin() as connection:
        resumed = second_ledger.acquire_daily_task(
            connection,
            scope=scope,
            trade_dates=[date(2024, 1, 2), date(2024, 1, 3)],
        )
        assert resumed.resumed is True
        assert [unit.unit_key for unit in resumed.pending_work_units] == ["2024-01-03"]
        _finish_success(
            second_ledger,
            connection,
            run_id=resumed.run_id,
            work_unit_id=resumed.pending_work_units[0].work_unit_id,
        )
        second_ledger.mark_units_verified(connection, run_id=resumed.run_id)
        completed = second_ledger.finalize_task(
            connection,
            run_id=resumed.run_id,
            review_required=False,
        )
    assert completed["status"] == "success"

    with engine.connect() as connection:
        no_op = TaskLedger(lease_owner="third").completed_daily_task(
            connection,
            scope=scope,
        )
    assert no_op is not None
    assert no_op.no_op is True
    assert no_op.run_id == task.run_id


def test_overlapping_scope_reuses_only_verified_work_units() -> None:
    engine = _engine()
    first_scope = _scope(date(2024, 1, 2), date(2024, 1, 2))
    ledger = TaskLedger(lease_owner="first")
    with engine.begin() as connection:
        first = ledger.acquire_daily_task(
            connection,
            scope=first_scope,
            trade_dates=[date(2024, 1, 2)],
        )
        _finish_success(
            ledger,
            connection,
            run_id=first.run_id,
            work_unit_id=first.work_units[0].work_unit_id,
        )
        ledger.mark_units_verified(connection, run_id=first.run_id)
        ledger.finalize_task(connection, run_id=first.run_id, review_required=False)

    expanded_scope = _scope(date(2024, 1, 2), date(2024, 1, 3))
    expanded_ledger = TaskLedger(lease_owner="expanded")
    with engine.begin() as connection:
        expanded = expanded_ledger.acquire_daily_task(
            connection,
            scope=expanded_scope,
            trade_dates=[date(2024, 1, 2), date(2024, 1, 3)],
        )
    assert expanded.reused_work_units == 1
    assert [unit.status for unit in expanded.work_units] == ["reused", "pending"]


def test_new_run_ignores_reuse_and_live_lease_rejects_concurrency() -> None:
    engine = _engine()
    scope = _scope(date(2024, 1, 2), date(2024, 1, 2))
    first = TaskLedger(lease_owner="first", lease_seconds=60)
    with engine.begin() as connection:
        active = first.acquire_daily_task(
            connection,
            scope=scope,
            trade_dates=[date(2024, 1, 2)],
            now=datetime(2024, 1, 3, 0, 0),
        )

    with engine.begin() as connection:
        with pytest.raises(TaskAlreadyRunningError, match=f"run_id={active.run_id}"):
            TaskLedger(lease_owner="second").acquire_daily_task(
                connection,
                scope=scope,
                trade_dates=[date(2024, 1, 2)],
                new_run=True,
                now=datetime(2024, 1, 3, 0, 0, 30),
            )

    with engine.begin() as connection:
        fresh = TaskLedger(lease_owner="second").acquire_daily_task(
            connection,
            scope=scope,
            trade_dates=[date(2024, 1, 2)],
            new_run=True,
            now=datetime(2024, 1, 3, 0, 2),
        )
    assert fresh.run_id != active.run_id
    assert fresh.reused_work_units == 0
    assert fresh.work_units[0].status == "pending"
    assert fresh.supersedes_run_id == active.run_id


def test_preflight_estimate_counts_only_unfinished_or_unverified_dates() -> None:
    engine = _engine()
    first_scope = _scope(date(2024, 1, 2), date(2024, 1, 2))
    ledger = TaskLedger(lease_owner="first")
    with engine.begin() as connection:
        first = ledger.acquire_daily_task(
            connection,
            scope=first_scope,
            trade_dates=[date(2024, 1, 2)],
        )
        _finish_success(
            ledger,
            connection,
            run_id=first.run_id,
            work_unit_id=first.work_units[0].work_unit_id,
        )
        ledger.mark_units_verified(connection, run_id=first.run_id)
        ledger.finalize_task(connection, run_id=first.run_id, review_required=False)

    expanded_scope = _scope(date(2024, 1, 2), date(2024, 1, 3))
    with engine.connect() as connection:
        estimate = TaskLedger().estimate_daily_task(
            connection,
            scope=expanded_scope,
            trade_dates=[date(2024, 1, 2), date(2024, 1, 3)],
        )
        exact = TaskLedger().estimate_daily_task(
            connection,
            scope=first_scope,
            trade_dates=[date(2024, 1, 2)],
        )

    assert estimate.provider_work_units == 1
    assert estimate.reusable_work_units == 1
    assert exact.exact_no_op is True
    assert exact.provider_work_units == 0


def test_held_unit_finishes_invocation_but_remains_resumable() -> None:
    engine = _engine()
    scope = _scope(date(2024, 1, 2), date(2024, 1, 2))
    first = TaskLedger(lease_owner="first", lease_seconds=60)
    with engine.begin() as connection:
        task = first.acquire_daily_task(
            connection,
            scope=scope,
            trade_dates=[date(2024, 1, 2)],
            now=datetime(2024, 1, 3, 0, 0),
        )
        unit = first.claim_work_unit(
            connection,
            run_id=task.run_id,
            work_unit_id=task.work_units[0].work_unit_id,
            now=datetime(2024, 1, 3, 0, 0),
        )
        first.finish_work_unit(
            connection,
            run_id=task.run_id,
            work_unit_id=unit.work_unit_id,
            status="held",
            rows_fetched=100,
            rows_published=90,
            rows_pending=10,
            rows_rejected=0,
            api_calls=2,
            api_units=200,
            response_hash="b" * 64,
            quality_status="review_required",
            now=datetime(2024, 1, 3, 0, 0),
        )
        final = first.finalize_task(
            connection,
            run_id=task.run_id,
            review_required=True,
            now=datetime(2024, 1, 3, 0, 0),
        )

    assert final["status"] == "success"
    assert final["complete"] is False
    assert final["invocation_complete"] is True

    with engine.begin() as connection:
        resumed = TaskLedger(lease_owner="second").acquire_daily_task(
            connection,
            scope=scope,
            trade_dates=[date(2024, 1, 2)],
            now=datetime(2024, 1, 3, 0, 2),
        )
    assert resumed.resumed is True
    assert [unit.status for unit in resumed.pending_work_units] == ["held"]


def test_task_lease_heartbeat_pulses_during_long_external_work() -> None:
    class RecordingLedger:
        lease_seconds = 1

        def __init__(self) -> None:
            self.pulses = 0

        def heartbeat(self, connection, *, run_id: int) -> None:
            assert connection == "connection"
            assert run_id == 42
            self.pulses += 1

    class RecordingEngine:
        @contextmanager
        def begin(self):
            yield "connection"

    ledger = RecordingLedger()
    with TaskLeaseHeartbeat(
        engine=RecordingEngine(),
        ledger=ledger,
        run_id=42,
        interval_seconds=0.01,
    ):
        sleep(0.035)

    assert ledger.pulses >= 2
