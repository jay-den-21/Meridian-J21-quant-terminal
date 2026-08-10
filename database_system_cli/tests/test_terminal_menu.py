import json
from datetime import date
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import fdp.cli as cli_module
import fdp.menu.app as menu_module
from fdp.cli import app
from fdp.bulk_unmatched import BulkUnmatchedSummaryRow
from fdp.get_data.contracts import JobPreflight, JobResult, ProgressEvent
from fdp.menu.reconcile_ui import RichReconcileProgressReporter, hold_summary_for_review


class FakeStream:
    def __init__(self, is_tty: bool) -> None:
        self.is_tty = is_tty

    def isatty(self) -> bool:
        return self.is_tty


class FakePrompts:
    def __init__(self) -> None:
        self.select_answers = iter(["zh", "ingest", "instruments", "exit"])
        self.confirm_answers = iter([False, False])

    def select(self, message, choices, *, default=None):
        return next(self.select_answers)

    def checkbox(self, message, choices, *, defaults=None):
        raise AssertionError("checkbox should not be called")

    def text(self, message, *, default=""):
        raise AssertionError("text should not be called when advanced settings are skipped")

    def confirm(self, message, *, default=False):
        return next(self.confirm_answers)


def test_terminal_menu_requires_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(menu_module.sys, "stdin", FakeStream(False))
    monkeypatch.setattr(menu_module.sys, "stdout", FakeStream(False))

    with pytest.raises(RuntimeError, match="requires an interactive TTY"):
        menu_module.run_terminal_menu()


def test_terminal_menu_defaults_to_cancel_before_job_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(menu_module.JobRuntime, "from_env", lambda: object())

    def fail_run(self, **kwargs):
        raise AssertionError("job run must not execute after the default cancel choice")

    monkeypatch.setattr(menu_module.ActiveInstrumentsJob, "run", fail_run)
    menu_module.run_terminal_menu(FakePrompts(), force_tty=True)


