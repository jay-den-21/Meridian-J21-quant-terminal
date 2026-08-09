from datetime import date

import pytest

import fdp.mcp.server as server
from fdp.get_data.contracts import JobResult


class _FakeRangeJob:
    calls: list[dict[str, object]] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return JobResult(
            job="ingest.daily_range",
            status="success",
            run_id=42,
            parameters={"date_from": date(2024, 1, 2)},
            parameter_sources={},
        )


class _FakeDailyJob:
    calls: list[dict[str, object]] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return JobResult(
            job="ingest.daily",
            status="success",
            run_id=43,
            parameters={"trade_date": date(2024, 1, 2)},
            parameter_sources={},
        )


def test_mcp_write_tools_are_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(server.MCP_WRITE_ENV, raising=False)
    monkeypatch.setattr(server, "DailyRangeJob", _FakeRangeJob)
    _FakeRangeJob.calls.clear()

    with pytest.raises(PermissionError, match="MCP writes are disabled"):
        server.daily_range_execute(
            "2024-01-02",
            "2024-01-03",
            confirm_execute=True,
        )

    assert _FakeRangeJob.calls == []


def test_mcp_write_tools_require_per_call_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(server.MCP_WRITE_ENV, "1")
    monkeypatch.setattr(server, "DailyRangeJob", _FakeRangeJob)
    _FakeRangeJob.calls.clear()

    with pytest.raises(PermissionError, match="confirm_execute=true"):
        server.daily_range_execute(
            "2024-01-02",
            "2024-01-03",
            confirm_execute=False,
        )

    assert _FakeRangeJob.calls == []


def test_mcp_explicit_write_uses_shared_job_and_json_safe_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(server.MCP_WRITE_ENV, "1")
    monkeypatch.setattr(server, "DailyRangeJob", _FakeRangeJob)
    monkeypatch.setattr(server.JobRuntime, "from_env", lambda: object())
    _FakeRangeJob.calls.clear()

    result = server.daily_range_execute(
        "2024-01-02",
        "2024-01-03",
        confirm_execute=True,
        new_run=True,
        max_api_calls=500,
    )

    assert result["run_id"] == 42
    assert result["parameters"]["date_from"] == "2024-01-02"
    assert _FakeRangeJob.calls[0]["execute"] is True
    assert _FakeRangeJob.calls[0]["new_run"] is True
    assert _FakeRangeJob.calls[0]["max_api_calls"] == 500


def test_mcp_one_day_execute_forwards_latest_or_explicit_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(server.MCP_WRITE_ENV, "1")
    monkeypatch.setattr(server, "BulkDailyJob", _FakeDailyJob)
    monkeypatch.setattr(server.JobRuntime, "from_env", lambda: object())
    _FakeDailyJob.calls.clear()

    result = server.daily_execute(
        confirm_execute=True,
        trade_date="2024-01-02",
        manual=True,
    )

    assert result["parameters"]["trade_date"] == "2024-01-02"
    assert _FakeDailyJob.calls[0]["trade_date"] == date(2024, 1, 2)
    assert _FakeDailyJob.calls[0]["manual"] is True


def test_mcp_task_list_limit_is_bounded() -> None:
    with pytest.raises(ValueError, match="between 1 and 500"):
        server.task_list(limit=501)
