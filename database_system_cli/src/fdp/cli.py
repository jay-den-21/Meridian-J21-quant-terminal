from datetime import date

import typer
from sqlalchemy import create_engine

from fdp.config import database_url_from_env, eodhd_api_key_from_env
from fdp.research import DailyPriceReader
from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import (
    DEFAULT_INDEX_PROVIDER_SYMBOLS,
    SYMBOL_CHANGE_HISTORY_START,
    load_bulk_daily_prices,
    load_index_daily_prices,
    load_exchange_symbols,
    load_historical_daily_prices,
    load_market_calendar,
)
from fdp.sources.eodhd.retry import EodhdApiEvent
from fdp.quality.validation import validate_daily_prices
from fdp.storage.schema import ensure_runtime_schemas

app = typer.Typer(help="Financial data platform command line interface.")
ingest_app = typer.Typer(help="Ingest source data into the database.")
validate_app = typer.Typer(help="Validate stored market data quality.")
research_app = typer.Typer(help="Read stored database data for research code.")
app.add_typer(ingest_app, name="ingest")
app.add_typer(validate_app, name="validate")
app.add_typer(research_app, name="research")


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
    client = _eodhd_client(api_key)

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
    client = _eodhd_client(api_key)

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
    client = _eodhd_client(api_key)

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
    client = _eodhd_client(api_key)

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


