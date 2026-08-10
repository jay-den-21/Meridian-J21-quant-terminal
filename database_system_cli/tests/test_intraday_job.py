from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import fdp.get_data.intraday.validate_eodhd as validate_module
from fdp.config import EodhdRuntimeConfig
from fdp.get_data.contracts import ProgressEvent
from fdp.get_data.intraday.validate_eodhd import (
    EodhdIntradayValidationJob,
    intraday_request_windows,
)
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.client import EodhdClient


class FakeResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS system")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS us_share")
        connection.exec_driver_sql(
            """
            CREATE TABLE us_share.instrument (
                instrument_id INTEGER PRIMARY KEY, market TEXT NOT NULL,
                symbol TEXT NOT NULL, provider TEXT NOT NULL,
                provider_symbol TEXT NOT NULL, exchange TEXT NOT NULL,
                asset_type TEXT NOT NULL, is_active BOOLEAN NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE system.ingestion_task_run (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL, market TEXT NOT NULL, source TEXT NOT NULL,
                target_schema TEXT NOT NULL, target_table TEXT NOT NULL, status TEXT NOT NULL,
                date_from DATE, date_to DATE, started_at DATETIME NOT NULL,
                finished_at DATETIME, rows_fetched INTEGER DEFAULT 0,
                rows_inserted INTEGER DEFAULT 0, rows_updated INTEGER DEFAULT 0,
                rows_rejected INTEGER DEFAULT 0, api_calls INTEGER DEFAULT 0,
                error_message TEXT
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE system.api_call_log (
                api_call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL, work_unit_id INTEGER, source TEXT NOT NULL,
                endpoint TEXT NOT NULL, provider_symbol TEXT, date_from DATE, date_to DATE,
                status_code INTEGER, success BOOLEAN NOT NULL, retry_count INTEGER DEFAULT 0,
                rows_returned INTEGER DEFAULT 0, error_message TEXT, called_at DATETIME NOT NULL,
                duration_ms INTEGER
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE system.intraday_file_manifest (
                manifest_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                dataset_kind TEXT NOT NULL, source TEXT NOT NULL, market TEXT NOT NULL,
                asset_type TEXT NOT NULL, interval TEXT NOT NULL, instrument_id INTEGER NOT NULL,
                provider_symbol TEXT NOT NULL, trade_date DATE NOT NULL, bucket INTEGER NOT NULL,
                storage_path TEXT NOT NULL UNIQUE, content_hash TEXT NOT NULL,
                file_sha256 TEXT NOT NULL, row_count INTEGER NOT NULL,
                file_size_bytes INTEGER NOT NULL, timestamp_min_utc DATETIME NOT NULL,
                timestamp_max_utc DATETIME NOT NULL, schema_version INTEGER NOT NULL,
                status TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (dataset_kind, source, instrument_id, interval, trade_date)
            )
            """
        )
        connection.execute(
            text(
                "INSERT INTO us_share.instrument VALUES "
                "(101, 'US', 'AAPL', 'EODHD', 'AAPL.US', 'NASDAQ', 'stock', 1)"
            )
        )
    return engine


def _runtime(engine, calls: list[str], timestamp: datetime) -> JobRuntime:
    def transport(request, timeout: int):
        calls.append(request.full_url)
        if "/user" in request.full_url:
            return FakeResponse(
                {
                    "apiRequests": 10,
                    "dailyRateLimit": 100000,
                    "extraLimit": 0,
                    "apiRequestsDate": "2026-08-10",
                }
            )
        return FakeResponse(
            [
                {
                    "timestamp": int(timestamp.timestamp()),
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "volume": 1000,
                }
            ]
        )

    return JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(max_retries=0),
        injected_client=EodhdClient(api_key="fixture-token", max_retries=0, transport=transport),
    )


