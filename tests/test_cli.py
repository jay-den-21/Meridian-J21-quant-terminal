from typer.testing import CliRunner

from fdp.cli import app


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