def test_ingest_json_output_is_one_machine_readable_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result_model = JobResult(
        job="ingest.instruments",
        status="success",
        run_id=12,
        parameters={"market": "US"},
        parameter_sources={"market": "cli"},
        rows_fetched=10,
        rows_matched=9,
        rows_inserted=9,
        api_calls=2,
        work_units_total=2,
        work_units_completed=2,
    )
    def fake_run(self, **kwargs):
        kwargs["reporter"].on_event(
            ProgressEvent(
                kind="finish",
                job="ingest.instruments",
                completed=2,
                total=2,
                message="success",
            )
        )
        return result_model

    monkeypatch.setattr(cli_module.ActiveInstrumentsJob, "run", fake_run)

    result = CliRunner().invoke(
        app,
        ["ingest", "instruments", "--output", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["job"] == "ingest.instruments"
    assert payload["rows_inserted"] == 9
    assert "ingest.instruments progress" in result.stderr
    assert "progress" not in result.stdout


def test_cli_registers_menu_and_history_asset_types() -> None:
    runner = CliRunner()

    root_help = runner.invoke(app, ["--help"])
    history_help = runner.invoke(app, ["ingest", "history", "--help"])

    assert root_help.exit_code == 0
    assert "menu" in root_help.output
    assert history_help.exit_code == 0
    assert "--asset-types" in history_help.output


def test_every_registered_ingest_job_has_a_menu_handler() -> None:
    registered = {definition.key for definition in menu_module.MENU_JOB_DEFINITIONS}

    assert set(menu_module.JOB_HANDLERS) == registered


def test_every_menu_registered_ingest_job_factory_constructs() -> None:
    for definition in menu_module.MENU_JOB_DEFINITIONS:
        assert definition.factory() is not None


def test_intraday_menu_builds_bilingual_validation_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class IntradayPrompts:
        def __init__(self) -> None:
            self.text_answers = iter(["AAPL.US", "2024-01-02", "2024-01-02"])

        def text(self, message, *, default=""):
            return next(self.text_answers)

        def confirm(self, message, *, default=False):
            return False

    class FakeJob:
        def preflight(self, **kwargs):
            captured["kwargs"] = kwargs
            return JobPreflight(
                job="validate.intraday",
                job_module="fdp.get_data.intraday.validate_eodhd",
                target_tables=["system.intraday_file_manifest"],
                work_units=1,
                estimated_api_calls=6,
                parameters={},
                parameter_sources={},
            )

    def capture_confirmation(session, language, preflight, command, runner):
        captured["language"] = language
        captured["command"] = command

    monkeypatch.setattr(menu_module.JobRuntime, "from_env", lambda: object())
    monkeypatch.setattr(menu_module, "EodhdIntradayValidationJob", FakeJob)
    monkeypatch.setattr(menu_module, "_confirm_and_run", capture_confirmation)

    menu_module._run_intraday_validation(IntradayPrompts(), "zh")

    assert captured["language"] == "zh"
    assert captured["kwargs"]["symbols"] == ["AAPL.US"]
    assert captured["command"] == (
        "poetry run j21 validate intraday --symbols AAPL.US --from 2024-01-02 "
        "--to 2024-01-02 --source eodhd --interval 1m --market US "
        "--max-api-calls 200 --execute --yes"
    )


def test_menu_closes_progress_reporter_when_job_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    class ConfirmPrompts:
        def confirm(self, message, *, default=False):
            return True

    class FakeReporter:
        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(menu_module, "TqdmProgressReporter", FakeReporter)
    preflight = JobPreflight(
        job="ingest.test",
        job_module="fdp.get_data.test",
        target_tables=[],
        work_units=1,
        estimated_api_calls=0,
        parameters={},
        parameter_sources={},
    )

    with pytest.raises(RuntimeError, match="failed after progress started"):
        menu_module._confirm_and_run(
            ConfirmPrompts(),
            "en",
            preflight,
            "poetry run j21 ingest test",
            lambda reporter: (_ for _ in ()).throw(RuntimeError("failed after progress started")),
        )

    assert closed == [True]


def test_id_mapping_menu_builds_symbol_scope_for_shared_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class MappingPrompts:
        def select(self, message, choices, *, default=None):
            return "symbols"

        def text(self, message, *, default=""):
            return "AAPL.US,MSFT.US"

        def confirm(self, message, *, default=False):
            return False

    class FakeJob:
        def preflight(self, **kwargs):
            captured["preflight_kwargs"] = kwargs
            return JobPreflight(
                job="ingest.id_mappings",
                job_module="fdp.get_data.reference.get_id_mappings",
                target_tables=["instrument_identifier_history"],
                work_units=2,
                estimated_api_calls=2,
                parameters={"scope": "symbols"},
                parameter_sources={"scope": "menu"},
            )

        def run(self, **kwargs):
            raise AssertionError("captured confirmation adapter must not execute the job")

    def capture_confirmation(session, language, preflight, command, runner):
        captured["command"] = command
        captured["preflight"] = preflight

    monkeypatch.setattr(menu_module.JobRuntime, "from_env", lambda: object())
    monkeypatch.setattr(menu_module, "IdentifierMappingJob", FakeJob)
    monkeypatch.setattr(menu_module, "_confirm_and_run", capture_confirmation)

    menu_module._run_id_mappings(MappingPrompts(), "en")

    preflight_kwargs = captured["preflight_kwargs"]
    assert preflight_kwargs["exchange"] is None
    assert preflight_kwargs["symbols"] == ["AAPL.US", "MSFT.US"]
    assert preflight_kwargs["page_limit"] == 1000
    assert preflight_kwargs["max_api_calls"] == 200
    assert captured["command"] == (
        "poetry run j21 ingest id-mappings --symbols AAPL.US,MSFT.US "
        "--page-limit 1000 --max-api-calls 200"
    )


def test_corporate_action_menu_builds_full_scope_for_shared_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class CorporateActionPrompts:
        def __init__(self) -> None:
            self.select_answers = iter(["full", "active"])
            self.checkbox_answers = iter(
                [["dividend", "split"], ["stock", "etf"]]
            )

        def select(self, message, choices, *, default=None):
            return next(self.select_answers)

        def checkbox(self, message, choices, *, defaults=None):
            return next(self.checkbox_answers)

        def text(self, message, *, default=""):
            return ""

        def confirm(self, message, *, default=False):
            return False

    class FakeJob:
        def preflight(self, **kwargs):
            captured["preflight_kwargs"] = kwargs
            return JobPreflight(
                job="ingest.corporate_actions",
                job_module="fdp.get_data.corporate_actions.get_history",
                target_tables=["corporate_action"],
                work_units=10,
                estimated_api_calls=21,
                parameters={"selected_instruments": 10},
                parameter_sources={},
            )

        def run(self, **kwargs):
            raise AssertionError("confirmation adapter must own execution")

    def capture_confirmation(session, language, preflight, command, runner):
        captured["command"] = command

    runtime = SimpleNamespace(config=SimpleNamespace(max_requests_per_minute=600))
    monkeypatch.setattr(menu_module.JobRuntime, "from_env", lambda: runtime)
    monkeypatch.setattr(menu_module, "CorporateActionsHistoryJob", FakeJob)
    monkeypatch.setattr(menu_module, "_confirm_and_run", capture_confirmation)

    menu_module._run_corporate_actions(CorporateActionPrompts(), "en")

    kwargs = captured["preflight_kwargs"]
    assert kwargs["symbols"] is None
    assert kwargs["action_types"] == ["dividend", "split"]
    assert "asset_types" not in kwargs
    assert kwargs["instrument_status"] == "active"
    assert captured["command"] == (
        "poetry run j21 ingest corporate-actions --action-types dividend,split "
        "--instrument-status active --execute --yes"
    )


def test_guided_reconcile_keeps_one_run_id_through_classify_route_and_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class ConfirmPrompts:
        def __init__(self) -> None:
            self.defaults: list[bool] = []

        def confirm(self, message, *, default=False):
            self.defaults.append(default)
            return True

    class FakeJob:
        def preflight(self, **kwargs):
            return JobPreflight(
                job="reconcile.bulk_unmatched",
                job_module="fdp.get_data.reconcile.bulk_unmatched",
                target_tables=["system.bulk_unmatched_daily_price_observation"],
                work_units=2,
                estimated_api_calls=0,
                parameters={"statuses": kwargs["statuses"]},
                parameter_sources={"statuses": "menu"},
            )

        def summary(self, **kwargs):
            return [BulkUnmatchedSummaryRow("unresolved", "stock", 2)]

        def classify(self, **kwargs):
            assert kwargs["statuses"] == ["unresolved", "needs_instrument", "unknown"]
            calls.append(("classify", kwargs["run_id"]))
            return JobResult(
                job="reconcile.bulk_unmatched.classify",
                status="success",
                run_id=42,
                parameters={},
                parameter_sources={},
                metrics={"checkpoint_phase": "route"},
            )

        def route(self, **kwargs):
            calls.append(("route_execute" if kwargs["execute"] else "route_preview", kwargs["run_id"]))
            return JobResult(
                job="reconcile.bulk_unmatched.route",
                status="success" if kwargs["execute"] else "dry_run",
                run_id=42,
                parameters={},
                parameter_sources={},
                metrics={
                    "checkpoint_phase": "validation" if kwargs["execute"] else "route",
                    "remaining_groups": 0,
                },
            )

        def validate(self, **kwargs):
            calls.append(("validate", kwargs["run_id"]))
            return JobResult(
                job="reconcile.bulk_unmatched.validate",
                status="success",
                run_id=42,
                parameters={},
                parameter_sources={},
                metrics={
                    "checkpoint_phase": "complete",
                    "quality_issue_count": 0,
                    "route_failed": 0,
                },
            )

        def list(self, **kwargs):
            return []

    prompts = ConfirmPrompts()
    monkeypatch.setattr(menu_module, "BulkUnmatchedReconcileJob", FakeJob)
    monkeypatch.setattr(menu_module, "show_reconcile_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr(menu_module, "hold_summary_for_review", lambda *args, **kwargs: None)
    monkeypatch.setattr(menu_module, "play_j21_logo", lambda *args, **kwargs: None)
    monkeypatch.setattr(menu_module, "show_reconcile_final_report", lambda *args, **kwargs: None)

    menu_module._run_guided_reconcile(
        prompts,
        "en",
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        runtime=object(),
    )

    assert calls == [
        ("classify", None),
        ("route_preview", 42),
        ("route_execute", 42),
        ("validate", 42),
    ]
    assert prompts.defaults == [False, False]


def test_rich_reconcile_reporter_plain_mode_closes_on_finish(capsys) -> None:
    reporter = RichReconcileProgressReporter(interactive=False)
    reporter.on_event(ProgressEvent("start", "reconcile.test", 0, 2, message="run_id=1"))
    reporter.on_event(
        ProgressEvent(
            "unit_completed",
            "reconcile.test",
            1,
            2,
            unit="batch-1",
            message="checkpoint=10",
            counters={"routed": 1},
        )
    )
    reporter.on_event(ProgressEvent("finish", "reconcile.test", 2, 2, message="success"))

    output = capsys.readouterr().out
    assert "batch=batch-1" in output
    assert "checkpoint=checkpoint=10" in output
    assert reporter._live is None


def test_reconcile_countdown_is_zero_wait_outside_tty() -> None:
    started = __import__("time").monotonic()
    hold_summary_for_review(seconds=10, language="en", interactive=False)
    assert __import__("time").monotonic() - started < 0.1


@pytest.mark.parametrize(
    ("date_text", "expected_default"),
    [("", "active"), ("2024-01-02", "all")],
)
def test_bulk_daily_menu_status_default_depends_on_explicit_history_date(
    date_text: str,
    expected_default: str,
) -> None:
    class StatusDefaultPrompts:
        def __init__(self) -> None:
            self.text_values = iter([date_text, ""])
            self.status_default: str | None = None

        def text(self, message, *, default=""):
            return next(self.text_values)

        def checkbox(self, message, choices, *, defaults=None):
            return sorted(defaults)

        def select(self, message, choices, *, default=None):
            self.status_default = default
            return None

    prompts = StatusDefaultPrompts()

    with pytest.raises(menu_module.MenuCancelled):
        menu_module._run_bulk_daily(prompts, "en")

    assert prompts.status_default == expected_default


def test_daily_range_menu_defaults_to_active_and_inactive() -> None:
    class RangeStatusPrompts:
        def __init__(self) -> None:
            self.text_values = iter(["2024-01-02", "2024-01-03"])
            self.status_default: str | None = None

        def text(self, message, *, default=""):
            return next(self.text_values)

        def checkbox(self, message, choices, *, defaults=None):
            return sorted(defaults)

        def select(self, message, choices, *, default=None):
            self.status_default = default
            return None

    prompts = RangeStatusPrompts()

    with pytest.raises(menu_module.MenuCancelled):
        menu_module._run_daily_range(prompts, "en")

    assert prompts.status_default == "all"


@pytest.mark.parametrize(
    ("answers", "expected"),
    [(["continue", "auto"], (False, False)), (["new", "manual"], (True, True))],
)
def test_daily_menu_exposes_resume_new_and_auto_manual_modes(
    answers: list[str],
    expected: tuple[bool, bool],
) -> None:
    class ModePrompts:
        def __init__(self) -> None:
            self.answers = iter(answers)

        def select(self, message, choices, *, default=None):
            return next(self.answers)

    assert menu_module._daily_task_mode(ModePrompts(), "zh") == expected