def test_intraday_request_windows_respect_120_calendar_day_limit() -> None:
    windows = intraday_request_windows(date(2024, 1, 1), date(2024, 8, 1))
    assert [(window.date_to - window.date_from).days + 1 for window in windows] == [120, 94]
    assert windows[0].to_timestamp < windows[1].from_timestamp


def test_intraday_dry_run_has_zero_provider_calls(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = _runtime(
        _engine(), calls, datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    )
    result = EodhdIntradayValidationJob().run(
        symbols=["AAPL"],
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        data_root=tmp_path / "minutes",
        execute=False,
        runtime=runtime,
    )
    assert result.status == "dry_run"
    assert result.preflight is not None
    assert result.preflight.estimated_api_calls == 6
    assert calls == []


def test_intraday_execute_uses_fixture_and_idempotent_manifest(tmp_path: Path) -> None:
    calls: list[str] = []
    engine = _engine()
    runtime = _runtime(
        engine, calls, datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    )
    kwargs = {
        "symbols": ["AAPL.US"],
        "date_from": date(2024, 1, 2),
        "date_to": date(2024, 1, 2),
        "data_root": tmp_path / "minutes",
        "execute": True,
        "runtime": runtime,
    }

    first = EodhdIntradayValidationJob().run(**kwargs)
    second = EodhdIntradayValidationJob().run(**kwargs)

    assert first.status == "success"
    assert first.rows_matched == 1
    assert first.rows_inserted == 1
    assert first.metrics["api_units_consumed"] == 6
    assert second.status == "success"
    assert second.rows_inserted == 0
    assert second.metrics["manifests_reused"] == 1
    assert len(calls) == 4
    assert all("fixture-token" in url for url in calls)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM system.intraday_file_manifest")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM system.api_call_log")
        ).scalar_one() == 4


def test_intraday_cap_and_missing_root_fail_before_client_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(
        _engine(), [], datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    )
    with pytest.raises(ValueError, match="exceed max-api-calls"):
        EodhdIntradayValidationJob().preflight(
            symbols=["AAPL"],
            date_from=date(2000, 1, 1),
            date_to=date(2025, 1, 1),
            data_root=tmp_path / "minutes",
            runtime=runtime,
        )
    monkeypatch.delenv("J21_INTRADAY_DATA_ROOT", raising=False)
    runtime.injected_client = None
    runtime.client_factory = lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("client must not be constructed")
    )
    with pytest.raises(ValueError, match="J21_INTRADAY_DATA_ROOT is required"):
        EodhdIntradayValidationJob().run(
            symbols=["AAPL"],
            date_from=date(2024, 1, 2),
            date_to=date(2024, 1, 2),
            execute=True,
            runtime=runtime,
        )


def test_intraday_missing_instrument_uses_zero_provider_calls(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = _runtime(
        _engine(), calls, datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    )
    result = EodhdIntradayValidationJob().run(
        symbols=["NOT_FOUND"],
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        data_root=tmp_path / "minutes",
        execute=True,
        runtime=runtime,
    )
    assert result.status == "failed"
    assert result.api_calls == 0
    assert calls == []


def test_intraday_empty_response_is_not_reported_as_success(tmp_path: Path) -> None:
    calls: list[str] = []
    runtime = _runtime(
        _engine(), calls, datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    )
    runtime.injected_client.transport = lambda request, timeout: (
        FakeResponse(
            {
                "apiRequests": 10,
                "dailyRateLimit": 100000,
                "extraLimit": 0,
                "apiRequestsDate": "2026-08-10",
            }
        )
        if "/user" in request.full_url
        else FakeResponse([])
    )

    result = EodhdIntradayValidationJob().run(
        symbols=["AAPL.US"],
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        data_root=tmp_path / "minutes",
        execute=True,
        runtime=runtime,
    )

    assert result.status == "failed"
    assert result.rows_matched == 0
    assert result.work_units_failed == 1
    assert result.failures[0].category == "no_data"


def test_intraday_rejects_stale_confirmed_preflight_before_api_call(tmp_path: Path) -> None:
    calls: list[str] = []
    engine = _engine()
    runtime = _runtime(
        engine, calls, datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    )
    job = EodhdIntradayValidationJob()
    kwargs = {
        "symbols": ["AAPL.US"],
        "date_from": date(2024, 1, 2),
        "date_to": date(2024, 1, 2),
        "data_root": tmp_path / "minutes",
        "runtime": runtime,
    }
    preflight = job.preflight(**kwargs)
    with engine.begin() as connection:
        connection.execute(text("UPDATE us_share.instrument SET is_active = 0"))

    with pytest.raises(ValueError, match="scope changed after preflight"):
        job.run(**kwargs, execute=True, preflight=preflight)

    assert calls == []
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM system.ingestion_task_run")
        ).scalar_one() == 0


