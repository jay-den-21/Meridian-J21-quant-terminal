from datetime import date
from threading import Barrier

import pytest

import fdp.get_data.bulk.get_daily_range as range_module
import fdp.get_data.historical.base as historical_module
from fdp.config import EodhdRuntimeConfig
from fdp.get_data.bulk import BulkDailyJob, DailyRangeJob
from fdp.get_data.contracts import NullProgressReporter
from fdp.get_data.historical import HistoricalDailyJob, IndexDailyJob, StockDailyJob
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.ingest import (
    BulkDailyPriceLoadResult,
    HistoricalDailyPriceUnitResult,
)
from fdp.sources.eodhd.client import EodhdApiResponse


class FakeContext:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def __enter__(self) -> object:
        return self.connection

    def __exit__(self, *args: object) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.connection = object()
        self.begin_count = 0

    def connect(self) -> FakeContext:
        return FakeContext(self.connection)

    def begin(self) -> FakeContext:
        self.begin_count += 1
        return FakeContext(self.connection)


def _instrument(symbol: str, instrument_id: int) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "provider_symbol": f"{symbol}.US",
        "asset_type": "stock",
        "currency": "USD",
    }


def test_stock_job_requires_symbols_and_dates_when_python_defaults_are_empty() -> None:
    job = StockDailyJob()

    with pytest.raises(ValueError, match="symbols is required"):
        job._resolve_options(
            symbols=None,
            date_from=None,
            date_to=None,
            market=None,
            instrument_status=None,
            override_source="python",
        )


def test_bulk_daily_default_routes_stock_etf_and_fund_tables() -> None:
    preflight = BulkDailyJob().preflight()

    assert preflight.parameters["asset_types"] == ["stock", "etf", "fund"]
    assert preflight.target_tables[:3] == [
        "stock_daily_price",
        "etf_daily_price",
        "fund_daily_price",
    ]


def test_index_daily_job_accepts_index_as_a_historical_asset_type() -> None:
    runtime = JobRuntime(
        engine=FakeEngine(),
        config=EodhdRuntimeConfig(),
        injected_client=object(),
    )

    preflight = IndexDailyJob().preflight(
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 5),
        runtime=runtime,
    )

    assert preflight.target_tables == ["index_daily_price"]
    assert preflight.parameters["asset_types"] == ["index"]
    assert preflight.estimated_api_calls == 4


def test_historical_job_resolves_canonical_and_provider_symbols_from_instrument_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    runtime = JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(),
        injected_client=object(),
    )
    instruments = [_instrument("AAPL", 1), _instrument("MSFT", 2)]
    monkeypatch.setattr(
        historical_module, "load_active_instruments", lambda *args, **kwargs: instruments
    )

    preflight = HistoricalDailyJob(asset_types=("stock",)).preflight(
        symbols=["AAPL", "MSFT.US"],
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 5),
        runtime=runtime,
        override_source="cli",
    )

    assert preflight.missing_symbols == []
    assert preflight.estimated_api_calls == 2
    assert preflight.parameter_sources["symbols"] == "cli"


def test_historical_job_commits_each_symbol_and_continues_isolated_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    runtime = JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(),
        injected_client=object(),
    )
    instruments = [_instrument("AAPL", 1), _instrument("BAD", 2), _instrument("MSFT", 3)]
    calls: list[str] = []
    finish_values: list[dict[str, object]] = []

    monkeypatch.setattr(historical_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(historical_module, "create_task_run", lambda *args, **kwargs: 77)
    monkeypatch.setattr(
        historical_module, "load_active_instruments", lambda *args, **kwargs: instruments
    )
    monkeypatch.setattr(
        historical_module,
        "finish_task_run",
        lambda connection, **kwargs: finish_values.append(kwargs),
    )

    def fake_unit(connection, client, *, run_id, instrument_row, date_from, date_to):
        provider_symbol = str(instrument_row["provider_symbol"])
        calls.append(provider_symbol)
        if provider_symbol == "BAD.US":
            return HistoricalDailyPriceUnitResult(
                provider_symbol=provider_symbol,
                status="failed",
                status_code=404,
                rows_fetched=0,
                rows_inserted=0,
                rows_rejected=0,
                api_calls=1,
                rejected_rows=[],
                error_message="not found",
            )
        return HistoricalDailyPriceUnitResult(
            provider_symbol=provider_symbol,
            status="success",
            status_code=200,
            rows_fetched=5,
            rows_inserted=5,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
        )

    monkeypatch.setattr(historical_module, "load_historical_daily_price_unit", fake_unit)
    job = HistoricalDailyJob(asset_types=("stock",))
    result = job.run(
        symbols=["AAPL", "BAD", "MSFT"],
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 5),
        runtime=runtime,
        override_source="cli",
    )

    assert calls == ["AAPL.US", "BAD.US", "MSFT.US"]
    assert engine.begin_count == 5  # parent, three symbols, finalization
    assert result.status == "partial_failed"
    assert result.rows_inserted == 10
    assert result.work_units_failed == 1
    assert finish_values[0]["status"] == "partial_failed"


