from __future__ import annotations

from typing import Any

import pytest

import fdp.get_data.reference.get_id_mappings as job_module
from fdp.config import EodhdRuntimeConfig
from fdp.get_data.contracts import ProgressEvent
from fdp.get_data.reference import IdentifierMappingJob
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.client import EodhdApiResponse
from fdp.sources.eodhd.ingest.id_mapping import IdentifierMappingPageResult


class _Context:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def __enter__(self) -> object:
        return self.connection

    def __exit__(self, *args: object) -> None:
        return None


class _Engine:
    def __init__(self) -> None:
        self.connection = object()
        self.connect_count = 0
        self.begin_count = 0

    def connect(self) -> _Context:
        self.connect_count += 1
        return _Context(self.connection)

    def begin(self) -> _Context:
        self.begin_count += 1
        return _Context(self.connection)


class _Reporter:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def on_event(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def on_api_event(self, event: object) -> None:
        return None


class _Client:
    def __init__(
        self,
        *,
        total: int = 5,
        remote_remaining: int = 100,
        cancel_at_offset: int | None = None,
    ) -> None:
        self.total = total
        self.remote_remaining = remote_remaining
        self.api_budget = None
        self.completed_offsets: list[int] = []
        self.mapping_calls = 0
        self.cancel_at_offset = cancel_at_offset

    def get_user(self) -> EodhdApiResponse:
        daily_limit = 100
        used = daily_limit - self.remote_remaining
        return EodhdApiResponse(
            endpoint="/user",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=1,
            duration_ms=1,
            payload=[
                {
                    "apiRequests": used,
                    "dailyRateLimit": daily_limit,
                    "extraLimit": 0,
                    "apiRequestsDate": "2026-07-16",
                }
            ],
        )

    def get_id_mappings(
        self,
        *,
        filter_type: str,
        filter_value: str,
        limit: int,
        offset: int,
    ) -> EodhdApiResponse:
        assert filter_type in {"ex", "symbol"}
        assert filter_value
        if offset == self.cancel_at_offset:
            raise KeyboardInterrupt
        if self.api_budget is not None:
            self.api_budget.reserve(endpoint="/id-mapping", units=1)
        self.mapping_calls += 1
        self.completed_offsets.append(offset)
        total = 1 if filter_type == "symbol" else self.total
        row_count = min(limit, max(total - offset, 0))
        data = [
            {"symbol": f"TEST{offset + index}.US", "cik": str(offset + index + 1)}
            for index in range(row_count)
        ]
        has_next = offset + row_count < total
        return EodhdApiResponse(
            endpoint="/id-mapping",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=row_count,
            duration_ms=1,
            payload={
                "meta": {"total": total, "limit": limit, "offset": offset},
                "data": data,
                "links": {"next": "/next" if has_next else None},
            },
        )


class _Runtime(JobRuntime):
    def __init__(self, client: _Client) -> None:
        super().__init__(engine=_Engine(), config=EodhdRuntimeConfig())
        self.fake_client = client
        self.client_calls = 0

    def client(self, reporter=None, *, max_requests_per_minute=None, api_budget=None):
        self.client_calls += 1
        if api_budget is not None:
            self.fake_client.api_budget = api_budget
        return self.fake_client


@pytest.fixture
def job_hooks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    finished: list[dict[str, Any]] = []
    monkeypatch.setattr(job_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(job_module, "create_task_run", lambda *args, **kwargs: 71)
    monkeypatch.setattr(job_module, "record_api_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        job_module,
        "finish_task_run",
        lambda connection, **kwargs: finished.append(kwargs),
    )
    monkeypatch.setattr(
        IdentifierMappingJob,
        "_count_local_instruments",
        staticmethod(lambda connection, *, market: 5),
    )

    def process_page(connection, *, run_id, market, envelope):
        return IdentifierMappingPageResult(
            total=envelope.total,
            offset=envelope.offset,
            rows_fetched=len(envelope.rows),
            rows_matched=len(envelope.rows),
            identifiers_inserted=len(envelope.rows),
            identifiers_unchanged=0,
            rows_unmatched=0,
            rows_invalid=0,
            identifier_conflicts=0,
            next_offset=(
                envelope.offset + len(envelope.rows) if envelope.has_next else None
            ),
        )

    monkeypatch.setattr(job_module, "process_identifier_mapping_page", process_page)
    return finished


def test_id_mapping_preflight_rejects_missing_or_ambiguous_scope_before_client() -> None:
    runtime = _Runtime(_Client())
    job = IdentifierMappingJob()

    with pytest.raises(ValueError, match="exactly one ID Mapping scope"):
        job.preflight(runtime=runtime)
    with pytest.raises(ValueError, match="exactly one ID Mapping scope"):
        job.preflight(exchange="US", symbols=["AAPL.US"], runtime=runtime)

    assert runtime.client_calls == 0
    assert runtime.engine.connect_count == 0


def test_id_mapping_dry_run_is_local_and_does_not_create_client(
    job_hooks: list[dict[str, Any]],
) -> None:
    runtime = _Runtime(_Client())

    result = IdentifierMappingJob().run(
        exchange="US",
        page_limit=2,
        max_api_calls=3,
        execute=False,
        runtime=runtime,
    )

    assert result.status == "dry_run"
    assert result.preflight is not None
    assert result.preflight.target_tables == [
        "instrument_identifier_history",
        "system.identifier_mapping_unmatched_observation",
    ]
    assert result.preflight.estimated_api_calls == 3
    assert runtime.client_calls == 0
    assert runtime.engine.begin_count == 0
    assert job_hooks == []


def test_id_mapping_exchange_budget_stop_returns_resumable_offset(
    job_hooks: list[dict[str, Any]],
) -> None:
    runtime = _Runtime(_Client(total=5, remote_remaining=100))
    reporter = _Reporter()

    result = IdentifierMappingJob().run(
        exchange="US",
        page_limit=2,
        max_api_calls=2,
        execute=True,
        runtime=runtime,
        reporter=reporter,
        override_source="cli",
    )

    assert result.status == "partial_failed"
    assert result.rows_fetched == 4
    assert result.rows_inserted == 4
    assert result.api_calls == 3
    assert result.metrics["mapping_api_units_consumed"] == 2
    assert result.metrics["next_offset"] == 4
    assert runtime.fake_client.completed_offsets == [0, 2]
    assert [event.kind for event in reporter.events] == [
        "start",
        "unit_completed",
        "unit_completed",
        "finish",
    ]
    assert job_hooks[0]["status"] == "partial_failed"
    assert job_hooks[0]["api_calls"] == 3


def test_id_mapping_operator_cancel_closes_run_with_resume_offset(
    job_hooks: list[dict[str, Any]],
) -> None:
    runtime = _Runtime(_Client(total=5, cancel_at_offset=2))
    reporter = _Reporter()

    result = IdentifierMappingJob().run(
        exchange="US",
        page_limit=2,
        max_api_calls=5,
        execute=True,
        runtime=runtime,
        reporter=reporter,
    )

    assert result.status == "cancelled"
    assert result.rows_fetched == 2
    assert result.metrics["next_offset"] == 2
    assert result.failures[0].category == "cancelled"
    assert [event.kind for event in reporter.events] == [
        "start",
        "unit_completed",
        "finish",
    ]
    assert job_hooks[0]["status"] == "cancelled"


def test_id_mapping_remote_budget_failure_closes_task_and_progress(
    job_hooks: list[dict[str, Any]],
) -> None:
    runtime = _Runtime(_Client(remote_remaining=0))
    reporter = _Reporter()

    result = IdentifierMappingJob().run(
        symbols=["AAPL.US"],
        max_api_calls=1,
        execute=True,
        runtime=runtime,
        reporter=reporter,
    )

    assert result.status == "failed"
    assert result.failures[0].category == "api_budget"
    assert runtime.fake_client.mapping_calls == 0
    assert [event.kind for event in reporter.events] == ["start", "finish"]
    assert job_hooks[0]["status"] == "failed"
    assert job_hooks[0]["api_calls"] == 1


def test_id_mapping_user_client_initialization_failure_closes_task(
    monkeypatch: pytest.MonkeyPatch,
    job_hooks: list[dict[str, Any]],
) -> None:
    runtime = _Runtime(_Client())
    reporter = _Reporter()
    monkeypatch.setattr(
        runtime,
        "client",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("missing API key")),
    )

    result = IdentifierMappingJob().run(
        symbols=["AAPL.US"],
        max_api_calls=1,
        execute=True,
        runtime=runtime,
        reporter=reporter,
    )

    assert result.status == "failed"
    assert result.failures[0].category == "runtime_error"
    assert "missing API key" in (result.error_message or "")
    assert [event.kind for event in reporter.events] == ["start", "finish"]
    assert job_hooks[0]["status"] == "failed"


def test_id_mapping_user_preflight_cancel_closes_task(
    monkeypatch: pytest.MonkeyPatch,
    job_hooks: list[dict[str, Any]],
) -> None:
    runtime = _Runtime(_Client())
    reporter = _Reporter()

    def cancel_client(*args: object, **kwargs: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(runtime, "client", cancel_client)

    result = IdentifierMappingJob().run(
        symbols=["AAPL.US"],
        max_api_calls=1,
        execute=True,
        runtime=runtime,
        reporter=reporter,
    )

    assert result.status == "cancelled"
    assert result.failures[0].category == "cancelled"
    assert [event.kind for event in reporter.events] == ["start", "finish"]
    assert job_hooks[0]["status"] == "cancelled"


def test_id_mapping_mapping_client_cancel_closes_task(
    monkeypatch: pytest.MonkeyPatch,
    job_hooks: list[dict[str, Any]],
) -> None:
    runtime = _Runtime(_Client())
    reporter = _Reporter()
    original_client = runtime.client
    calls = 0

    def cancel_second_client(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return original_client(*args, **kwargs)

    monkeypatch.setattr(runtime, "client", cancel_second_client)

    result = IdentifierMappingJob().run(
        symbols=["AAPL.US"],
        max_api_calls=1,
        execute=True,
        runtime=runtime,
        reporter=reporter,
    )

    assert result.status == "cancelled"
    assert result.failures[0].category == "cancelled"
    assert result.api_calls == 1
    assert [event.kind for event in reporter.events] == ["start", "finish"]
    assert reporter.events[-1].counters == {"api_calls": 1, "cancelled": 1}
    assert job_hooks[0]["status"] == "cancelled"


def test_id_mapping_runtime_error_message_prefers_bounded_original_error() -> None:
    class WrappedDatabaseError(RuntimeError):
        orig = RuntimeError("unknown column\n" + "x" * 2000)

    message = IdentifierMappingJob._concise_exception(WrappedDatabaseError("verbose SQL"))

    assert message.startswith("unknown column ")
    assert "verbose SQL" not in message
    assert len(message) == 1000
