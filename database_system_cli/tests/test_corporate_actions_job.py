from __future__ import annotations

from threading import Lock

import pytest

import fdp.get_data.corporate_actions.get_history as job_module
from fdp.config import EodhdRuntimeConfig
from fdp.get_data.corporate_actions import CorporateActionsHistoryJob
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.client import EodhdApiResponse
from fdp.sources.eodhd.corporate_action_identity import (
    CorporateActionIdentityResolution,
)


class FakeContext:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def __enter__(self) -> object:
        return self.connection

    def __exit__(self, *args: object) -> None:
        return None


class FakeConnection:
    def execute(self, statement):
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def connect(self) -> FakeContext:
        return FakeContext(self.connection)

    def begin(self) -> FakeContext:
        return FakeContext(self.connection)


class BudgetedClient:
    def __init__(self, budget) -> None:
        self.budget = budget

    def _response(self, endpoint: str, payload: object) -> EodhdApiResponse:
        self.budget.reserve(endpoint=endpoint, units=1)
        rows = payload if isinstance(payload, list) else [payload]
        return EodhdApiResponse(
            endpoint=endpoint,
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=len(rows),
            duration_ms=1,
            payload=rows,
        )

    def get_user(self):
        return self._response(
            "/user",
            {
                "apiRequests": 1,
                "dailyRateLimit": 100000,
                "extraLimit": 0,
                "apiRequestsDate": "2026-07-17",
            },
        )

    def get_dividends(self, provider_symbol, *, date_from=None, date_to=None):
        return self._response(
            f"/div/{provider_symbol}",
            [{"date": "2025-05-12", "value": "0.25"}],
        )

    def get_splits(self, provider_symbol, *, date_from=None, date_to=None):
        return self._response(
            f"/splits/{provider_symbol}",
            [{"date": "2020-08-31", "split": "4/1"}],
        )


class BudgetRuntime(JobRuntime):
    def client(self, reporter=None, *, max_requests_per_minute=None, api_budget=None):
        assert api_budget is not None
        return BudgetedClient(api_budget)


class RejectingSplitClient(BudgetedClient):
    def get_splits(self, provider_symbol, *, date_from=None, date_to=None):
        if provider_symbol == "MSFT.US":
            return self._response(
                f"/splits/{provider_symbol}",
                [{"date": "2020-08-31", "split": "0/1"}],
            )
        return super().get_splits(
            provider_symbol,
            date_from=date_from,
            date_to=date_to,
        )


class RejectingSplitRuntime(JobRuntime):
    def client(self, reporter=None, *, max_requests_per_minute=None, api_budget=None):
        assert api_budget is not None
        return RejectingSplitClient(api_budget)


class GlobalFailureClient:
    @staticmethod
    def _response(endpoint: str) -> EodhdApiResponse:
        return EodhdApiResponse(
            endpoint=endpoint,
            status_code=503,
            success=False,
            retry_count=0,
            rows_returned=0,
            duration_ms=1,
            payload=[],
            error_message="service unavailable",
        )

    def get_dividends(self, provider_symbol, *, date_from=None, date_to=None):
        return self._response(f"/div/{provider_symbol}")

    def get_splits(self, provider_symbol, *, date_from=None, date_to=None):
        return self._response(f"/splits/{provider_symbol}")


class PassthroughIdentityResolver:
    def resolve(self, *, provider_symbol, action_date):
        symbol = provider_symbol.removesuffix(".US")
        instrument_id = 1 if symbol == "AAPL" else 2
        return CorporateActionIdentityResolution(
            instrument={
                "instrument_id": instrument_id,
                "symbol": symbol,
                "provider_symbol": provider_symbol,
                "asset_type": "stock",
            },
            matched_by="current_provider_symbol",
            reason=None,
        )


def _instruments() -> list[dict[str, object]]:
    return [
        {
            "instrument_id": 1,
            "symbol": "AAPL",
            "provider_symbol": "AAPL.US",
            "asset_type": "stock",
            "currency": "USD",
        },
        {
            "instrument_id": 2,
            "symbol": "MSFT",
            "provider_symbol": "MSFT.US",
            "asset_type": "stock",
            "currency": "USD",
        },
    ]


def test_corporate_action_preflight_truncates_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = JobRuntime(engine=FakeEngine(), config=EodhdRuntimeConfig())
    job = CorporateActionsHistoryJob()
    monkeypatch.setattr(job, "_load_resume_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        job,
        "_select_instruments",
        lambda *args, **kwargs: (_instruments() * 3, [], 6),
    )

    preflight = job.preflight(max_api_calls=5, runtime=runtime)

    assert preflight.work_units == 2
    assert preflight.estimated_api_calls == 5
    assert preflight.parameters["asset_type"] == "stock"
    assert preflight.parameter_sources["asset_type"] == "job_fixed"
    assert "selects 2 of 6" in preflight.warnings[0]