def test_historical_job_stops_immediately_on_entitlement_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    runtime = JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(),
        injected_client=object(),
    )
    instruments = [_instrument("AAPL", 1), _instrument("DENIED", 2), _instrument("MSFT", 3)]
    calls: list[str] = []
    monkeypatch.setattr(historical_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(historical_module, "create_task_run", lambda *args, **kwargs: 88)
    monkeypatch.setattr(
        historical_module, "load_active_instruments", lambda *args, **kwargs: instruments
    )
    monkeypatch.setattr(historical_module, "finish_task_run", lambda *args, **kwargs: None)

    def fake_unit(connection, client, *, run_id, instrument_row, date_from, date_to):
        provider_symbol = str(instrument_row["provider_symbol"])
        calls.append(provider_symbol)
        denied = provider_symbol == "DENIED.US"
        return HistoricalDailyPriceUnitResult(
            provider_symbol=provider_symbol,
            status="failed" if denied else "success",
            status_code=403 if denied else 200,
            rows_fetched=0 if denied else 1,
            rows_inserted=0 if denied else 1,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
            error_message="forbidden" if denied else None,
        )

    monkeypatch.setattr(historical_module, "load_historical_daily_price_unit", fake_unit)
    result = HistoricalDailyJob(asset_types=("stock",)).run(
        symbols=["AAPL", "DENIED", "MSFT"],
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 5),
        runtime=runtime,
    )

    assert calls == ["AAPL.US", "DENIED.US"]
    assert result.status == "partial_failed"
    assert result.work_units_completed == 2


def test_historical_job_finalizes_parent_run_after_unit_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    runtime = JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(),
        injected_client=object(),
    )
    finish_values: list[dict[str, object]] = []
    monkeypatch.setattr(historical_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(historical_module, "create_task_run", lambda *args, **kwargs: 99)
    monkeypatch.setattr(
        historical_module,
        "load_active_instruments",
        lambda *args, **kwargs: [_instrument("AAPL", 1), _instrument("MSFT", 2)],
    )
    monkeypatch.setattr(
        historical_module,
        "finish_task_run",
        lambda connection, **kwargs: finish_values.append(kwargs),
    )
    monkeypatch.setattr(
        historical_module,
        "load_historical_daily_price_unit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    result = HistoricalDailyJob(asset_types=("stock",)).run(
        symbols=["AAPL", "MSFT"],
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 5),
        runtime=runtime,
    )

    assert result.status == "failed"
    assert result.work_units_completed == 1
    assert result.work_units_failed == 1
    assert result.failures[0].category == "runtime_error"
    assert finish_values[0]["status"] == "failed"


def test_daily_range_budget_rejection_happens_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailClientRuntime(JobRuntime):
        def client(self, *args, **kwargs):
            raise AssertionError("client must not be created for an over-budget preflight")

    runtime = FailClientRuntime(engine=FakeEngine(), config=EodhdRuntimeConfig())
    monkeypatch.setattr(
        range_module.DailyRangeJob,
        "_ensure_calendar_coverage",
        staticmethod(lambda connection, *, date_from, date_to: None),
    )
    monkeypatch.setattr(
        range_module.DailyRangeJob,
        "_load_trading_dates",
        staticmethod(lambda connection, *, date_from, date_to: [date(2024, 1, 2)]),
    )
    monkeypatch.setattr(
        range_module.DailyRangeJob,
        "_count_instruments",
        staticmethod(lambda connection, *, market, asset_types, instrument_status: 10),
    )

    with pytest.raises(ValueError, match="estimated EODHD API calls 100 exceed max-api-calls 99"):
        DailyRangeJob().run(
            execute=True,
            date_from=date(2024, 1, 1),
            date_to=date(2024, 1, 2),
            max_api_calls=99,
            runtime=runtime,
        )


def test_daily_range_requires_complete_calendar_coverage() -> None:
    class FakeScalar:
        def scalar_one(self) -> int:
            return 2

    class FakeConnection:
        def execute(self, statement) -> FakeScalar:
            return FakeScalar()

    with pytest.raises(ValueError, match="market_calendar coverage is incomplete"):
        DailyRangeJob._ensure_calendar_coverage(
            FakeConnection(),
            date_from=date(2023, 1, 1),
            date_to=date(2023, 1, 3),
        )


