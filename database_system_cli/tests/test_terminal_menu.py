import json

import pytest
from typer.testing import CliRunner

import fdp.cli as cli_module
import fdp.menu.app as menu_module
from fdp.cli import app
from fdp.get_data.contracts import JobPreflight, JobResult, ProgressEvent


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
    registered = {definition.key for definition in menu_module.INGEST_JOB_DEFINITIONS}

    assert set(menu_module.JOB_HANDLERS) == registered


def test_every_menu_registered_ingest_job_factory_constructs() -> None:
    for definition in menu_module.INGEST_JOB_DEFINITIONS:
        assert definition.factory() is not None


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
