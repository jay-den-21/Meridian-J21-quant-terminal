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


def test_cli_registers_daily_bulk_ingest_command() -> None:
    result = CliRunner().invoke(app, ["ingest", "daily", "--help"])

    assert result.exit_code == 0
    assert "--exchange" in result.output
    assert "--date" in result.output
    assert "--symbols" in result.output
    assert "--asset-types" in result.output


def test_cli_registers_daily_price_validate_command() -> None:
    result = CliRunner().invoke(app, ["validate", "daily-price", "--help"])

    assert result.exit_code == 0
    assert "--from" in result.output
    assert "--to" in result.output
    assert "--asset-types" in result.output


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