def test_corporate_action_job_counts_user_preflight_inside_hard_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = BudgetRuntime(engine=FakeEngine(), config=EodhdRuntimeConfig())
    job = CorporateActionsHistoryJob()
    monkeypatch.setattr(job, "_load_resume_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        job,
        "_select_instruments",
        lambda *args, **kwargs: (_instruments(), [], 2),
    )
    checkpoint = {
        "version": 1,
        "job": job.job_key,
        "fingerprint": "unused",
        "quality_check_run_id": 22,
        "api_units_limit": 5,
        "api_calls": 0,
        "last_instrument_id": 0,
        "work_units_completed": 0,
        "initial_work_units_completed": 0,
        "work_units_failed": 0,
        "rows_fetched": 0,
        "rows_inserted": 0,
        "rows_rejected": 0,
        "complete": False,
    }
    monkeypatch.setattr(
        job,
        "_prepare_run",
        lambda *args, **kwargs: (11, 22, checkpoint),
    )
    monkeypatch.setattr(job_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(job_module, "finish_task_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        job_module,
        "finish_corporate_action_quality_check",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        job_module.CorporateActionIdentityResolver,
        "from_connection",
        lambda *args, **kwargs: PassthroughIdentityResolver(),
    )

    preflight = job.preflight(
        symbols=["AAPL", "MSFT"],
        max_api_calls=5,
        parallel=False,
        batch_size=1,
        runtime=runtime,
    )
    result = job.run(
        execute=True,
        runtime=runtime,
        preflight=preflight,
    )

    assert result.status == "success"
    assert result.api_calls == 5
    assert result.rows_inserted == 4
    assert result.work_units_completed == 2
    assert result.metrics["task_api_units_consumed"] == 5


def test_corporate_action_partial_result_marks_completed_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = RejectingSplitRuntime(engine=FakeEngine(), config=EodhdRuntimeConfig())
    job = CorporateActionsHistoryJob()
    checkpoint = {
        "version": 1,
        "job": job.job_key,
        "fingerprint": "unused",
        "quality_check_run_id": 22,
        "api_units_limit": 5,
        "api_calls": 0,
        "last_instrument_id": 0,
        "work_units_completed": 0,
        "initial_work_units_completed": 0,
        "work_units_failed": 0,
        "rows_fetched": 0,
        "rows_inserted": 0,
        "rows_rejected": 0,
        "complete": False,
    }
    monkeypatch.setattr(job, "_load_resume_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        job,
        "_select_instruments",
        lambda *args, **kwargs: (_instruments(), [], 2),
    )
    monkeypatch.setattr(job, "_prepare_run", lambda *args, **kwargs: (11, 22, checkpoint))
    monkeypatch.setattr(job_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(job_module, "finish_task_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        job_module,
        "finish_corporate_action_quality_check",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        job_module.CorporateActionIdentityResolver,
        "from_connection",
        lambda *args, **kwargs: PassthroughIdentityResolver(),
    )

    preflight = job.preflight(
        symbols=["AAPL", "MSFT"],
        max_api_calls=5,
        parallel=False,
        batch_size=1,
        runtime=runtime,
    )
    result = job.run(execute=True, runtime=runtime, preflight=preflight)

    assert result.status == "partial_failed"
    assert result.work_units_completed == 2
    assert result.work_units_failed == 1
    assert checkpoint["complete"] is True


def test_corporate_action_resume_refuses_budget_change() -> None:
    checkpoint = {"api_units_limit": 100, "api_calls": 40}

    with pytest.raises(ValueError, match="must remain 100"):
        CorporateActionsHistoryJob._apply_resume_budget(
            {"max_api_calls": 99},
            checkpoint,
        )


def test_parallel_batch_stops_after_repeated_global_failures() -> None:
    job = CorporateActionsHistoryJob()
    instruments = [
        {
            "instrument_id": instrument_id,
            "symbol": f"FAIL{instrument_id}",
            "provider_symbol": f"FAIL{instrument_id}.US",
            "asset_type": "stock",
            "currency": "USD",
        }
        for instrument_id in range(1, 5)
    ]

    results, failures, fatal = job._execute_batch(
        JobRuntime(engine=FakeEngine(), config=EodhdRuntimeConfig()),
        GlobalFailureClient(),
        run_id=11,
        check_run_id=22,
        batch=instruments,
        parameters={
            "parallel": True,
            "workers": 2,
            "action_types": ["dividend", "split"],
            "date_from": None,
            "date_to": None,
            "market": "US",
        },
        write_lock=Lock(),
        identity_resolver=PassthroughIdentityResolver(),
    )

    assert len(results) == 4
    assert len(failures) == 4
    assert fatal is True
