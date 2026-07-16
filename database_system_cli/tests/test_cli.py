import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

import fdp.cli as cli_module
from fdp.cli import app
from fdp.get_data.contracts import JobResult
from fdp.get_data.reconcile.workflow import new_reconcile_checkpoint
from fdp.sources.eodhd.retry import EodhdApiEvent


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
    assert "--instrument-status" in result.output


def test_cli_registers_bounded_technical_validation_command() -> None:
    result = CliRunner().invoke(app, ["research", "technical-validate", "--help"])

    assert result.exit_code == 0
    assert "--max-api-units" in result.output
    assert "--output" in result.output


def test_json_mode_eodhd_progress_is_written_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    client = cli_module._eodhd_client("test-token", progress_to_stderr=True)
    assert client.progress_callback is not None

    client.progress_callback(
        EodhdApiEvent(kind="request", endpoint="/technical/AAPL.US", attempt=1, max_attempts=1)
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "/technical/AAPL.US" in captured.err


def test_cli_history_routes_fund_asset_type_to_fund_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, object]] = []

    def fake_run(self, **kwargs):
        seen.append(kwargs)
        return JobResult(
            job="ingest.history",
            status="success",
            run_id=1,
            parameters={"asset_types": ["fund"]},
            parameter_sources={},
        )

    monkeypatch.setattr(cli_module.FundDailyJob, "run", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "history",
            "--symbols",
            "VFINX",
            "--from",
            "2024-01-01",
            "--to",
            "2024-01-31",
            "--asset-types",
            "fund",
        ],
    )

    assert result.exit_code == 0
    assert seen[0]["symbols"] == ["VFINX"]


def test_cli_registers_indices_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "indices", "--help"])

    assert result.exit_code == 0
    assert "--provider-symbols" in result.output
    assert "--from" in result.output
    assert "--to" in result.output


def test_cli_indices_executes_the_index_daily_job(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(self, **kwargs):
        calls.append(kwargs)
        return JobResult(
            job="ingest.indices",
            status="success",
            run_id=2,
            parameters={"asset_types": ["index"]},
            parameter_sources={},
            work_units_total=4,
            work_units_completed=4,
        )

    monkeypatch.setattr(cli_module.IndexDailyJob, "run", fake_run)
    result = CliRunner().invoke(
        app,
        ["ingest", "indices", "--from", "2024-01-01", "--to", "2024-01-05"],
    )

    assert result.exit_code == 0, result.output
    assert calls[0]["override_source"] == "cli"


def test_cli_registers_calendar_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "calendar", "--help"])

    assert result.exit_code == 0
    assert "--market" in result.output
    assert "--from" in result.output
    assert "--to" in result.output


def test_cli_documentation_and_html_mirrors_are_current() -> None:
    repository_root = Path(__file__).parents[2]
    result = CliRunner().invoke(
        app,
        ["validate", "docs-staleness", "--root", str(repository_root)],
    )

    assert result.exit_code == 0, result.output
    assert "status=current" in result.output


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


def test_cli_registers_guarded_fund_daily_price_migration() -> None:
    runner = CliRunner()
    help_result = runner.invoke(app, ["migrate", "fund-daily-price", "--help"])
    unsafe_copy = runner.invoke(
        app,
        ["migrate", "fund-daily-price", "--phase", "copy"],
    )

    assert help_result.exit_code == 0
    assert "--backup-file" in help_result.output
    assert "--run-id" in help_result.output
    assert unsafe_copy.exit_code != 0
    assert "requires --execute --yes" in unsafe_copy.output


def test_cli_registers_guarded_asset_type_reconcile() -> None:
    runner = CliRunner()
    help_result = runner.invoke(app, ["migrate", "daily-price-asset-types", "--help"])
    unsafe_execute = runner.invoke(
        app,
        ["migrate", "daily-price-asset-types", "--phase", "execute"],
    )

    assert help_result.exit_code == 0
    assert "--chunk-size" in help_result.output
    assert unsafe_execute.exit_code != 0
    assert "requires --execute --yes" in unsafe_execute.output


def test_cli_registers_bulk_unmatched_commands() -> None:
    runner = CliRunner()

    route = runner.invoke(app, ["ingest", "bulk-unmatched-route", "--help"])
    summary = runner.invoke(app, ["research", "bulk-unmatched", "summary", "--help"])
    list_result = runner.invoke(app, ["research", "bulk-unmatched", "list", "--help"])
    classify = runner.invoke(app, ["research", "bulk-unmatched", "classify", "--help"])

    assert route.exit_code == 0
    assert "--execute" in route.output
    assert "--yes" in route.output
    assert summary.exit_code == 0
    assert "--from" in summary.output
    assert list_result.exit_code == 0
    assert "--status" in list_result.output
    assert classify.exit_code == 0
    assert "--limit" in classify.output


def test_cli_registers_guided_bulk_reconcile_commands() -> None:
    runner = CliRunner()
    root = runner.invoke(app, ["reconcile", "bulk-unmatched", "--help"])

    assert root.exit_code == 0
    for command in ("summary", "list", "classify", "route", "status"):
        assert command in root.output
    classify = runner.invoke(app, ["reconcile", "bulk-unmatched", "classify", "--help"])
    route = runner.invoke(app, ["reconcile", "bulk-unmatched", "route", "--help"])
    assert "--statuses" in classify.output
    assert "--batch-size" in classify.output
    assert "--run-id" in classify.output
    assert "--execute" in route.output
    assert "--batch-size" in route.output


