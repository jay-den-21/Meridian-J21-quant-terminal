from datetime import date

import pytest
from typer.testing import CliRunner

import fdp.cli as cli_module
from fdp.cli import app
from fdp.config import EodhdRuntimeConfig
from fdp.sources.eodhd.ingest import BulkDailyPriceLoadResult


def test_cli_registers_instrument_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "instruments", "--help"])

    assert result.exit_code == 0
    assert "--market" in result.output
    assert "--source" in result.output
    assert "--rename-from" in result.output


def test_cli_registers_history_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "history", "--help"])

    assert result.exit_code == 0
    assert "--symbols" in result.output
    assert "--from" in result.output
    assert "--to" in result.output


def test_cli_registers_indices_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "indices", "--help"])

    assert result.exit_code == 0
    assert "--provider-symbols" in result.output
    assert "--from" in result.output
    assert "--to" in result.output


def test_cli_registers_calendar_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "calendar", "--help"])

    assert result.exit_code == 0
    assert "--market" in result.output
    assert "--from" in result.output
    assert "--to" in result.output


def test_cli_registers_daily_bulk_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "daily", "--help"])

    assert result.exit_code == 0
    assert "--exchange" in result.output
    assert "--date" in result.output
    assert "--symbols" in result.output
    assert "--asset-types" in result.output


def test_cli_registers_daily_range_ingest_command() -> None:
    result = CliRunner().invoke(
        app,
        ["ingest", "daily-range", "--help"],
        env={"COLUMNS": "200"},
    )

    assert result.exit_code == 0
    assert "--parallel" in result.output
    assert "--sequential" in result.output
    assert "--workers" in result.output
    assert "--max-requests-per-minute" in result.output
    assert "--max-api-calls" in result.output


def test_cli_registers_daily_price_validate_command() -> None:
    result = CliRunner().invoke(app, ["validate", "daily-price", "--help"])

    assert result.exit_code == 0
    assert "--from" in result.output
    assert "--to" in result.output
    assert "--asset-types" in result.output


def test_cli_registers_repair_commands() -> None:
    runner = CliRunner()

    plan = runner.invoke(app, ["repair", "plan-daily-price", "--help"])
    list_result = runner.invoke(app, ["repair", "list", "--help"])
    confirm = runner.invoke(app, ["repair", "confirm", "--help"])
    run = runner.invoke(app, ["repair", "run", "--help"])

    assert plan.exit_code == 0
    assert "--asset-types" in plan.output
    assert "--from" in plan.output
    assert "--to" in plan.output
    assert list_result.exit_code == 0
    assert "--status" in list_result.output
    assert "--json" in list_result.output
    assert confirm.exit_code == 0
    assert "--plan-id" in confirm.output
    assert "--yes" in confirm.output
    assert run.exit_code == 0
    assert "--plan-id" in run.output
    assert "--yes" in run.output
    assert "--json" in run.output


def test_cli_registers_quarantine_commands() -> None:
    runner = CliRunner()

    plan = runner.invoke(app, ["quarantine", "plan-daily-price", "--help"])
    list_result = runner.invoke(app, ["quarantine", "list", "--help"])
    confirm = runner.invoke(app, ["quarantine", "confirm", "--help"])
    run = runner.invoke(app, ["quarantine", "run", "--help"])

    assert plan.exit_code == 0
    assert "--issue-types" in plan.output
    assert "duplicate_key" in plan.output
    assert "--asset-types" in plan.output
    assert "--from" in plan.output
    assert "--to" in plan.output
    assert list_result.exit_code == 0
    assert "--status" in list_result.output
    assert "--json" in list_result.output
    assert confirm.exit_code == 0
    assert "--plan-id" in confirm.output
    assert "--yes" in confirm.output
    assert run.exit_code == 0
    assert "--plan-id" in run.output
    assert "--yes" in run.output
    assert "--json" in run.output


def test_cli_registers_research_daily_prices_command() -> None:
    result = CliRunner().invoke(app, ["research", "daily-prices", "--help"])

    assert result.exit_code == 0
    assert "--symbols" in result.output
    assert "--from" in result.output
    assert "--to" in result.output
    assert "--asset-type" in result.output
    assert "--adjusted" in result.output
    assert "--raw" in result.output


