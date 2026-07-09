from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from datetime import date
from typing import Any

import typer
from sqlalchemy import create_engine, func, select

from fdp.bulk_unmatched import (
    classify_bulk_unmatched_observations,
    list_bulk_unmatched_observations,
    route_bulk_unmatched_observations,
    summarize_bulk_unmatched_observations,
)
from fdp.config import (
    EODHD_OFFICIAL_MAX_REQUESTS_PER_MINUTE,
    database_url_from_env,
    eodhd_api_key_from_env,
    eodhd_runtime_config_from_env,
)
from fdp.repair import (
    confirm_repair_plan,
    create_missing_daily_price_repair_plans,
    execute_repair_plan,
    get_repair_plan,
    list_repair_plans,
)
from fdp.quarantine import (
    confirm_quarantine_plan,
    create_daily_price_quarantine_plans,
    execute_quarantine_plan,
    get_quarantine_plan,
    list_quarantine_plans,
    preview_quarantine_plan_source_rows,
)
from fdp.research import DailyPriceReader
from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import (
    BulkDailyPriceLoadResult,
    DEFAULT_INDEX_PROVIDER_SYMBOLS,
    SYMBOL_CHANGE_HISTORY_START,
    load_bulk_daily_prices,
    load_delisted_instruments,
    load_index_daily_prices,
    load_exchange_symbols,
    load_historical_daily_prices,
    load_market_calendar,
)
from fdp.sources.eodhd.retry import EodhdApiEvent, EodhdRequestRateLimiter
from fdp.quality.validation import validate_daily_prices
from fdp.storage.schema import ensure_runtime_schemas
from fdp.storage.tables import instrument, market_calendar

app = typer.Typer(help="Financial data platform command line interface.")
ingest_app = typer.Typer(help="Ingest source data into the database.")
validate_app = typer.Typer(help="Validate stored market data quality.")
repair_app = typer.Typer(help="Create and manage human-confirmed repair plans.")
quarantine_app = typer.Typer(help="Create and manage human-confirmed quarantine plans.")
research_app = typer.Typer(help="Read stored database data for research code.")
bulk_unmatched_app = typer.Typer(help="Inspect and classify Bulk EOD unmatched rows.")
app.add_typer(ingest_app, name="ingest")
app.add_typer(validate_app, name="validate")
app.add_typer(repair_app, name="repair")
app.add_typer(quarantine_app, name="quarantine")
app.add_typer(research_app, name="research")
research_app.add_typer(bulk_unmatched_app, name="bulk-unmatched")

EODHD_BULK_FULL_EXCHANGE_API_CALL_COST = 100
DAILY_PRICE_ASSET_TYPES = {"stock", "etf", "index"}
QUARANTINE_DAILY_PRICE_ISSUE_TYPES = {
    "duplicate_key",
    "invalid_ohlcv",
    "price_on_non_trading_day",
}


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
    instrument_status: str = typer.Option(
        "active",
        "--instrument-status",
        help="Instrument status to match: active, inactive, or all.",
    ),
    include_inactive: bool | None = typer.Option(
        None,
        "--include-inactive/--active-only",
        help="Deprecated compatibility flag. Use --instrument-status all/active instead.",
    ),
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
    resolved_instrument_status = _resolve_history_instrument_status(
        instrument_status=instrument_status,
        include_inactive=include_inactive,
    )

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
            instrument_status=resolved_instrument_status,
        )

    typer.echo(
        "history ingest "
        f"run_id={result.run_id} status={result.status} "
        f"symbols={result.symbols_loaded}/{result.symbols_requested} "
        f"instrument_status={resolved_instrument_status} "
        f"fetched={result.rows_fetched} inserted={result.rows_inserted} "
        f"rejected={result.rows_rejected}"
    )