def test_cli_requires_advanced_flag_for_risky_reclassification_states() -> None:
    result = CliRunner().invoke(
        app,
        [
            "reconcile",
            "bulk-unmatched",
            "classify",
            "--from",
            "2024-01-02",
            "--to",
            "2024-01-02",
            "--statuses",
            "unresolved,ambiguous",
        ],
    )

    assert result.exit_code != 0
    assert "requires --advanced" in result.output


def test_reconcile_classify_json_stdout_is_one_job_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module.BulkUnmatchedReconcileJob,
        "classify",
        lambda self, **kwargs: JobResult(
            job="reconcile.bulk_unmatched.classify",
            status="success",
            run_id=71,
            parameters={},
            parameter_sources={},
            api_calls=0,
            metrics={"remaining_eligible": 0, "checkpoint_phase": "route"},
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "reconcile",
            "bulk-unmatched",
            "classify",
            "--from",
            "2024-01-02",
            "--to",
            "2024-01-02",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["run_id"] == 71


def test_reconcile_status_text_shows_safe_cursors_and_resume_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = new_reconcile_checkpoint(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 3),
        market="US",
        source_statuses=["unresolved"],
        status_counts={"unresolved": 10},
        snapshot_max_by_status={"unresolved": 99},
    )
    checkpoint["classify"].update(
        {
            "rows_processed": 5,
            "batches_committed": 1,
            "last_trade_date": "2024-01-02",
            "last_observation_id": 55,
        }
    )
    monkeypatch.setattr(
        cli_module.BulkUnmatchedReconcileJob,
        "status",
        lambda self, **kwargs: {
            "status": "partial_failed",
            "checkpoint": checkpoint,
            "api_calls": 0,
            "resume_hint": "resume-command",
        },
    )

    result = CliRunner().invoke(
        app,
        ["reconcile", "bulk-unmatched", "status", "--run-id", "71"],
    )

    assert result.exit_code == 0
    assert "checkpoint=2024-01-02/55" in result.output
    assert "api_calls=0" in result.output
    assert "resume_hint=resume-command" in result.output


def test_legacy_bulk_reconcile_help_remains_available_in_v04() -> None:
    result = CliRunner().invoke(
        app,
        [
            "research",
            "bulk-unmatched",
            "summary",
            "--from",
            "bad-date",
            "--to",
            "2024-01-02",
        ],
    )

    assert result.exit_code != 0
    assert "DEPRECATED v0.4" in result.stderr
    assert "j21 reconcile bulk-unmatched summary" in result.stderr


def test_history_cli_accepts_index_as_a_supported_historical_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(self, **kwargs):
        captured.update(kwargs)
        return JobResult(
            job="ingest.history",
            status="success",
            run_id=9,
            parameters={},
            parameter_sources={},
        )

    monkeypatch.setattr(cli_module.HistoricalDailyJob, "run", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "history",
            "--symbols",
            "GSPC.INDX",
            "--from",
            "2024-01-01",
            "--to",
            "2024-01-03",
            "--asset-types",
            "index",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["symbols"] == ["GSPC.INDX"]


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


def test_daily_range_refuses_api_budget_before_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_over_budget(self, **kwargs):
        raise ValueError("estimated EODHD API calls 100 exceed max-api-calls 99")

    monkeypatch.setattr(cli_module.DailyRangeJob, "run", fail_over_budget)

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


def test_bulk_daily_commands_expose_point_in_time_instrument_scope() -> None:
    runner = CliRunner()

    daily = runner.invoke(app, ["ingest", "daily", "--help"])
    daily_range = runner.invoke(app, ["ingest", "daily-range", "--help"])

    assert daily.exit_code == 0
    assert "--instrument-status" in daily.output
    assert daily_range.exit_code == 0
    assert "--instrument-status" in daily_range.output


def test_cli_registers_delisted_instruments_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "delisted-instruments", "--help"])

    assert result.exit_code == 0
    assert "--market" in result.output
    assert "--source" in result.output


def test_cli_registers_id_mapping_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "id-mappings", "--help"])

    assert result.exit_code == 0
    assert "--exchange" in result.output
    assert "--symbols" in result.output
    assert "--start-offset" in result.output
    assert "--max-api-calls" in result.output


def test_id_mapping_cli_passes_symbol_scope_to_shared_job_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(self, **kwargs):
        captured.update(kwargs)
        return cli_module.JobResult(
            job="ingest.id_mappings",
            status="success",
            run_id=44,
            parameters={"scope": "symbols", "symbols": ["AAPL.US", "MSFT.US"]},
            parameter_sources={"scope": "cli", "symbols": "cli"},
            rows_fetched=2,
            rows_matched=2,
            rows_inserted=10,
            api_calls=3,
            work_units_total=2,
            work_units_completed=2,
        )

    monkeypatch.setattr(cli_module.IdentifierMappingJob, "run", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "id-mappings",
            "--symbols",
            "AAPL.US,MSFT.US",
            "--max-api-calls",
            "2",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["job"] == "ingest.id_mappings"
    assert captured["exchange"] is None
    assert captured["symbols"] == ["AAPL.US", "MSFT.US"]
    assert captured["max_api_calls"] == 2
    assert captured["execute"] is True
    assert captured["override_source"] == "cli"


def test_cli_history_supports_include_inactive_flag() -> None:
    result = CliRunner().invoke(app, ["ingest", "history", "--help"])

    assert result.exit_code == 0
    assert "--include-inactive" in result.output


def test_history_instrument_status_rejects_conflicting_legacy_flag() -> None:
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "history",
            "--symbols",
            "OLD.US",
            "--from",
            "2020-01-01",
            "--to",
            "2020-01-31",
            "--instrument-status",
            "inactive",
            "--include-inactive",
        ],
    )

    assert result.exit_code != 0
    assert "do not combine" in result.output
