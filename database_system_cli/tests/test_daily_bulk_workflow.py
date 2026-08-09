from contextlib import contextmanager
from datetime import date, datetime

import pytest

import fdp.get_data.bulk.workflow as workflow_module
from fdp.config import EodhdRuntimeConfig
from fdp.get_data.bulk.readiness import NEW_YORK, latest_ready_from_dates
from fdp.get_data.bulk.workflow import DailyBulkExecutor, _response_completeness
from fdp.get_data.runtime import JobRuntime
from fdp.get_data.task_ledger import DailyTaskScope, TaskLedger, WorkUnitState
from fdp.sources.eodhd.client import EodhdApiResponse
from fdp.sources.eodhd.ingest import BulkDailyPriceLoadResult

from test_daily_task_ledger import _engine


class TrackingEngine:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.transaction_depth = 0

    @contextmanager
    def begin(self):
        self.transaction_depth += 1
        try:
            with self.engine.begin() as connection:
                yield connection
        finally:
            self.transaction_depth -= 1

    def connect(self):
        return self.engine.connect()


class AssertOutsideTransactionClient:
    def __init__(self, engine: TrackingEngine, response: EodhdApiResponse) -> None:
        self.engine = engine
        self.response = response
        self.calls = 0

    def get_bulk_eod(self, *args, **kwargs) -> EodhdApiResponse:
        assert self.engine.transaction_depth == 0
        self.calls += 1
        return self.response


def _response(
    *,
    rows: int = 1,
    vendor_type: str = "Common Stock",
    trade_date: str = "2024-01-02",
) -> EodhdApiResponse:
    payload = [
        {
            "code": f"TICK{index}",
            "date": trade_date,
            "type": vendor_type,
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "adjusted_close": 10,
            "volume": 100,
        }
        for index in range(rows)
    ]
    return EodhdApiResponse(
        endpoint="/eod-bulk-last-day/US",
        status_code=200,
        success=True,
        retry_count=0,
        rows_returned=len(payload),
        duration_ms=1,
        payload=payload,
    )


def _scope() -> DailyTaskScope:
    return DailyTaskScope.create(
        source="eodhd",
        market="US",
        exchange="US",
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        asset_types=["stock"],
        instrument_status="all",
    )


def test_bulk_executor_fetches_outside_transaction_and_checkpoints_with_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_engine = _engine()
    engine = TrackingEngine(raw_engine)
    ledger = TaskLedger(lease_owner="test")
    scope = _scope()
    with engine.begin() as connection:
        acquisition = ledger.acquire_daily_task(
            connection,
            scope=scope,
            trade_dates=[date(2024, 1, 2)],
        )
    client = AssertOutsideTransactionClient(engine, _response())
    publish_depths: list[int] = []

    def fake_publish(connection, response, **kwargs):
        publish_depths.append(engine.transaction_depth)
        return BulkDailyPriceLoadResult(
            run_id=acquisition.run_id,
            status="success",
            exchange="US",
            trade_date=date(2024, 1, 2),
            rows_fetched=1,
            rows_matched=1,
            rows_inserted=1,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
            unmatched_rows=0,
        )

    monkeypatch.setattr(workflow_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(workflow_module, "publish_bulk_daily_prices", fake_publish)
    runtime = JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(),
        injected_client=client,
    )
    execution = DailyBulkExecutor(
        runtime=runtime,
        ledger=ledger,
        client=client,
        scope=scope,
        identity_resolver=object(),
    ).execute(acquisition, parallel=False, workers=1)

    assert client.calls == 1
    assert publish_depths == [1]
    assert execution.outcomes[0].status == "success"
    with engine.connect() as connection:
        unit = ledger.load_work_units(connection, run_id=acquisition.run_id)[0]
    assert unit.status == "success"
    assert unit.rows_published == 1
    assert unit.quality_status == "response_verified"


def test_thin_response_uses_verified_type_and_total_baselines() -> None:
    baseline = [
        WorkUnitState(
            work_unit_id=index,
            run_id=index,
            unit_key=f"2024-01-0{index}",
            unit_fingerprint=str(index),
            series_fingerprint="series",
            status="success",
            attempt_count=1,
            reused_from_work_unit_id=None,
            rows_fetched=2_000,
            rows_published=2_000,
            rows_pending=0,
            rows_rejected=0,
            api_calls=1,
            api_units=100,
            quality_status="verified",
            metrics={"asset_type_counts": {"stock": 2_000}},
        )
        for index in (2, 3, 4)
    ]

    check = _response_completeness(
        _response(rows=100),
        trade_date=date(2024, 1, 2),
        asset_types=["stock"],
        baseline=baseline,
    )

    assert check["review_required"] is True
    assert any("thin_total_response" in reason for reason in check["reasons"])
    assert any("thin_stock_response" in reason for reason in check["reasons"])


def test_thin_response_detects_smaller_fund_subpopulation() -> None:
    baseline = [
        WorkUnitState(
            work_unit_id=index,
            run_id=index,
            unit_key=f"2024-01-0{index}",
            unit_fingerprint=str(index),
            series_fingerprint="series",
            status="success",
            attempt_count=1,
            reused_from_work_unit_id=None,
            rows_fetched=300,
            rows_published=300,
            rows_pending=0,
            rows_rejected=0,
            api_calls=1,
            api_units=100,
            quality_status="verified",
            metrics={"asset_type_counts": {"fund": 300}},
        )
        for index in (2, 3, 4)
    ]

    check = _response_completeness(
        _response(rows=100, vendor_type="FUND"),
        trade_date=date(2024, 1, 2),
        asset_types=["fund"],
        baseline=baseline,
    )

    assert any("thin_fund_response" in reason for reason in check["reasons"])