@ingest_app.command("delisted-instruments")
def ingest_delisted_instruments(
    market: str = typer.Option("US", "--market", help="Market code to ingest."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
) -> None:
    """Load inactive/delisted stock and ETF instruments from EODHD."""
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    api_key = eodhd_api_key_from_env()
    engine = create_engine(database_url_from_env())
    client = _eodhd_client(api_key)

    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        result = load_delisted_instruments(connection, client, market=market)

    typer.echo(
        "delisted-instruments ingest "
        f"run_id={result.run_id} status={result.status} "
        f"fetched={result.rows_fetched} accepted={result.rows_accepted} "
        f"rejected={result.rows_rejected} lifecycle_events={result.lifecycle_events_inserted}"
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


@ingest_app.command("daily-range")
def ingest_daily_range(
    date_from: str = typer.Option(..., "--from", help="Start calendar date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End calendar date in YYYY-MM-DD format."),
    exchange: str = typer.Option("US", "--exchange", help="EODHD bulk exchange code."),
    asset_types: str = typer.Option(
        "stock,etf",
        "--asset-types",
        help="Comma-separated asset types to write: stock,etf.",
    ),
    market: str = typer.Option("US", "--market", help="Internal market code to match instruments."),
    bytes_per_row: int = typer.Option(
        600,
        "--bytes-per-row",
        help="Conservative storage estimate per price row.",
    ),
    max_estimated_gb: float = typer.Option(
        30.0,
        "--max-estimated-gb",
        help="Refuse execution if estimated storage exceeds this many GB.",
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--execute",
        help="Estimate by default; use --execute --yes to ingest.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Required with --execute to confirm a multi-day bulk ingest.",
    ),
    parallel: bool | None = typer.Option(
        None,
        "--parallel/--sequential",
        help="Enable bounded parallel per-day ingestion; omitted uses config/default.yaml.",
    ),
    workers: int | None = typer.Option(
        None,
        "--workers",
        help="Parallel worker count; omitted uses EODHD_DAILY_RANGE_MAX_WORKERS/config.",
    ),
    max_requests_per_minute: int | None = typer.Option(
        None,
        "--max-requests-per-minute",
        help="Throttle EODHD HTTP requests at or below the official per-minute ceiling.",
    ),
    max_api_calls: int | None = typer.Option(
        None,
        "--max-api-calls",
        help="Refuse execution when estimated EODHD API-call cost exceeds this budget.",
    ),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
) -> None:
    """Run guarded multi-day EODHD bulk daily ingestion over trading calendar days."""
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")
    if bytes_per_row <= 0:
        raise typer.BadParameter("bytes-per-row must be positive")
    if max_estimated_gb <= 0:
        raise typer.BadParameter("max-estimated-gb must be positive")
    if workers is not None and workers <= 0:
        raise typer.BadParameter("workers must be positive")
    if max_requests_per_minute is not None and max_requests_per_minute <= 0:
        raise typer.BadParameter("max-requests-per-minute must be positive")
    if (
        max_requests_per_minute is not None
        and max_requests_per_minute > EODHD_OFFICIAL_MAX_REQUESTS_PER_MINUTE
    ):
        raise typer.BadParameter(
            "max-requests-per-minute must be less than or equal to "
            f"the official EODHD limit {EODHD_OFFICIAL_MAX_REQUESTS_PER_MINUTE}"
        )
    if max_api_calls is not None and max_api_calls <= 0:
        raise typer.BadParameter("max-api-calls must be positive")

    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    parsed_asset_types = _parse_asset_types(asset_types, supported={"stock", "etf"})
    runtime_config = eodhd_runtime_config_from_env()
    resolved_parallel = runtime_config.daily_range_parallel_enabled if parallel is None else parallel
    resolved_workers = workers or runtime_config.daily_range_max_workers
    if not resolved_parallel:
        resolved_workers = 1
    resolved_max_requests_per_minute = (
        max_requests_per_minute or runtime_config.max_requests_per_minute
    )
    resolved_max_api_calls = max_api_calls or runtime_config.daily_call_budget

    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        _ensure_calendar_coverage(
            connection,
            date_from=parsed_from,
            date_to=parsed_to,
        )
        trade_dates = _load_trading_dates(
            connection,
            date_from=parsed_from,
            date_to=parsed_to,
        )
        active_instruments = _count_active_instruments(
            connection,
            market=market,
            asset_types=parsed_asset_types,
        )
        estimated_rows = len(trade_dates) * active_instruments
        estimated_gb = _estimated_storage_gb(estimated_rows, bytes_per_row=bytes_per_row)
        estimated_api_calls = _estimated_bulk_daily_api_calls(
            trading_days=len(trade_dates),
            symbols=None,
        )

    typer.echo(
        "daily-range estimate "
        f"date_from={parsed_from} date_to={parsed_to} trading_days={len(trade_dates)} "
        f"active_instruments={active_instruments} estimated_rows={estimated_rows} "
        f"estimated_gb={estimated_gb:.2f} max_estimated_gb={max_estimated_gb:.2f} "
        f"estimated_api_calls={estimated_api_calls} max_api_calls={resolved_max_api_calls} "
        f"parallel={str(resolved_parallel).lower()} workers={resolved_workers} "
        f"max_requests_per_minute={resolved_max_requests_per_minute}"
    )
    if not trade_dates:
        raise typer.BadParameter("no trading days found in market_calendar for this range")
    if estimated_gb > max_estimated_gb:
        raise typer.BadParameter(
            f"estimated storage {estimated_gb:.2f}GB exceeds max-estimated-gb {max_estimated_gb:.2f}GB"
        )
    if estimated_api_calls > resolved_max_api_calls:
        raise typer.BadParameter(
            f"estimated EODHD API calls {estimated_api_calls} exceed max-api-calls "
            f"{resolved_max_api_calls}; split the date range or raise the budget explicitly"
        )
    if dry_run:
        typer.echo("dry-run only; rerun with --execute --yes to ingest this range")
        return
    if not yes:
        raise typer.BadParameter("--execute requires --yes")

    api_key = eodhd_api_key_from_env()
    client = _eodhd_client(
        api_key,
        max_retries=runtime_config.max_retries,
        retry_delay_seconds=runtime_config.retry_delay_seconds,
        max_requests_per_minute=resolved_max_requests_per_minute,
    )
    totals = _run_daily_range_ingest(
        engine,
        client,
        trade_dates=trade_dates,
        exchange=exchange,
        market=market,
        asset_types=parsed_asset_types,
        parallel=resolved_parallel,
        workers=resolved_workers,
    )

    typer.echo(
        "daily-range ingest "
        f"status=completed trading_days={len(trade_dates)} "
        f"rows_fetched={totals['rows_fetched']} rows_matched={totals['rows_matched']} "
        f"rows_inserted={totals['rows_inserted']} rows_rejected={totals['rows_rejected']} "
        f"http_requests={totals['api_calls']} api_call_cost_estimate={estimated_api_calls} "
        f"success_days={totals['success']} "
        f"partial_failed_days={totals['partial_failed']} failed_days={totals['failed']}"
    )


@ingest_app.command("bulk-unmatched-route")
def ingest_bulk_unmatched_route(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    asset_types: str = typer.Option(
        "stock,etf,index",
        "--asset-types",
        help="Comma-separated asset types to route: stock,etf,index.",
    ),
    market: str = typer.Option("US", "--market", help="Market code to route."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--execute",
        help="Preview by default; use --execute --yes to write price tables.",
    ),
    yes: bool = typer.Option(False, "--yes", help="Required with --execute."),
    limit: int | None = typer.Option(None, "--limit", help="Optional max rows to route."),
) -> None:
    """Route classified Bulk EOD unmatched observations into split daily price tables."""
    if limit is not None and limit <= 0:
        raise typer.BadParameter("limit must be positive")
    if not dry_run and not yes:
        raise typer.BadParameter("bulk-unmatched-route execution requires --yes")
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    parsed_asset_types = _parse_asset_types(asset_types, supported=DAILY_PRICE_ASSET_TYPES)

    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        try:
            result = route_bulk_unmatched_observations(
                connection,
                date_from=parsed_from,
                date_to=parsed_to,
                market=market,
                asset_types=parsed_asset_types,
                dry_run=dry_run,
                limit=limit,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    mode = "dry_run" if result.dry_run else "executed"
    typer.echo(
        "bulk-unmatched-route "
        f"mode={mode} date_from={parsed_from} date_to={parsed_to} "
        f"routeable={result.routeable} rows_inserted={result.rows_inserted} "
        f"rows_rejected={result.rows_rejected} routed={result.routed}"
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


@repair_app.command("plan-daily-price")
def repair_plan_daily_price(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    asset_types: str = typer.Option(
        "stock,etf,index",
        "--asset-types",
        help="Comma-separated asset types to plan: stock,etf,index.",
    ),
    market: str = typer.Option("US", "--market", help="Market code to repair."),
) -> None:
    """Create pending backfill plans from open missing daily-price issues."""
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    parsed_asset_types = _parse_asset_types(asset_types, supported=DAILY_PRICE_ASSET_TYPES)

    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        try:
            result = create_missing_daily_price_repair_plans(
                connection,
                date_from=parsed_from,
                date_to=parsed_to,
                asset_types=parsed_asset_types,
                market=market,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    typer.echo(
        "repair plan-daily-price "
        f"status=success date_from={result.date_from} date_to={result.date_to} "
        f"asset_types={','.join(result.asset_types)} eligible_issues={result.eligible_issues} "
        f"existing_plans={result.existing_plans} plans_created={result.plans_created}"
    )
    _print_repair_plan_records(result.created_plans, limit=20)


@repair_app.command("list")
def repair_list(
    status: str | None = typer.Option(
        None,
        "--status",
        help="Optional comma-separated statuses, e.g. pending_confirmation,confirmed.",
    ),
    limit: int = typer.Option(50, "--limit", help="Maximum repair plans to print."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of tabular text."),
) -> None:
    """List repair plans for operator review."""
    if limit <= 0:
        raise typer.BadParameter("limit must be positive")
    parsed_statuses = _parse_statuses(status)

    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        try:
            rows = list_repair_plans(connection, statuses=parsed_statuses, limit=limit)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if as_json:
        typer.echo(json.dumps([row.to_dict() for row in rows], default=_json_cli_default, indent=2))
        return

    typer.echo(f"repair list rows={len(rows)}")
    _print_repair_plan_records(rows, limit=limit)


@repair_app.command("confirm")
def repair_confirm(
    plan_id: int = typer.Option(..., "--plan-id", help="Repair plan id to confirm."),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Confirm the displayed repair plan. Without --yes this is preview-only.",
    ),
) -> None:
    """Confirm one pending repair plan after showing its impact."""
    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        try:
            current = get_repair_plan(connection, repair_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

        typer.echo("repair confirm preview")
        _print_repair_plan_records([current], limit=1)
        if not yes:
            typer.echo("not confirmed; rerun with --yes to mark this plan confirmed")
            return

        try:
            confirmed = confirm_repair_plan(connection, repair_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    typer.echo(
        "repair confirm "
        f"status=success repair_plan_id={confirmed.repair_plan_id} "
        f"new_status={confirmed.status}"
    )


@repair_app.command("run")
def repair_run(
    plan_id: int = typer.Option(..., "--plan-id", help="Confirmed repair plan id to execute."),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Execute the displayed confirmed repair plan. Without --yes this is preview-only.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print JSON execution summary."),
) -> None:
    """Execute one confirmed repair plan and resolve its linked issue if fixed."""
    engine = create_engine(database_url_from_env())

    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        try:
            current = get_repair_plan(connection, repair_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

        typer.echo("repair run preview")
        _print_repair_plan_records([current], limit=1)
        if not yes:
            typer.echo("not executed; rerun with --yes to execute this confirmed plan")
            return

        api_key = eodhd_api_key_from_env()
        client = _eodhd_client(api_key)
        try:
            result = execute_repair_plan(connection, client, repair_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if as_json:
        typer.echo(json.dumps(result.to_dict(), default=_json_cli_default, indent=2))
    else:
        typer.echo(
            "repair run "
            f"status={result.status} repair_plan_id={result.repair_plan_id} "
            f"issue_id={result.issue_id} asset_type={result.asset_type} "
            f"target_table={result.target_table} ingest_run_id={result.ingest_run_id} "
            f"rows_fetched={result.rows_fetched} rows_inserted={result.rows_inserted} "
            f"rows_rejected={result.rows_rejected} issue_resolved={result.issue_resolved}"
        )
        typer.echo(f"result_message={result.result_message}")

    if not result.issue_resolved:
        raise typer.Exit(code=1)


@quarantine_app.command("plan-daily-price")
def quarantine_plan_daily_price(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    issue_types: str = typer.Option(
        "duplicate_key,invalid_ohlcv,price_on_non_trading_day",
        "--issue-types",
        help=(
            "Comma-separated issue types to plan: "
            "duplicate_key,invalid_ohlcv,price_on_non_trading_day."
        ),
    ),
    asset_types: str = typer.Option(
        "stock,etf,index",
        "--asset-types",
        help="Comma-separated asset types to plan: stock,etf,index.",
    ),
    market: str = typer.Option("US", "--market", help="Market code to quarantine."),
) -> None:
    """Create pending quarantine plans from open bad daily-price issues."""
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    parsed_issue_types = _parse_issue_types(issue_types)
    parsed_asset_types = _parse_asset_types(asset_types, supported=DAILY_PRICE_ASSET_TYPES)

    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        try:
            result = create_daily_price_quarantine_plans(
                connection,
                date_from=parsed_from,
                date_to=parsed_to,
                issue_types=parsed_issue_types,
                asset_types=parsed_asset_types,
                market=market,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    typer.echo(
        "quarantine plan-daily-price "
        f"status=success date_from={result.date_from} date_to={result.date_to} "
        f"issue_types={','.join(result.issue_types)} eligible_issues={result.eligible_issues} "
        f"existing_plans={result.existing_plans} plans_created={result.plans_created}"
    )
    _print_quarantine_plan_records(result.created_plans, limit=20)


@quarantine_app.command("list")
def quarantine_list(
    status: str | None = typer.Option(
        None,
        "--status",
        help="Optional comma-separated statuses, e.g. pending_confirmation,confirmed.",
    ),
    limit: int = typer.Option(50, "--limit", help="Maximum quarantine plans to print."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of tabular text."),
) -> None:
    """List quarantine plans for operator review."""
    if limit <= 0:
        raise typer.BadParameter("limit must be positive")
    parsed_statuses = _parse_statuses(status)

    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        try:
            rows = list_quarantine_plans(connection, statuses=parsed_statuses, limit=limit)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if as_json:
        typer.echo(json.dumps([row.to_dict() for row in rows], default=_json_cli_default, indent=2))
        return

    typer.echo(f"quarantine list rows={len(rows)}")
    _print_quarantine_plan_records(rows, limit=limit)


@quarantine_app.command("confirm")
def quarantine_confirm(
    plan_id: int = typer.Option(..., "--plan-id", help="Quarantine plan id to confirm."),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Confirm the displayed quarantine plan. Without --yes this is preview-only.",
    ),
) -> None:
    """Confirm one pending quarantine plan after showing its impact."""
    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        try:
            current = get_quarantine_plan(connection, quarantine_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

        typer.echo("quarantine confirm preview")
        _print_quarantine_plan_records([current], limit=1)
        try:
            source_rows = preview_quarantine_plan_source_rows(connection, quarantine_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        _print_quarantine_source_rows(source_rows, limit=10)
        if not yes:
            typer.echo("not confirmed; rerun with --yes to mark this plan confirmed")
            return

        try:
            confirmed = confirm_quarantine_plan(connection, quarantine_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    typer.echo(
        "quarantine confirm "
        f"status=success quarantine_plan_id={confirmed.quarantine_plan_id} "
        f"new_status={confirmed.status}"
    )


@quarantine_app.command("run")
def quarantine_run(
    plan_id: int = typer.Option(..., "--plan-id", help="Confirmed quarantine plan id to execute."),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Execute the displayed confirmed quarantine plan. Without --yes this is preview-only.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print JSON execution summary."),
) -> None:
    """Execute one confirmed quarantine plan and resolve its linked issue if fixed."""
    engine = create_engine(database_url_from_env())

    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        try:
            current = get_quarantine_plan(connection, quarantine_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

        typer.echo("quarantine run preview")
        _print_quarantine_plan_records([current], limit=1)
        try:
            source_rows = preview_quarantine_plan_source_rows(connection, quarantine_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        _print_quarantine_source_rows(source_rows, limit=10)
        if not yes:
            typer.echo("not executed; rerun with --yes to execute this confirmed plan")
            return

        try:
            result = execute_quarantine_plan(connection, quarantine_plan_id=plan_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if as_json:
        typer.echo(json.dumps(result.to_dict(), default=_json_cli_default, indent=2))
    else:
        typer.echo(
            "quarantine run "
            f"status={result.status} quarantine_plan_id={result.quarantine_plan_id} "
            f"issue_id={result.issue_id} action_type={result.action_type} "
            f"target_table={result.target_table} rows_quarantined={result.rows_quarantined} "
            f"rows_deleted={result.rows_deleted} issue_resolved={result.issue_resolved}"
        )
        typer.echo(f"result_message={result.result_message}")

    if not result.issue_resolved:
        raise typer.Exit(code=1)


@bulk_unmatched_app.command("summary")
def research_bulk_unmatched_summary(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market code to inspect."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of text."),
) -> None:
    """Summarize Bulk EOD unmatched staging rows by status and asset type."""
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        rows = summarize_bulk_unmatched_observations(
            connection,
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
        )

    if as_json:
        typer.echo(json.dumps([row.to_dict() for row in rows], default=_json_cli_default, indent=2))
        return
    typer.echo(f"bulk-unmatched summary rows={len(rows)}")
    for row in rows:
        typer.echo(
            "  "
            f"status={row.classification_status} "
            f"asset_type={row.classified_asset_type or '-'} count={row.row_count}"
        )


@bulk_unmatched_app.command("list")
def research_bulk_unmatched_list(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    status: str | None = typer.Option(None, "--status", help="Optional classification status."),
    market: str = typer.Option("US", "--market", help="Market code to inspect."),
    limit: int = typer.Option(50, "--limit", help="Maximum rows to print."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of text."),
) -> None:
    """List bounded Bulk EOD unmatched staging rows for operator review."""
    if limit <= 0:
        raise typer.BadParameter("limit must be positive")
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        rows = list_bulk_unmatched_observations(
            connection,
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
            status=status,
            limit=limit,
        )

    if as_json:
        typer.echo(json.dumps(rows, default=_json_cli_default, indent=2))
        return
    typer.echo(f"bulk-unmatched list rows={len(rows)}")
    _print_bulk_unmatched_rows(rows, limit=limit)


@bulk_unmatched_app.command("classify")
def research_bulk_unmatched_classify(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market code to classify."),
    limit: int | None = typer.Option(None, "--limit", help="Optional max rows to classify."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of text."),
) -> None:
    """Classify unresolved unmatched rows using strict provider-symbol matches."""
    if limit is not None and limit <= 0:
        raise typer.BadParameter("limit must be positive")
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    engine = create_engine(database_url_from_env())
    with engine.begin() as connection:
        ensure_runtime_schemas(connection)
        result = classify_bulk_unmatched_observations(
            connection,
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
            limit=limit,
        )

    if as_json:
        typer.echo(json.dumps(result.to_dict(), default=_json_cli_default, indent=2))
        return
    typer.echo(
        "bulk-unmatched classify "
        f"scanned={result.scanned} matched={result.matched} "
        f"needs_instrument={result.needs_instrument} "
        f"non_price_asset={result.non_price_asset} unknown={result.unknown}"
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


def _load_trading_dates(
    connection: Any,
    *,
    date_from: date,
    date_to: date,
) -> list[date]:
    """Read trading calendar dates already loaded into `us_share.market_calendar`."""
    rows = connection.execute(
        select(market_calendar.c.calendar_date)
        .where(
            market_calendar.c.calendar_date >= date_from,
            market_calendar.c.calendar_date <= date_to,
            market_calendar.c.is_trading_day.is_(True),
        )
        .order_by(market_calendar.c.calendar_date)
    ).scalars()
    return list(rows)


def _ensure_calendar_coverage(
    connection: Any,
    *,
    date_from: date,
    date_to: date,
) -> None:
    """Require one market-calendar row per calendar day before large-run estimates."""
    expected_days = (date_to - date_from).days + 1
    loaded_days = int(
        connection.execute(
            select(func.count())
            .select_from(market_calendar)
            .where(
                market_calendar.c.calendar_date >= date_from,
                market_calendar.c.calendar_date <= date_to,
            )
        ).scalar_one()
    )
    if loaded_days < expected_days:
        raise typer.BadParameter(
            "market_calendar coverage is incomplete for this range: "
            f"loaded_days={loaded_days} expected_days={expected_days}; "
            "run calendar ingest before estimating or executing a large backfill"
        )


def _count_active_instruments(
    connection: Any,
    *,
    market: str,
    asset_types: list[str],
) -> int:
    """Count active instruments in the requested market/asset scope for planning."""
    return int(
        connection.execute(
            select(func.count())
            .select_from(instrument)
            .where(
                instrument.c.provider == "EODHD",
                instrument.c.market == market,
                instrument.c.asset_type.in_(asset_types),
                instrument.c.is_active.is_(True),
            )
        ).scalar_one()
    )


def _estimated_storage_gb(rows: int, *, bytes_per_row: int) -> float:
    return rows * bytes_per_row / (1024 ** 3)


def _estimated_bulk_daily_api_calls(*, trading_days: int, symbols: list[str] | None) -> int:
    """Estimate EODHD Bulk EOD API-call currency for a daily-range request."""
    per_request_cost = EODHD_BULK_FULL_EXCHANGE_API_CALL_COST + (len(symbols) if symbols else 0)
    return trading_days * per_request_cost


def _run_daily_range_ingest(
    engine: Any,
    client: EodhdClient,
    *,
    trade_dates: list[date],
    exchange: str,
    market: str,
    asset_types: list[str],
    parallel: bool,
    workers: int,
) -> dict[str, int]:
    """Run daily-range ingest sequentially or with bounded per-day parallelism."""
    totals = _empty_daily_range_totals()
    if parallel and workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _run_one_daily_range_day,
                    engine,
                    client,
                    trade_date=trade_date,
                    exchange=exchange,
                    market=market,
                    asset_types=asset_types,
                ): trade_date
                for trade_date in trade_dates
            }
            for future in as_completed(futures):
                trade_date = futures[future]
                try:
                    _record_daily_range_result(totals, future.result())
                except Exception as exc:
                    _record_daily_range_failure(totals, trade_date=trade_date, error=exc)
        return totals

    for trade_date in trade_dates:
        try:
            result = _run_one_daily_range_day(
                engine,
                client,
                trade_date=trade_date,
                exchange=exchange,
                market=market,
                asset_types=asset_types,
            )
            _record_daily_range_result(totals, result)
        except Exception as exc:
            _record_daily_range_failure(totals, trade_date=trade_date, error=exc)
    return totals


def _run_one_daily_range_day(
    engine: Any,
    client: EodhdClient,
    *,
    trade_date: date,
    exchange: str,
    market: str,
    asset_types: list[str],
) -> BulkDailyPriceLoadResult:
    """Load one daily-range trading date inside its own transaction."""
    with engine.begin() as connection:
        return load_bulk_daily_prices(
            connection,
            client,
            exchange=exchange,
            trade_date=trade_date,
            market=market,
            asset_types=asset_types,
        )


def _empty_daily_range_totals() -> dict[str, int]:
    return {
        "rows_fetched": 0,
        "rows_matched": 0,
        "rows_inserted": 0,
        "rows_rejected": 0,
        "api_calls": 0,
        "success": 0,
        "partial_failed": 0,
        "failed": 0,
    }


def _record_daily_range_result(totals: dict[str, int], result: BulkDailyPriceLoadResult) -> None:
    totals["rows_fetched"] += result.rows_fetched
    totals["rows_matched"] += result.rows_matched
    totals["rows_inserted"] += result.rows_inserted
    totals["rows_rejected"] += result.rows_rejected
    totals["api_calls"] += result.api_calls
    totals[result.status] = totals.get(result.status, 0) + 1
    typer.echo(
        "daily-range day "
        f"date={result.trade_date} run_id={result.run_id} status={result.status} "
        f"fetched={result.rows_fetched} matched={result.rows_matched} "
        f"inserted={result.rows_inserted} rejected={result.rows_rejected}"
    )


def _record_daily_range_failure(
    totals: dict[str, int],
    *,
    trade_date: date,
    error: Exception,
) -> None:
    totals["failed"] += 1
    typer.echo(f"daily-range day date={trade_date} status=failed error={error}")


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


def _resolve_history_instrument_status(
    *,
    instrument_status: str,
    include_inactive: bool | None,
) -> str:
    """Resolve new history status semantics and the legacy include-inactive flag."""
    normalized = instrument_status.strip().lower()
    if normalized not in {"active", "inactive", "all"}:
        raise typer.BadParameter("instrument-status must be active, inactive, or all")
    if include_inactive is not None:
        if normalized != "active":
            raise typer.BadParameter(
                "do not combine --include-inactive/--active-only with --instrument-status"
            )
        return "all" if include_inactive else "active"
    return normalized


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


def _print_bulk_unmatched_rows(rows: list[dict[str, object]], *, limit: int) -> None:
    """Print a compact preview of Bulk EOD unmatched staging rows."""
    for row in rows[:limit]:
        typer.echo(
            "  "
            f"observation_id={row['observation_id']} "
            f"date={row['trade_date']} "
            f"provider_symbol={row['provider_symbol']} "
            f"status={row['classification_status']} "
            f"asset_type={row['classified_asset_type'] or '-'} "
            f"eodhd_type={row['eodhd_type'] or '-'} "
            f"matched_instrument_id={row['matched_instrument_id'] or '-'}"
        )
    if len(rows) > limit:
        typer.echo(f"  ... {len(rows) - limit} more row(s)")


def _format_cli_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _parse_statuses(status: str | None) -> list[str] | None:
    """Parse an optional comma-separated status filter."""
    if status is None:
        return None
    statuses = [item.strip() for item in status.split(",") if item.strip()]
    if not statuses:
        raise typer.BadParameter("status must contain at least one status when provided")
    return statuses


def _parse_issue_types(issue_types: str) -> list[str]:
    """Parse and validate quarantine issue types."""
    parsed = [issue_type.strip() for issue_type in issue_types.split(",") if issue_type.strip()]
    if not parsed:
        raise typer.BadParameter("issue-types must contain at least one issue type")
    unsupported = [
        issue_type for issue_type in parsed if issue_type not in QUARANTINE_DAILY_PRICE_ISSUE_TYPES
    ]
    if unsupported:
        expected = ",".join(sorted(QUARANTINE_DAILY_PRICE_ISSUE_TYPES))
        raise typer.BadParameter(
            f"unsupported issue type(s): {', '.join(unsupported)}; expected {expected}"
        )
    return parsed


def _json_cli_default(value: object) -> str:
    """JSON serializer for CLI preview values."""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _print_repair_plan_records(rows: list[object], *, limit: int) -> None:
    """Print a compact CLI preview of repair plans."""
    if not rows:
        return

    columns = [
        "repair_plan_id",
        "issue_id",
        "status",
        "repair_type",
        "symbol",
        "provider_symbol",
        "date_from",
        "date_to",
        "target_table",
    ]
    rows_to_print = rows if limit == 0 else rows[:limit]
    typer.echo("\t".join(columns))
    for row in rows_to_print:
        values = row.to_dict()
        typer.echo("\t".join(_format_cli_value(values.get(column)) for column in columns))
    if limit > 0 and len(rows) > limit:
        typer.echo(f"... output truncated at {limit} rows; use --limit 0 to print all rows")


def _print_quarantine_plan_records(rows: list[object], *, limit: int) -> None:
    """Print a compact CLI preview of quarantine plans."""
    if not rows:
        return

    columns = [
        "quarantine_plan_id",
        "issue_id",
        "status",
        "issue_type",
        "action_type",
        "symbol",
        "provider_symbol",
        "date_from",
        "date_to",
        "target_table",
        "row_count",
    ]
    rows_to_print = rows if limit == 0 else rows[:limit]
    typer.echo("\t".join(columns))
    for row in rows_to_print:
        values = row.to_dict()
        typer.echo("\t".join(_format_cli_value(values.get(column)) for column in columns))
    if limit > 0 and len(rows) > limit:
        typer.echo(f"... output truncated at {limit} rows; use --limit 0 to print all rows")


def _print_quarantine_source_rows(rows: list[dict[str, object]], *, limit: int) -> None:
    """Print source daily-price rows that currently match a quarantine plan."""
    typer.echo(f"quarantine source-row preview rows={len(rows)}")
    if not rows:
        return

    columns = [
        "source_primary_key",
        "instrument_id",
        "symbol",
        "provider_symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
    ]
    rows_to_print = rows if limit == 0 else rows[:limit]
    typer.echo("\t".join(columns))
    for row in rows_to_print:
        typer.echo("\t".join(_format_cli_value(row.get(column)) for column in columns))
    if limit > 0 and len(rows) > limit:
        typer.echo(f"... source rows truncated at {limit} rows")


def _eodhd_client(
    api_key: str,
    *,
    max_retries: int | None = None,
    retry_delay_seconds: int | None = None,
    max_requests_per_minute: int | None = None,
) -> EodhdClient:
    """Build the CLI EODHD client with visible progress and retry messages."""
    runtime_config = eodhd_runtime_config_from_env()
    resolved_max_requests_per_minute = max_requests_per_minute or runtime_config.max_requests_per_minute
    rate_limiter = EodhdRequestRateLimiter(resolved_max_requests_per_minute)
    return EodhdClient(
        api_key=api_key,
        max_retries=max_retries or runtime_config.max_retries,
        retry_delay_seconds=retry_delay_seconds or runtime_config.retry_delay_seconds,
        rate_limiter=rate_limiter,
        progress_callback=_echo_eodhd_event,
    )


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
            f"status={event.status_code} error={event.error_message}. "
            f"请稍等1分钟，马上重试～ (≧∇≦) wait={event.retry_delay_seconds}s"
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