def test_intraday_rejects_same_size_instrument_identity_change_before_api_call(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    engine = _engine()
    runtime = _runtime(
        engine, calls, datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    )
    job = EodhdIntradayValidationJob()
    kwargs = {
        "symbols": ["AAPL.US"],
        "date_from": date(2024, 1, 2),
        "date_to": date(2024, 1, 2),
        "data_root": tmp_path / "minutes",
        "runtime": runtime,
    }
    preflight = job.preflight(**kwargs)
    with engine.begin() as connection:
        connection.execute(text("UPDATE us_share.instrument SET instrument_id = 202"))

    with pytest.raises(ValueError, match="scope changed after preflight"):
        job.run(**kwargs, execute=True, preflight=preflight)

    assert calls == []
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM system.ingestion_task_run")
        ).scalar_one() == 0


def test_intraday_budget_exhaustion_audits_prior_retry_attempt_and_stops(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    engine = _engine()

    def transport(request, timeout: int):
        calls.append(request.full_url)
        if "/user" in request.full_url:
            return FakeResponse(
                {
                    "apiRequests": 10,
                    "dailyRateLimit": 100000,
                    "extraLimit": 0,
                    "apiRequestsDate": "2026-08-10",
                }
            )
        return FakeResponse([], status=503)

    runtime = JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(max_retries=1, retry_delay_seconds=0),
        injected_client=EodhdClient(
            api_key="fixture-token",
            max_retries=1,
            retry_delay_seconds=0,
            sleeper=lambda _: None,
            transport=transport,
        ),
    )
    result = EodhdIntradayValidationJob().run(
        symbols=["AAPL.US"],
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        data_root=tmp_path / "minutes",
        max_api_units=6,
        execute=True,
        runtime=runtime,
    )

    assert result.status == "failed"
    assert result.api_calls == 2
    assert result.metrics["api_units_consumed"] == 6
    assert len(calls) == 2
    with engine.connect() as connection:
        logs = connection.execute(
            text("SELECT endpoint, retry_count FROM system.api_call_log ORDER BY api_call_id")
        ).all()
    assert logs == [("/user", 0), ("/intraday/AAPL.US", 0)]


def test_intraday_unexpected_error_terminalizes_run_before_reraising(tmp_path: Path) -> None:
    engine = _engine()

    class BrokenClient:
        api_budget = None
        progress_callback = None

        def get_user(self):
            raise KeyError("unexpected fixture failure")

    runtime = JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(max_retries=0),
        injected_client=BrokenClient(),
    )
    with pytest.raises(KeyError, match="unexpected fixture failure"):
        EodhdIntradayValidationJob().run(
            symbols=["AAPL.US"],
            date_from=date(2024, 1, 2),
            date_to=date(2024, 1, 2),
            data_root=tmp_path / "minutes",
            execute=True,
            runtime=runtime,
        )

    with engine.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM system.ingestion_task_run")
        ).scalar_one()
    assert status == "failed"