def test_retry_attempts_are_logged_but_only_best_response_is_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_engine = _engine()
    engine = TrackingEngine(raw_engine)
    ledger = TaskLedger(lease_owner="test")
    scope = _scope()
    with engine.begin() as connection:
        acquisition = ledger.acquire_daily_task(
            connection,
            scope=scope,
            trade_dates=[date(2024, 1, 2)],
        )
        claimed = ledger.claim_work_unit(
            connection,
            run_id=acquisition.run_id,
            work_unit_id=acquisition.work_units[0].work_unit_id,
        )

    first = _response(rows=100)
    best = _response(rows=200)
    published: list[EodhdApiResponse] = []
    logged: list[EodhdApiResponse] = []

    def fake_publish(connection, response, **kwargs):
        published.append(response)
        return BulkDailyPriceLoadResult(
            run_id=acquisition.run_id,
            status="success",
            exchange="US",
            trade_date=date(2024, 1, 2),
            rows_fetched=response.rows_returned,
            rows_matched=response.rows_returned,
            rows_inserted=response.rows_returned,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
            unmatched_rows=0,
        )

    monkeypatch.setattr(workflow_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(workflow_module, "publish_bulk_daily_prices", fake_publish)
    monkeypatch.setattr(
        workflow_module,
        "record_api_call",
        lambda connection, *, response, **kwargs: logged.append(response),
    )
    executor = DailyBulkExecutor(
        runtime=JobRuntime(engine=engine, config=EodhdRuntimeConfig()),
        ledger=ledger,
        client=object(),
        scope=scope,
        identity_resolver=object(),
    )

    outcome = executor._publish_responses(
        run_id=acquisition.run_id,
        unit=claimed,
        responses=[first, best],
        final_response=best,
        completeness={"review_required": False, "reasons": []},
    )

    assert published == [best]
    assert logged == [first]
    assert outcome.rows_published == 200


def test_source_row_closure_mismatch_keeps_work_unit_resumable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_engine = _engine()
    engine = TrackingEngine(raw_engine)
    ledger = TaskLedger(lease_owner="test")
    scope = _scope()
    with engine.begin() as connection:
        acquisition = ledger.acquire_daily_task(
            connection,
            scope=scope,
            trade_dates=[date(2024, 1, 2)],
        )
        claimed = ledger.claim_work_unit(
            connection,
            run_id=acquisition.run_id,
            work_unit_id=acquisition.work_units[0].work_unit_id,
        )

    response = _response(rows=2)

    def incomplete_publish(connection, response, **kwargs):
        return BulkDailyPriceLoadResult(
            run_id=acquisition.run_id,
            status="success",
            exchange="US",
            trade_date=date(2024, 1, 2),
            rows_fetched=2,
            rows_matched=1,
            rows_inserted=1,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
            unmatched_rows=0,
        )

    monkeypatch.setattr(workflow_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(workflow_module, "publish_bulk_daily_prices", incomplete_publish)
    executor = DailyBulkExecutor(
        runtime=JobRuntime(engine=engine, config=EodhdRuntimeConfig()),
        ledger=ledger,
        client=object(),
        scope=scope,
        identity_resolver=object(),
    )

    outcome = executor._publish_responses(
        run_id=acquisition.run_id,
        unit=claimed,
        responses=[response],
        final_response=response,
        completeness={"review_required": False, "reasons": []},
    )

    assert outcome.status == "failed"
    assert outcome.metrics["source_row_closure"] == {
        "valid": False,
        "fetched": 2,
        "accounted": 1,
    }
    with engine.connect() as connection:
        unit = ledger.load_work_unit(connection, work_unit_id=claimed.work_unit_id)
    assert unit.status == "failed"
    assert unit.quality_status == "source_closure_failed"


def test_latest_date_readiness_changes_when_fund_is_selected() -> None:
    trade_dates = [date(2024, 1, 5), date(2024, 1, 8)]
    before_equity_cutoff = datetime(2024, 1, 8, 16, 29, tzinfo=NEW_YORK)
    after_equity_cutoff = datetime(2024, 1, 8, 16, 30, tzinfo=NEW_YORK)
    before_fund_cutoff = datetime(2024, 1, 9, 6, 29, tzinfo=NEW_YORK)
    after_fund_cutoff = datetime(2024, 1, 9, 6, 30, tzinfo=NEW_YORK)

    assert latest_ready_from_dates(
        trade_dates,
        asset_types=["stock", "etf"],
        now=before_equity_cutoff,
    ) == date(2024, 1, 5)
    assert latest_ready_from_dates(
        trade_dates,
        asset_types=["stock", "etf"],
        now=after_equity_cutoff,
    ) == date(2024, 1, 8)
    assert latest_ready_from_dates(
        trade_dates,
        asset_types=["stock", "fund"],
        now=before_fund_cutoff,
    ) == date(2024, 1, 5)
    assert latest_ready_from_dates(
        trade_dates,
        asset_types=["stock", "fund"],
        now=after_fund_cutoff,
    ) == date(2024, 1, 8)