def test_daily_range_parallel_stop_still_collects_running_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    runtime = JobRuntime(
        engine=engine,
        config=EodhdRuntimeConfig(),
        injected_client=object(),
    )
    results: dict[date, BulkDailyPriceLoadResult | Exception] = {
        date(2023, 1, 3): BulkDailyPriceLoadResult(
            run_id=1,
            status="success",
            exchange="US",
            trade_date=date(2023, 1, 3),
            rows_fetched=10,
            rows_matched=9,
            rows_inserted=8,
            rows_rejected=1,
            api_calls=1,
            rejected_rows=[],
            unmatched_rows=1,
        ),
        date(2023, 1, 4): RuntimeError("boom from worker"),
    }
    started = Barrier(2)

    def fake_run_one_day(
        runtime,
        client,
        *,
        trade_date,
        exchange,
        market,
        asset_types,
        instrument_status,
        identity_resolver,
    ):
        started.wait()
        result = results[trade_date]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(DailyRangeJob, "_run_one_day", staticmethod(fake_run_one_day))
    loaded, failures, cancelled = DailyRangeJob()._execute_dates(
        runtime,
        object(),
        trade_dates=list(results),
        exchange="US",
        market="US",
        asset_types=["stock"],
        instrument_status="active",
        identity_resolver=object(),
        parallel=True,
        workers=2,
        reporter=NullProgressReporter(),
    )

    assert cancelled is False
    assert len(loaded) == 1
    assert loaded[0].rows_inserted == 8
    assert len(failures) == 1
    assert failures[0].category == "exception"


def test_daily_range_reports_actual_weighted_api_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BudgetRuntime(JobRuntime):
        api_budget = None

        def client(self, reporter=None, *, max_requests_per_minute=None, api_budget=None):
            self.api_budget = api_budget
            return object()

    runtime = BudgetRuntime(engine=FakeEngine(), config=EodhdRuntimeConfig())
    trade_dates = [date(2024, 1, 2), date(2024, 1, 3)]
    monkeypatch.setattr(
        DailyRangeJob,
        "_ensure_calendar_coverage",
        staticmethod(lambda connection, *, date_from, date_to: None),
    )
    monkeypatch.setattr(
        range_module.DatedInstrumentIdentityResolver,
        "from_connection",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        DailyRangeJob,
        "_check_remote_api_capacity",
        staticmethod(
            lambda client, *, required_units: {
                "remote_api_requests_used": 100,
                "remote_daily_rate_limit": 100_000,
                "remote_extra_units_remaining": 0,
                "remote_api_units_remaining": 99_900,
                "remote_api_requests_date": "2024-01-03",
                "remote_preflight_api_units": 1,
            }
        ),
    )
    monkeypatch.setattr(
        DailyRangeJob,
        "_load_trading_dates",
        staticmethod(lambda connection, *, date_from, date_to: trade_dates),
    )
    monkeypatch.setattr(
        DailyRangeJob,
        "_count_instruments",
        staticmethod(
            lambda connection, *, market, asset_types, instrument_status: 10
        ),
    )

    def fake_run_one_day(
        runtime,
        client,
        *,
        trade_date,
        exchange,
        market,
        asset_types,
        instrument_status,
        identity_resolver,
    ):
        runtime.api_budget.reserve(endpoint="/eod-bulk-last-day/US", units=100)
        return BulkDailyPriceLoadResult(
            run_id=trade_date.day,
            status="success",
            exchange=exchange,
            trade_date=trade_date,
            rows_fetched=10,
            rows_matched=10,
            rows_inserted=10,
            rows_rejected=0,
            api_calls=1,
            rejected_rows=[],
            unmatched_rows=0,
        )

    monkeypatch.setattr(DailyRangeJob, "_run_one_day", staticmethod(fake_run_one_day))

    result = DailyRangeJob().run(
        execute=True,
        date_from=trade_dates[0],
        date_to=trade_dates[-1],
        instrument_status="all",
        parallel=False,
        max_api_calls=200,
        runtime=runtime,
    )

    assert result.status == "success"
    assert result.parameters["instrument_status"] == "all"
    assert result.metrics["api_units_limit"] == 200
    assert result.metrics["api_units_consumed"] == 200
    assert result.metrics["api_units_remaining"] == 0
    assert result.metrics["task_api_units_consumed"] == 201
    assert result.metrics["remote_api_units_remaining"] == 99_900


def test_daily_range_remote_budget_preflight_is_redacted_and_strict() -> None:
    class UserClient:
        def get_user(self):
            return EodhdApiResponse(
                endpoint="/user",
                status_code=200,
                success=True,
                retry_count=0,
                rows_returned=1,
                duration_ms=1,
                payload=[
                    {
                        "name": "Private User",
                        "email": "private@example.com",
                        "apiRequests": 99_500,
                        "apiRequestsDate": "2026-07-11",
                        "dailyRateLimit": 100_000,
                        "extraLimit": 500,
                    }
                ],
            )

    metrics = DailyRangeJob._check_remote_api_capacity(UserClient(), required_units=1_000)

    assert metrics["remote_api_units_remaining"] == 1_000
    assert "name" not in metrics
    assert "email" not in metrics

    with pytest.raises(ValueError, match="remaining=1000 required=1001"):
        DailyRangeJob._check_remote_api_capacity(UserClient(), required_units=1_001)