@ingest_app.command("daily")
def ingest_daily(
    exchange: str = typer.Option(
        "US",
        "--exchange",
        help="EODHD bulk exchange code, for example US, NASDAQ, NYSE, AMEX, or BATS.",
    ),
    trade_date: str | None = typer.Option(
        None,
        "--date",
        help="Specific bulk EOD date in YYYY-MM-DD format; omitted means EODHD last trading day.",
    ),
    symbols: str | None = typer.Option(
        None,
        "--symbols",
        help="Optional comma-separated symbols; omitted means entire exchange bulk request.",
    ),
    asset_types: str = typer.Option(
        "stock,etf",
        "--asset-types",
        help="Comma-separated asset types to write: stock,etf.",
    ),
    market: str = typer.Option("US", "--market", help="Internal market code to match instruments."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
) -> None:
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    parsed_date = _parse_optional_date(trade_date, field_name="date")
    parsed_symbols = None
    if symbols is not None:
        parsed_symbols = [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]
        if not parsed_symbols:
            raise typer.BadParameter("symbols must contain at least one symbol when provided")
    parsed_asset_types = _parse_asset_types(asset_types, supported={"stock", "etf"})

    api_key = eodhd_api_key_from_env()
    engine = create_engine(database_url_from_env())
    client = _eodhd_client(api_key)

    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        result = load_bulk_daily_prices(
            connection,
            client,
            exchange=exchange,
            trade_date=parsed_date,
            symbols=parsed_symbols,
            market=market,
            asset_types=parsed_asset_types,
        )

    typer.echo(
        "daily bulk ingest "
        f"run_id={result.run_id} status={result.status} exchange={result.exchange} "
        f"date={result.trade_date or 'last-trading-day'} fetched={result.rows_fetched} "
        f"matched={result.rows_matched} inserted={result.rows_inserted} "
        f"rejected={result.rows_rejected}"
    )


@validate_app.command("daily-price")
def validate_daily_price(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    asset_types: str = typer.Option(
        "stock,etf,index",
        "--asset-types",
        help="Comma-separated asset types to validate: stock,etf,index.",
    ),
    market: str = typer.Option("US", "--market", help="Market code to validate."),
) -> None:
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    parsed_asset_types = _parse_asset_types(asset_types)

    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        result = validate_daily_prices(
            connection,
            date_from=parsed_from,
            date_to=parsed_to,
            asset_types=parsed_asset_types,
            market=market,
        )

    typer.echo(
        "daily-price validate "
        f"status=success date_from={result.date_from} date_to={result.date_to} "
        f"issues={result.issues_found}"
    )
    for summary in result.table_summaries:
        typer.echo(
            "  "
            f"check_run_id={summary.check_run_id} "
            f"table={summary.target_table} "
            f"asset_type={summary.asset_type} "
            f"issues={summary.issues_found}"
        )


@research_app.command("daily-prices")
def research_daily_prices(
    symbols: str = typer.Option(..., "--symbols", help="Comma-separated symbols to read."),
    date_from: str | None = typer.Option(
        None,
        "--from",
        help="Start trade date in YYYY-MM-DD format.",
    ),
    date_to: str | None = typer.Option(
        None,
        "--to",
        help="End trade date in YYYY-MM-DD format.",
    ),
    asset_type: str = typer.Option(
        "stock",
        "--asset-type",
        help="Asset type to read: stock, etf, or index.",
    ),
    market: str = typer.Option("US", "--market", help="Market code to read."),
    adjusted: bool = typer.Option(
        True,
        "--adjusted/--raw",
        help="Use adjusted_close or raw close as analysis_close.",
    ),
    limit: int = typer.Option(20, "--limit", help="Maximum rows to print; 0 prints all rows."),
) -> None:
    if limit < 0:
        raise typer.BadParameter("limit must be greater than or equal to 0")

    parsed_symbols = [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]
    if not parsed_symbols:
        raise typer.BadParameter("symbols must contain at least one symbol")
    parsed_from, parsed_to = _parse_optional_date_range(date_from, date_to)
    if parsed_from is None or parsed_to is None:
        raise typer.BadParameter("research CLI requires --from and --to")

    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        reader = DailyPriceReader(connection, market=market)
        try:
            rows = reader.get_daily_prices(
                symbols=parsed_symbols,
                asset_type=asset_type,
                date_from=parsed_from,
                date_to=parsed_to,
                adjusted=adjusted,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    typer.echo(
        "daily-prices research "
        f"rows={len(rows)} asset_type={asset_type.lower()} "
        f"date_from={parsed_from} date_to={parsed_to} adjusted={adjusted}"
    )
    _print_daily_price_rows(rows, limit=limit)


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


def _parse_optional_date_range(
    date_from: str | None,
    date_to: str | None,
) -> tuple[date | None, date | None]:
    """Parse an optional CLI date range without silently accepting partial ranges."""
    if date_from is None and date_to is None:
        return None, None
    if date_from is None or date_to is None:
        raise typer.BadParameter("from and to must be provided together")
    return _parse_date_range(date_from, date_to)


def _parse_asset_types(asset_types: str, *, supported: set[str] | None = None) -> list[str]:
    """Parse and validate a comma-separated asset type list."""
    parsed = [asset_type.strip().lower() for asset_type in asset_types.split(",") if asset_type.strip()]
    if not parsed:
        raise typer.BadParameter("asset-types must contain at least one asset type")
    supported_asset_types = supported or {"stock", "etf", "index"}
    unsupported = [asset_type for asset_type in parsed if asset_type not in supported_asset_types]
    if unsupported:
        expected = ",".join(sorted(supported_asset_types))
        raise typer.BadParameter(
            f"unsupported asset type(s): {', '.join(unsupported)}; expected {expected}"
        )
    return parsed


def _parse_optional_date(value: str | None, *, field_name: str) -> date | None:
    """Parse an optional CLI date value."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"{field_name} must be YYYY-MM-DD") from exc


def _print_daily_price_rows(rows: list[dict[str, object]], *, limit: int) -> None:
    """Print a compact CLI preview of research rows."""
    if not rows:
        return

    columns = [
        "trade_date",
        "symbol",
        "provider_symbol",
        "price_symbol",
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "analysis_close",
        "volume",
    ]
    rows_to_print = rows if limit == 0 else rows[:limit]
    typer.echo("\t".join(columns))
    for row in rows_to_print:
        typer.echo("\t".join(_format_cli_value(row.get(column)) for column in columns))
    if limit > 0 and len(rows) > limit:
        typer.echo(f"... output truncated at {limit} rows; use --limit 0 to print all rows")


def _format_cli_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _eodhd_client(api_key: str) -> EodhdClient:
    """Build the CLI EODHD client with visible progress and retry messages."""
    return EodhdClient(api_key=api_key, progress_callback=_echo_eodhd_event)


def _echo_eodhd_event(event: EodhdApiEvent) -> None:
    """Print EODHD request progress without exposing API keys."""
    if event.kind == "request":
        typer.echo(
            "EODHD request "
            f"endpoint={event.endpoint} attempt={event.attempt}/{event.max_attempts}"
        )
        return
    if event.kind == "retry":
        typer.echo(
            "EODHD retrying "
            f"endpoint={event.endpoint} attempt={event.attempt}/{event.max_attempts} "
            f"wait={event.retry_delay_seconds}s error={event.error_message}. "
            f"请耐心等待 {event.retry_delay_seconds} 秒后重试。"
        )
        return
    if event.kind == "success":
        typer.echo(
            "EODHD success "
            f"endpoint={event.endpoint} status={event.status_code} "
            f"rows={event.rows_returned} duration_ms={event.duration_ms}"
        )
        return
    if event.kind == "failed":
        typer.echo(
            "EODHD failed "
            f"endpoint={event.endpoint} status={event.status_code} "
            f"error={event.error_message}"
        )