def test_cli_research_daily_prices_requires_dates_before_database_connection() -> None:
    result = CliRunner().invoke(app, ["research", "daily-prices", "--symbols", "AAPL"])

    assert result.exit_code != 0
    assert "requires --from and --to" in result.output


def test_retry_progress_message_includes_eodhd_error_and_operator_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    event = cli_module.EodhdApiEvent(
        kind="retry",
        endpoint="/eod-bulk-last-day/US",
        attempt=2,
        max_attempts=6,
        status_code=429,
        error_message="HTTP 429: rate limit",
        retry_delay_seconds=61,
    )

    monkeypatch.setattr(cli_module.typer, "echo", messages.append)
    cli_module._echo_eodhd_event(event)

    message = messages[0]
    assert "status=429" in message
    assert "error=HTTP 429: rate limit" in message
    assert "请稍等1分钟，马上重试～ (≧∇≦)" in message
    assert "wait=61s" in message


def test_bulk_daily_range_api_call_estimate_uses_eodhd_bulk_cost() -> None:
    assert cli_module._estimated_bulk_daily_api_calls(trading_days=3, symbols=None) == 300
    assert (
        cli_module._estimated_bulk_daily_api_calls(
            trading_days=3,
            symbols=["AAPL", "MSFT"],
        )
        == 306
    )


def test_daily_range_refuses_api_budget_before_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEngine:
        def begin(self) -> "FakeEngine":
            return self

        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fail_api_key() -> str:
        raise AssertionError("api key must not be read when estimate is over budget")

    monkeypatch.setattr(cli_module, "database_url_from_env", lambda: "sqlite://")
    monkeypatch.setattr(cli_module, "create_engine", lambda url: FakeEngine())
    monkeypatch.setattr(cli_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(
        cli_module,
        "_ensure_calendar_coverage",
        lambda connection, *, date_from, date_to: None,
    )
    monkeypatch.setattr(
        cli_module,
        "_load_trading_dates",
        lambda connection, *, date_from, date_to: [date(2023, 1, 3)],
    )
    monkeypatch.setattr(
        cli_module,
        "_count_active_instruments",
        lambda connection, *, market, asset_types: 10,
    )
    monkeypatch.setattr(
        cli_module,
        "eodhd_runtime_config_from_env",
        lambda: EodhdRuntimeConfig(daily_call_budget=100_000),
    )
    monkeypatch.setattr(cli_module, "eodhd_api_key_from_env", fail_api_key)

    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "daily-range",
            "--from",
            "2023-01-01",
            "--to",
            "2023-01-03",
            "--max-api-calls",
            "99",
            "--execute",
            "--yes",
        ],
    )

    assert result.exit_code != 0
    assert "estimated EODHD API calls 100 exceed max-api-calls 99" in result.output


def test_ensure_calendar_coverage_refuses_incomplete_range() -> None:
    class FakeScalar:
        def scalar_one(self) -> int:
            return 2

    class FakeConnection:
        def execute(self, statement) -> FakeScalar:
            return FakeScalar()

    with pytest.raises(cli_module.typer.BadParameter, match="market_calendar coverage is incomplete"):
        cli_module._ensure_calendar_coverage(
            FakeConnection(),
            date_from=date(2023, 1, 1),
            date_to=date(2023, 1, 3),
        )


def test_run_daily_range_ingest_aggregates_parallel_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = {
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

    def fake_run_one_day(engine, client, *, trade_date, exchange, market, asset_types):
        result = results[trade_date]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cli_module, "_run_one_daily_range_day", fake_run_one_day)

    totals = cli_module._run_daily_range_ingest(
        object(),
        object(),
        trade_dates=[date(2023, 1, 3), date(2023, 1, 4)],
        exchange="US",
        market="US",
        asset_types=["stock"],
        parallel=True,
        workers=2,
    )

    assert totals == {
        "rows_fetched": 10,
        "rows_matched": 9,
        "rows_inserted": 8,
        "rows_rejected": 1,
        "api_calls": 1,
        "success": 1,
        "partial_failed": 0,
        "failed": 1,
    }