def test_intraday_budget_audit_failure_still_terminalizes_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()

    def transport(request, timeout: int):
        if "/user" in request.full_url:
            return FakeResponse(
                {
                    "apiRequests": 10,
                    "dailyRateLimit": 100000,
                    "extraLimit": 0,
                    "apiRequestsDate": "2026-08-10",
                }
            )
        return FakeResponse([], status=503)

    original_record = validate_module.record_api_call

    def record_or_fail(connection, *, response, **kwargs):
        if response.endpoint.startswith("/intraday/"):
            raise RuntimeError("fixture audit failure")
        return original_record(connection, response=response, **kwargs)

    monkeypatch.setattr(validate_module, "record_api_call", record_or_fail)
    runtime = JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(max_retries=1, retry_delay_seconds=0),
        injected_client=EodhdClient(
            api_key="fixture-token",
            max_retries=1,
            retry_delay_seconds=0,
            sleeper=lambda _: None,
            transport=transport,
        ),
    )

    with pytest.raises(RuntimeError, match="fixture audit failure"):
        EodhdIntradayValidationJob().run(
            symbols=["AAPL.US"],
            date_from=date(2024, 1, 2),
            date_to=date(2024, 1, 2),
            data_root=tmp_path / "minutes",
            max_api_units=6,
            execute=True,
            runtime=runtime,
        )

    with engine.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM system.ingestion_task_run")
        ).scalar_one()
    assert status == "failed"


def test_intraday_reporter_failure_does_not_double_count_completed_unit(
    tmp_path: Path,
) -> None:
    engine = _engine()
    events: list[ProgressEvent] = []

    class BrokenReporter:
        def on_event(self, event: ProgressEvent) -> None:
            events.append(event)
            if event.kind == "unit_completed":
                raise KeyError("fixture reporter failure")

        def on_api_event(self, event) -> None:
            return None

    runtime = _runtime(
        engine, [], datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    )
    with pytest.raises(KeyError, match="fixture reporter failure"):
        EodhdIntradayValidationJob().run(
            symbols=["AAPL.US"],
            date_from=date(2024, 1, 2),
            date_to=date(2024, 1, 2),
            data_root=tmp_path / "minutes",
            execute=True,
            runtime=runtime,
            reporter=BrokenReporter(),
        )

    finish = [event for event in events if event.kind == "finish"]
    assert len(finish) == 1
    assert finish[0].completed == 1
    with engine.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM system.ingestion_task_run")
        ).scalar_one()
    assert status == "failed"


def test_intraday_failed_unit_plus_reporter_failure_never_exceeds_total(
    tmp_path: Path,
) -> None:
    engine = _engine()
    finish_events: list[ProgressEvent] = []

    class BrokenFailureReporter:
        def on_event(self, event: ProgressEvent) -> None:
            if event.kind == "unit_failed":
                raise RuntimeError("fixture failed-event reporter failure")
            if event.kind == "finish":
                finish_events.append(event)

        def on_api_event(self, event) -> None:
            return None

    runtime = _runtime(
        engine, [], datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    )
    runtime.injected_client.transport = lambda request, timeout: (
        FakeResponse(
            {
                "apiRequests": 10,
                "dailyRateLimit": 100000,
                "extraLimit": 0,
                "apiRequestsDate": "2026-08-10",
            }
        )
        if "/user" in request.full_url
        else FakeResponse([])
    )

    result = EodhdIntradayValidationJob().run(
        symbols=["AAPL.US"],
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        data_root=tmp_path / "minutes",
        execute=True,
        runtime=runtime,
        reporter=BrokenFailureReporter(),
    )

    assert len(finish_events) == 1
    assert result.status == "failed"
    assert result.work_units_total == 1
    assert result.work_units_failed == 1
    with engine.connect() as connection:
        run = connection.execute(
            text("SELECT status, rows_rejected FROM system.ingestion_task_run")
        ).one()
    assert run.status == "failed"
    assert run.rows_rejected == 0
