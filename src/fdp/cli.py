from datetime import date

import typer
from sqlalchemy import create_engine

from fdp.config import database_url_from_env, eodhd_api_key_from_env
from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import (
    DEFAULT_INDEX_PROVIDER_SYMBOLS,
    SYMBOL_CHANGE_HISTORY_START,
    load_index_daily_prices,
    load_exchange_symbols,
    load_historical_daily_prices,
    load_market_calendar,
)
from fdp.storage.schema import ensure_runtime_schemas

app = typer.Typer(help="Financial data platform command line interface.")
ingest_app = typer.Typer(help="Ingest source data into the database.")
app.add_typer(ingest_app, name="ingest")


@app.callback()
def main() -> None:
    """Project CLI entrypoint."""


@ingest_app.command("instruments")
def ingest_instruments(
    market: str = typer.Option("US", "--market", help="Market code to ingest."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
    rename_from: str = typer.Option(
        SYMBOL_CHANGE_HISTORY_START.isoformat(),
        "--rename-from",
        help="Earliest EODHD symbol-change-history date to reconcile.",
    ),
) -> None:
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    try:
        rename_from_date = date.fromisoformat(rename_from)
    except ValueError as exc:
        raise typer.BadParameter("rename-from must be YYYY-MM-DD") from exc

    api_key = eodhd_api_key_from_env()
    engine = create_engine(database_url_from_env())
    client = EodhdClient(api_key=api_key)

    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        result = load_exchange_symbols(connection, client, market=market, rename_from=rename_from_date)

    typer.echo(
        "instrument ingest "
        f"run_id={result.run_id} status={result.status} "
        f"fetched={result.rows_fetched} accepted={result.rows_accepted} "
        f"rejected={result.rows_rejected}"
    )


@ingest_app.command("history")
def ingest_history(
    symbols: str = typer.Option(..., "--symbols", help="Comma-separated current symbols to ingest."),
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market code to ingest."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
) -> None:
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    parsed_symbols = [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]
    if not parsed_symbols:
        raise typer.BadParameter("symbols must contain at least one symbol")

    try:
        parsed_from = date.fromisoformat(date_from)
        parsed_to = date.fromisoformat(date_to)
    except ValueError as exc:
        raise typer.BadParameter("from/to must be YYYY-MM-DD") from exc
    if parsed_to < parsed_from:
        raise typer.BadParameter("to must be greater than or equal to from")

    api_key = eodhd_api_key_from_env()
    engine = create_engine(database_url_from_env())
    client = EodhdClient(api_key=api_key)

    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        result = load_historical_daily_prices(
            connection,
            client,
            symbols=parsed_symbols,
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
        )

    typer.echo(
        "history ingest "
        f"run_id={result.run_id} status={result.status} "
        f"symbols={result.symbols_loaded}/{result.symbols_requested} "
        f"fetched={result.rows_fetched} inserted={result.rows_inserted} "
        f"rejected={result.rows_rejected}"
    )


@ingest_app.command("indices")
def ingest_indices(
    provider_symbols: str = typer.Option(
        ",".join(DEFAULT_INDEX_PROVIDER_SYMBOLS),
        "--provider-symbols",
        help="Comma-separated EODHD index provider symbols to ingest.",
    ),
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market code to attach to index instruments."),
    currency: str = typer.Option("USD", "--currency", help="Currency to attach to index instruments."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
) -> None:
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    parsed_provider_symbols = [
        provider_symbol.strip()
        for provider_symbol in provider_symbols.split(",")
        if provider_symbol.strip()
    ]
    if not parsed_provider_symbols:
        raise typer.BadParameter("provider-symbols must contain at least one symbol")

    parsed_from, parsed_to = _parse_date_range(date_from, date_to)

    api_key = eodhd_api_key_from_env()
    engine = create_engine(database_url_from_env())
    client = EodhdClient(api_key=api_key)

    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        result = load_index_daily_prices(
            connection,
            client,
            provider_symbols=parsed_provider_symbols,
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
            currency=currency,
        )

    typer.echo(
        "index history ingest "
        f"run_id={result.run_id} status={result.status} "
        f"symbols={result.symbols_loaded}/{result.symbols_requested} "
        f"fetched={result.rows_fetched} inserted={result.rows_inserted} "
        f"rejected={result.rows_rejected}"
    )


@ingest_app.command("calendar")
def ingest_calendar(
    date_from: str = typer.Option(..., "--from", help="Start calendar date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End calendar date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market/exchange code to ingest."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
) -> None:
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    parsed_from, parsed_to = _parse_date_range(date_from, date_to)

    api_key = eodhd_api_key_from_env()
    engine = create_engine(database_url_from_env())
    client = EodhdClient(api_key=api_key)

    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        result = load_market_calendar(
            connection,
            client,
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
        )

    typer.echo(
        "calendar ingest "
        f"run_id={result.run_id} status={result.status} "
        f"fetched={result.rows_fetched} inserted={result.rows_inserted} "
        f"rejected={result.rows_rejected}"
    )


def _parse_date_range(date_from: str, date_to: str) -> tuple[date, date]:
    """Parse and validate an inclusive CLI date range."""
    try:
        parsed_from = date.fromisoformat(date_from)
        parsed_to = date.fromisoformat(date_to)
    except ValueError as exc:
        raise typer.BadParameter("from/to must be YYYY-MM-DD") from exc
    if parsed_to < parsed_from:
        raise typer.BadParameter("to must be greater than or equal to from")
    return parsed_from, parsed_to
