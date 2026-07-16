import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import typer
from sqlalchemy import create_engine
from typer.main import get_command

from fdp.assets import (
    CANONICAL_ASSET_TYPES,
    HISTORICAL_EOD_ASSET_TYPES,
    US_BULK_EOD_ASSET_TYPES,
)
from fdp.get_data import (
    ActiveInstrumentsJob,
    BulkDailyJob,
    BulkUnmatchedReconcileJob,
    DailyRangeJob,
    DelistedInstrumentsJob,
    EtfDailyJob,
    FundDailyJob,
    HistoricalDailyJob,
    IdentifierMappingJob,
    IndexDailyJob,
    MarketCalendarJob,
    StockDailyJob,
)
from fdp.get_data.contracts import JobResult, ProgressEvent
from fdp.get_data.reference import (
    DEFAULT_MAX_API_CALLS as ID_MAPPING_DEFAULT_MAX_API_CALLS,
)
from fdp.get_data.reference import DEFAULT_PAGE_LIMIT as ID_MAPPING_DEFAULT_PAGE_LIMIT
from fdp.get_data.reporting import format_eodhd_event
from fdp.migrate import (
    copy_fund_daily_prices,
    finalize_fund_daily_prices,
    plan_daily_price_asset_type_reconcile,
    plan_fund_daily_prices,
    reconcile_daily_price_asset_types,
    verify_fund_daily_prices,
)
from fdp.config import (
    EODHD_OFFICIAL_MAX_REQUESTS_PER_MINUTE,
    database_url_from_env,
    eodhd_api_key_from_env,
    eodhd_runtime_config_from_env,
)
from fdp.docs_staleness import validate_docs_staleness
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
from fdp.research import (
    DailyPriceReader,
    required_technical_validation_units,
    validate_technical_indicators,
)
from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.ingest import (
    DEFAULT_INDEX_PROVIDER_SYMBOLS,
    SYMBOL_CHANGE_HISTORY_START,
)
from fdp.sources.eodhd.retry import (
    EodhdApiEvent,
    EodhdRequestRateLimiter,
    WeightedApiBudget,
)
from fdp.quality.validation import validate_daily_prices
from fdp.storage.schema import ensure_runtime_schemas

app = typer.Typer(help="Financial data platform command line interface.")
ingest_app = typer.Typer(help="Ingest source data into the database.")
validate_app = typer.Typer(help="Validate stored market data quality.")
repair_app = typer.Typer(help="Create and manage human-confirmed repair plans.")
quarantine_app = typer.Typer(help="Create and manage human-confirmed quarantine plans.")
research_app = typer.Typer(help="Read stored database data for research code.")
migrate_app = typer.Typer(help="Run operator-controlled resumable data migrations.")
bulk_unmatched_app = typer.Typer(help="Inspect and classify Bulk EOD unmatched rows.")
reconcile_app = typer.Typer(help="Reconcile staged data into canonical database tables.")
reconcile_bulk_unmatched_app = typer.Typer(
    help="Inspect, classify, route, and track Bulk EOD unmatched rows."
)
app.add_typer(ingest_app, name="ingest")
app.add_typer(validate_app, name="validate")
app.add_typer(repair_app, name="repair")
app.add_typer(quarantine_app, name="quarantine")
app.add_typer(research_app, name="research")
app.add_typer(migrate_app, name="migrate")
app.add_typer(reconcile_app, name="reconcile")
research_app.add_typer(bulk_unmatched_app, name="bulk-unmatched")
reconcile_app.add_typer(reconcile_bulk_unmatched_app, name="bulk-unmatched")

DAILY_PRICE_ASSET_TYPES = {"stock", "etf", "fund", "index"}
HISTORICAL_ASSET_TYPES = set(HISTORICAL_EOD_ASSET_TYPES)
BULK_ASSET_TYPES = set(US_BULK_EOD_ASSET_TYPES)
QUARANTINE_DAILY_PRICE_ISSUE_TYPES = {
    "duplicate_key",
    "invalid_ohlcv",
    "price_on_non_trading_day",
}


class CliProgressReporter:
    """Stable line-oriented reporter; JSON mode sends events to stderr."""

    def __init__(self, *, stderr: bool = False) -> None:
        self.stderr = stderr

    def on_event(self, event: ProgressEvent) -> None:
        if event.kind not in {"unit_completed", "unit_failed", "finish"}:
            return
        counters = " ".join(f"{key}={value}" for key, value in event.counters.items())
        message = (
            f"{event.job} progress completed={event.completed}/{event.total} "
            f"unit={event.unit or '-'} status={event.message or event.kind}"
        )
        if counters:
            message = f"{message} {counters}"
        typer.echo(message, err=self.stderr)

    def on_api_event(self, event: EodhdApiEvent) -> None:
        typer.echo(format_eodhd_event(event), err=self.stderr)


@app.callback()
def main() -> None:
    """Project CLI entrypoint."""


@app.command("menu")
def terminal_menu() -> None:
    """Open the bilingual human-oriented terminal ingest menu."""
    from fdp.menu import run_terminal_menu

    try:
        run_terminal_menu()
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc


@validate_app.command("docs-staleness")
def validate_documentation_staleness(
    root: Path = typer.Option(
        Path("."),
        "--root",
        help="Repository root or database_system_cli directory.",
    ),
) -> None:
    """Verify CLI tutorial coverage and managed Markdown/HTML mirrors."""
    try:
        report = validate_docs_staleness(root, get_command(app))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--root") from exc

    typer.echo(
        f"docs-staleness status={'current' if report.is_current else 'stale'} "
        f"documented={len(report.documented_leaf_routes)} "
        f"actual={len(report.actual_leaf_routes)}"
    )
    for label, values in (
        ("missing route", report.missing_routes),
        ("unknown route", report.unknown_routes),
        ("stale HTML", report.stale_html_pairs),
    ):
        for value in values:
            typer.echo(f"{label}: {value}")
    if not report.is_current:
        raise typer.Exit(code=1)


@migrate_app.command("daily-price-asset-types")
def migrate_daily_price_asset_types(
    phase: str = typer.Option(..., "--phase", help="Migration phase: plan or execute."),
    chunk_size: int = typer.Option(1_000, "--chunk-size", help="Rows per transaction."),
    max_chunks: int | None = typer.Option(
        None,
        "--max-chunks",
        help="Optional global chunk cap for a controlled resumable run.",
    ),
    execute: bool = typer.Option(False, "--execute", help="Required for the execute phase."),
    yes: bool = typer.Option(False, "--yes", help="Confirm source-row deletion after copy/verify."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Reconcile physical daily tables after canonical instrument type corrections."""
    normalized_phase = phase.strip().lower()
    if normalized_phase not in {"plan", "execute"}:
        raise typer.BadParameter("phase must be plan or execute")
    if chunk_size <= 0:
        raise typer.BadParameter("chunk-size must be positive")
    if max_chunks is not None and max_chunks <= 0:
        raise typer.BadParameter("max-chunks must be positive")
    if normalized_phase == "execute" and not (execute and yes):
        raise typer.BadParameter("execute phase requires --execute --yes")

    engine = create_engine(database_url_from_env())
    try:
        if normalized_phase == "plan":
            with engine.connect() as connection:
                ensure_runtime_schemas(connection)
                plan = plan_daily_price_asset_type_reconcile(connection)
            payload = {
                "phase": "plan",
                "total_rows": plan.total_rows,
                "groups": [asdict(group) for group in plan.groups],
            }
        else:
            with engine.connect() as connection:
                ensure_runtime_schemas(connection)
            result = reconcile_daily_price_asset_types(
                engine,
                chunk_size=chunk_size,
                max_chunks=max_chunks,
            )
            payload = {"phase": "execute", **asdict(result)}
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if as_json:
        typer.echo(json.dumps(payload, default=_json_cli_default, indent=2))
        return
    typer.echo(
        "daily-price-asset-types "
        + " ".join(f"{key}={value}" for key, value in payload.items() if key != "groups")
    )
    for group in payload.get("groups", []):
        typer.echo(
            f"  {group['source_asset_type']} -> {group['target_asset_type']}: "
            f"rows={group['rows_count']} instruments={group['instruments_count']}"
        )


@migrate_app.command("fund-daily-price")
def migrate_fund_daily_price(
    phase: str = typer.Option(
        ...,
        "--phase",
        help="Migration phase: plan, copy, verify, or finalize.",
    ),
    run_id: int | None = typer.Option(
        None,
        "--run-id",
        help="Existing split run id for resume, verify, or finalize.",
    ),
    backup_file: Path | None = typer.Option(
        None,
        "--backup-file",
        help="Absolute .sql or .sql.gz backup path; required for a new copy run.",
    ),
    chunk_size: int = typer.Option(
        10_000,
        "--chunk-size",
        help="Maximum Fund source rows per transaction.",
    ),
    max_chunks: int | None = typer.Option(
        None,
        "--max-chunks",
        help="Optional chunk cap for a controlled partial/resume run.",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Required for copy and finalize.",
    ),
    yes: bool = typer.Option(False, "--yes", help="Confirm copy or destructive finalize."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Plan, copy, verify, or finalize the physical ETF/Fund table split."""
    normalized_phase = phase.strip().lower()
    if normalized_phase not in {"plan", "copy", "verify", "finalize"}:
        raise typer.BadParameter("phase must be plan, copy, verify, or finalize")
    if run_id is not None and run_id <= 0:
        raise typer.BadParameter("run-id must be positive")
    if chunk_size <= 0:
        raise typer.BadParameter("chunk-size must be positive")
    if max_chunks is not None and max_chunks <= 0:
        raise typer.BadParameter("max-chunks must be positive")
    if normalized_phase in {"copy", "finalize"} and not (execute and yes):
        raise typer.BadParameter(f"{normalized_phase} requires --execute --yes")
    if normalized_phase in {"verify", "finalize"} and run_id is None:
        raise typer.BadParameter(f"{normalized_phase} requires --run-id")

    engine = create_engine(database_url_from_env())
    try:
        if normalized_phase == "plan":
            with engine.connect() as connection:
                ensure_runtime_schemas(connection)
                result = plan_fund_daily_prices(connection)
        elif normalized_phase == "copy":
            result = copy_fund_daily_prices(
                engine,
                backup_file=backup_file,
                run_id=run_id,
                chunk_size=chunk_size,
                max_chunks=max_chunks,
            )
        elif normalized_phase == "verify":
            result = verify_fund_daily_prices(engine, run_id=run_id)
        else:
            result = finalize_fund_daily_prices(
                engine,
                run_id=run_id,
                chunk_size=chunk_size,
                max_chunks=max_chunks,
            )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()

    payload = asdict(result)
    if as_json:
        typer.echo(json.dumps(payload, default=_json_cli_default, sort_keys=True))
        return
    typer.echo(f"fund-daily-price phase={normalized_phase}")
    for key, value in payload.items():
        if isinstance(value, dict):
            typer.echo(f"  {key}={json.dumps(value, sort_keys=True)}")
        else:
            typer.echo(f"  {key}={value}")


@ingest_app.command("instruments")
def ingest_instruments(
    market: str = typer.Option("US", "--market", help="Market code to ingest."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
    rename_from: str = typer.Option(
        SYMBOL_CHANGE_HISTORY_START.isoformat(),
        "--rename-from",
        help="Earliest EODHD symbol-change-history date to reconcile.",
    ),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Load the current active EODHD instrument universe and symbol changes."""
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    try:
        rename_from_date = date.fromisoformat(rename_from)
    except ValueError as exc:
        raise typer.BadParameter("rename-from must be YYYY-MM-DD") from exc

    output_mode = _parse_output_format(output)
    result = ActiveInstrumentsJob().run(
        market=market,
        rename_from=rename_from_date,
        reporter=CliProgressReporter(stderr=output_mode == "json"),
        override_source="cli",
    )
    if _emit_job_json(result, output_mode):
        return

    typer.echo(
        "instrument ingest "
        f"run_id={result.run_id} status={result.status} "
        f"fetched={result.rows_fetched} accepted={result.rows_matched} "
        f"rejected={result.rows_rejected} "
        f"lifecycle_events={result.metrics['lifecycle_events_inserted']}"
    )


@ingest_app.command("history")
def ingest_history(
    symbols: str | None = typer.Option(
        None,
        "--symbols",
        help="Comma-separated canonical or provider symbols; falls back to job defaults.",
    ),
    date_from: str | None = typer.Option(
        None,
        "--from",
        help="Start trade date; falls back to the selected job default.",
    ),
    date_to: str | None = typer.Option(
        None,
        "--to",
        help="End trade date; falls back to the selected job default.",
    ),
    market: str = typer.Option("US", "--market", help="Market code to ingest."),
    asset_types: str = typer.Option(
        "stock,etf,fund",
        "--asset-types",
        help="Historical price types: stock,etf,fund,index.",
    ),
    instrument_status: str = typer.Option(
        "active",
        "--instrument-status",
        help=(
            "Local instrument-master scope used to resolve symbols: active, inactive, or all; "
            "this is not an EODHD response field."
        ),
    ),
    include_inactive: bool | None = typer.Option(
        None,
        "--include-inactive/--active-only",
        help="Deprecated compatibility flag. Use --instrument-status all/active instead.",
    ),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Load stock, ETF, Fund, or index EOD history for explicit local instruments."""
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    parsed_symbols = None
    if symbols is not None:
        parsed_symbols = [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]
        if not parsed_symbols:
            raise typer.BadParameter("symbols must contain at least one symbol")
    parsed_from = _parse_optional_date(date_from, field_name="from")
    parsed_to = _parse_optional_date(date_to, field_name="to")
    if parsed_from is not None and parsed_to is not None and parsed_to < parsed_from:
        raise typer.BadParameter("to must be greater than or equal to from")
    parsed_asset_types = _parse_asset_types(asset_types, supported=HISTORICAL_ASSET_TYPES)
    resolved_instrument_status = _resolve_history_instrument_status(
        instrument_status=instrument_status,
        include_inactive=include_inactive,
    )
    if parsed_asset_types == ["stock"]:
        job = StockDailyJob()
    elif parsed_asset_types == ["etf"]:
        job = EtfDailyJob()
    elif parsed_asset_types == ["fund"]:
        job = FundDailyJob()
    else:
        job = HistoricalDailyJob(asset_types=tuple(parsed_asset_types))
    output_mode = _parse_output_format(output)
    try:
        result = job.run(
            symbols=parsed_symbols,
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
            instrument_status=resolved_instrument_status,
            reporter=CliProgressReporter(stderr=output_mode == "json"),
            override_source="cli",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _emit_job_json(result, output_mode):
        return

    typer.echo(
        "history ingest "
        f"run_id={result.run_id} status={result.status} "
        f"symbols={result.work_units_completed - result.work_units_failed}/"
        f"{result.work_units_total} "
        f"instrument_status={resolved_instrument_status} "
        f"fetched={result.rows_fetched} inserted={result.rows_inserted} "
        f"rejected={result.rows_rejected}"
    )
    if result.missing_symbols:
        typer.echo(f"missing_symbols={','.join(result.missing_symbols)}")


@ingest_app.command("id-mappings")
def ingest_id_mappings(
    exchange: str | None = typer.Option(
        None,
        "--exchange",
        help="Full EODHD exchange scope; mutually exclusive with --symbols.",
    ),
    symbols: str | None = typer.Option(
        None,
        "--symbols",
        help="Comma-separated EODHD provider symbols; mutually exclusive with --exchange.",
    ),
    page_limit: int = typer.Option(
        ID_MAPPING_DEFAULT_PAGE_LIMIT,
        "--page-limit",
        min=1,
        max=1000,
        help="EODHD rows per page.",
    ),
    start_offset: int = typer.Option(
        0,
        "--start-offset",
        min=0,
        help="Exchange pagination offset used to resume a partial run.",
    ),
    max_api_calls: int = typer.Option(
        ID_MAPPING_DEFAULT_MAX_API_CALLS,
        "--max-api-calls",
        min=1,
        help="Hard mapping API-unit budget; retries count against it.",
    ),
    max_requests_per_minute: int | None = typer.Option(
        None,
        "--max-requests-per-minute",
        min=1,
        max=1000,
        help="Optional request-rate override.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the local plan without API calls or database writes.",
    ),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Synchronize EODHD CUSIP/ISIN/FIGI/LEI/CIK mappings."""
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")
    parsed_symbols = None
    if symbols is not None:
        parsed_symbols = [value.strip() for value in symbols.split(",") if value.strip()]
        if not parsed_symbols:
            raise typer.BadParameter("symbols must contain at least one provider symbol")
    output_mode = _parse_output_format(output)
    try:
        result = IdentifierMappingJob().run(
            exchange=exchange,
            symbols=parsed_symbols,
            page_limit=page_limit,
            start_offset=start_offset,
            max_api_calls=max_api_calls,
            max_requests_per_minute=max_requests_per_minute,
            execute=not dry_run,
            reporter=CliProgressReporter(stderr=output_mode == "json"),
            override_source="cli",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _emit_job_json(result, output_mode):
        return
    typer.echo(
        "id-mappings ingest "
        f"run_id={result.run_id or '-'} status={result.status} "
        f"fetched={result.rows_fetched} matched={result.rows_matched} "
        f"inserted={result.rows_inserted} unmatched={result.rows_unmatched} "
        f"invalid={result.rows_rejected} api_calls={result.api_calls} "
        f"next_offset={result.metrics.get('next_offset')}"
    )


@ingest_app.command("delisted-instruments")
def ingest_delisted_instruments(
    market: str = typer.Option("US", "--market", help="Market code to ingest."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Load inactive/delisted stock, ETF, and Fund instruments from EODHD."""
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    output_mode = _parse_output_format(output)
    result = DelistedInstrumentsJob().run(
        market=market,
        reporter=CliProgressReporter(stderr=output_mode == "json"),
        override_source="cli",
    )
    if _emit_job_json(result, output_mode):
        return

    typer.echo(
        "delisted-instruments ingest "
        f"run_id={result.run_id} status={result.status} "
        f"fetched={result.rows_fetched} accepted={result.rows_matched} "
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
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
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

    output_mode = _parse_output_format(output)
    try:
        result = IndexDailyJob(currency=currency, currency_source="cli").run(
            symbols=parsed_provider_symbols,
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
            reporter=CliProgressReporter(stderr=output_mode == "json"),
            override_source="cli",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _emit_job_json(result, output_mode):
        return

    typer.echo(
        "index history ingest "
        f"run_id={result.run_id} status={result.status} "
        f"symbols={result.work_units_completed - result.work_units_failed}/"
        f"{result.work_units_total} "
        f"fetched={result.rows_fetched} inserted={result.rows_inserted} "
        f"rejected={result.rows_rejected}"
    )


@ingest_app.command("calendar")
def ingest_calendar(
    date_from: str = typer.Option(..., "--from", help="Start calendar date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End calendar date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market/exchange code to ingest."),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    parsed_from, parsed_to = _parse_date_range(date_from, date_to)

    output_mode = _parse_output_format(output)
    try:
        result = MarketCalendarJob().run(
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
            reporter=CliProgressReporter(stderr=output_mode == "json"),
            override_source="cli",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _emit_job_json(result, output_mode):
        return

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
        "stock,etf,fund",
        "--asset-types",
        help="Comma-separated asset types to write: stock,etf,fund.",
    ),
    market: str = typer.Option("US", "--market", help="Internal market code to match instruments."),
    instrument_status: str = typer.Option(
        "active",
        "--instrument-status",
        help=(
            "Local instrument-master scope used for identity resolution: active or all; "
            "this is not an EODHD Bulk response field."
        ),
    ),
    source: str = typer.Option("eodhd", "--source", help="Source provider."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Load one Bulk EOD date and match it against the selected local instrument scope."""
    if source.lower() != "eodhd":
        raise typer.BadParameter("only eodhd is supported")

    parsed_date = _parse_optional_date(trade_date, field_name="date")
    parsed_symbols = None
    if symbols is not None:
        parsed_symbols = [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]
        if not parsed_symbols:
            raise typer.BadParameter("symbols must contain at least one symbol when provided")
    parsed_asset_types = _parse_asset_types(asset_types, supported=BULK_ASSET_TYPES)
    parsed_instrument_status = instrument_status.strip().lower()
    if parsed_instrument_status not in {"active", "all"}:
        raise typer.BadParameter("instrument-status must be active or all")

    output_mode = _parse_output_format(output)
    try:
        result = BulkDailyJob().run(
            exchange=exchange,
            trade_date=parsed_date,
            symbols=parsed_symbols,
            market=market,
            asset_types=parsed_asset_types,
            instrument_status=parsed_instrument_status,
            reporter=CliProgressReporter(stderr=output_mode == "json"),
            override_source="cli",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _emit_job_json(result, output_mode):
        return

    typer.echo(
        "daily bulk ingest "
        f"run_id={result.run_id} status={result.status} exchange={result.parameters['exchange']} "
        f"date={result.parameters['trade_date'] or 'last-trading-day'} "
        f"fetched={result.rows_fetched} "
        f"matched={result.rows_matched} inserted={result.rows_inserted} "
        f"rejected={result.rows_rejected}"
    )


@ingest_app.command("daily-range")
def ingest_daily_range(
    date_from: str = typer.Option(..., "--from", help="Start calendar date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End calendar date in YYYY-MM-DD format."),
    exchange: str = typer.Option("US", "--exchange", help="EODHD bulk exchange code."),
    asset_types: str = typer.Option(
        "stock,etf,fund",
        "--asset-types",
        help="Comma-separated asset types to write: stock,etf,fund.",
    ),
    market: str = typer.Option("US", "--market", help="Internal market code to match instruments."),
    instrument_status: str = typer.Option(
        "active",
        "--instrument-status",
        help=(
            "Local instrument-master scope used for identity resolution: active or all; "
            "this is not an EODHD Bulk response field."
        ),
    ),
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
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
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
    parsed_asset_types = _parse_asset_types(asset_types, supported=BULK_ASSET_TYPES)
    parsed_instrument_status = instrument_status.strip().lower()
    if parsed_instrument_status not in {"active", "all"}:
        raise typer.BadParameter("instrument-status must be active or all")
    if not yes:
        if not dry_run:
            raise typer.BadParameter("--execute requires --yes")

    output_mode = _parse_output_format(output)
    try:
        result = DailyRangeJob().run(
            execute=not dry_run,
            date_from=parsed_from,
            date_to=parsed_to,
            exchange=exchange,
            asset_types=parsed_asset_types,
            market=market,
            instrument_status=parsed_instrument_status,
            bytes_per_row=bytes_per_row,
            max_estimated_gb=max_estimated_gb,
            parallel=parallel,
            workers=workers,
            max_requests_per_minute=max_requests_per_minute,
            max_api_calls=max_api_calls,
            reporter=CliProgressReporter(stderr=output_mode == "json"),
            override_source="cli",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _emit_job_json(result, output_mode):
        return

    preflight = result.preflight
    if preflight is None:
        raise RuntimeError("daily-range result is missing preflight details")
    parameters = preflight.parameters
    typer.echo(
        "daily-range estimate "
        f"date_from={parameters['date_from']} date_to={parameters['date_to']} "
        f"trading_days={preflight.work_units} estimated_rows={preflight.estimated_rows} "
        f"estimated_gb={preflight.estimated_gb:.2f} "
        f"max_estimated_gb={parameters['max_estimated_gb']:.2f} "
        f"estimated_api_calls={preflight.estimated_api_calls} "
        f"max_api_calls={parameters['max_api_calls']} "
        f"parallel={str(parameters['parallel']).lower()} workers={parameters['workers']} "
        f"max_requests_per_minute={parameters['max_requests_per_minute']}"
        f" instrument_status={parameters['instrument_status']}"
    )
    if result.status == "dry_run":
        typer.echo("dry-run only; rerun with --execute --yes to ingest this range")
        return

    typer.echo(
        "daily-range ingest "
        f"status={result.status} trading_days={result.work_units_total} "
        f"rows_fetched={result.rows_fetched} rows_matched={result.rows_matched} "
        f"rows_inserted={result.rows_inserted} rows_rejected={result.rows_rejected} "
        f"unmatched={result.rows_unmatched} http_requests={result.api_calls} "
        f"api_call_cost_estimate={preflight.estimated_api_calls} "
        f"api_units_consumed={result.metrics.get('api_units_consumed', 0)} "
        f"api_units_remaining={result.metrics.get('api_units_remaining', 0)} "
        f"completed_days={result.work_units_completed} failed_days={result.work_units_failed}"
    )


@ingest_app.command("bulk-unmatched-route")
def ingest_bulk_unmatched_route(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    asset_types: str = typer.Option(
        "stock,etf,fund,index",
        "--asset-types",
        help="Comma-separated asset types to route: stock,etf,fund,index.",
    ),
    market: str = typer.Option("US", "--market", help="Market code to route."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--execute",
        help="Preview by default; use --execute --yes to write price tables.",
    ),
    yes: bool = typer.Option(False, "--yes", help="Required with --execute."),
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Optional max complete instrument/date groups to route.",
    ),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Route classified Bulk EOD unmatched observations into split daily price tables."""
    _emit_reconcile_deprecation(
        "j21 ingest bulk-unmatched-route",
        "j21 reconcile bulk-unmatched route",
    )
    if limit is not None and limit <= 0:
        raise typer.BadParameter("limit must be positive")
    if not dry_run and not yes:
        raise typer.BadParameter("bulk-unmatched-route execution requires --yes")
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    parsed_asset_types = _parse_asset_types(asset_types, supported=DAILY_PRICE_ASSET_TYPES)

    output_mode = _parse_output_format(output)
    try:
        result = BulkUnmatchedReconcileJob().route(
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
            asset_types=parsed_asset_types,
            limit=limit,
            execute=not dry_run,
            reporter=CliProgressReporter(stderr=output_mode == "json"),
            override_source="cli",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _emit_job_json(result, output_mode):
        return

    mode = "dry_run" if result.status == "dry_run" else "executed"
    typer.echo(
        "bulk-unmatched-route "
        f"mode={mode} run_id={result.run_id or '-'} "
        f"date_from={parsed_from} date_to={parsed_to} "
        f"routeable={result.rows_matched} rows_inserted={result.rows_inserted} "
        f"rows_rejected={result.rows_rejected}"
    )


@validate_app.command("daily-price")
def validate_daily_price(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    asset_types: str = typer.Option(
        "stock,etf,fund,index",
        "--asset-types",
        help="Comma-separated US asset types to validate: stock,etf,fund,index.",
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
        "stock,etf,fund,index",
        "--asset-types",
        help="Comma-separated US asset types to plan: stock,etf,fund,index.",
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
        "stock,etf,fund,index",
        "--asset-types",
        help="Comma-separated US asset types to plan: stock,etf,fund,index.",
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


@reconcile_bulk_unmatched_app.command("summary")
def reconcile_bulk_unmatched_summary(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market code to inspect."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Summarize the current staging backlog; this command makes no API calls."""
    output_mode = _parse_output_format(output)
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    rows = BulkUnmatchedReconcileJob().summary(
        date_from=parsed_from,
        date_to=parsed_to,
        market=market,
    )
    if output_mode == "json":
        typer.echo(
            json.dumps(
                [row.to_dict() for row in rows],
                default=_json_cli_default,
                sort_keys=True,
            )
        )
        return
    typer.echo(
        f"bulk-unmatched summary date_from={parsed_from} date_to={parsed_to} "
        f"groups={len(rows)} api_calls=0"
    )
    for row in rows:
        typer.echo(
            "  "
            f"status={row.classification_status} "
            f"asset_type={row.classified_asset_type or '-'} count={row.row_count}"
        )


@reconcile_bulk_unmatched_app.command("list")
def reconcile_bulk_unmatched_list(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    status: str | None = typer.Option(None, "--status", help="Optional classification status."),
    market: str = typer.Option("US", "--market", help="Market code to inspect."),
    limit: int = typer.Option(50, "--limit", help="Maximum observations to print."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """List a bounded staging sample; this command makes no API calls."""
    if limit <= 0:
        raise typer.BadParameter("limit must be positive")
    output_mode = _parse_output_format(output)
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    rows = BulkUnmatchedReconcileJob().list(
        date_from=parsed_from,
        date_to=parsed_to,
        market=market,
        status=status,
        limit=limit,
    )
    if output_mode == "json":
        typer.echo(json.dumps(rows, default=_json_cli_default, sort_keys=True))
        return
    typer.echo(f"bulk-unmatched list rows={len(rows)} api_calls=0")
    _print_bulk_unmatched_rows(rows, limit=limit)


@reconcile_bulk_unmatched_app.command("classify")
def reconcile_bulk_unmatched_classify(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market code to classify."),
    statuses: str = typer.Option(
        "unresolved",
        "--statuses",
        help="Comma-separated source states; CLI default is unresolved only.",
    ),
    advanced: bool = typer.Option(
        False,
        "--advanced",
        help="Required to reclassify ambiguous or non_price_asset observations.",
    ),
    batch_size: int = typer.Option(5_000, "--batch-size", help="Rows per committed batch."),
    limit: int | None = typer.Option(None, "--limit", help="Optional max rows this command."),
    run_id: int | None = typer.Option(None, "--run-id", help="Resume a prior reconcile run."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Classify staging rows in checkpointed local batches; API cost is always zero."""
    parsed_statuses = _parse_statuses(statuses) or ["unresolved"]
    advanced_statuses = {"ambiguous", "non_price_asset"} & set(parsed_statuses)
    if advanced_statuses and not advanced:
        raise typer.BadParameter(
            "ambiguous/non_price_asset classification requires --advanced"
        )
    output_mode = _parse_output_format(output)
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    try:
        result = BulkUnmatchedReconcileJob().classify(
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
            statuses=parsed_statuses,
            batch_size=batch_size,
            limit=limit,
            run_id=run_id,
            reporter=CliProgressReporter(stderr=output_mode == "json"),
            override_source="cli",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _emit_job_json(result, output_mode):
        return
    typer.echo(
        "bulk-unmatched classify "
        f"run_id={result.run_id} status={result.status} "
        f"processed={result.work_units_completed}/{result.work_units_total} "
        f"matched={result.rows_matched} rejected={result.rows_rejected} "
        f"remaining={result.metrics['remaining_eligible']} "
        f"phase={result.metrics['checkpoint_phase']} api_calls=0"
    )
    if result.error_message:
        typer.echo(f"resume_hint={result.error_message}")


@reconcile_bulk_unmatched_app.command("route")
def reconcile_bulk_unmatched_route(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    asset_types: str = typer.Option(
        "stock,etf,fund,index",
        "--asset-types",
        help="Canonical target tables: stock,etf,fund,index.",
    ),
    market: str = typer.Option("US", "--market", help="Market code to route."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--execute",
        help="Preview by default; use --execute --yes for atomic writes.",
    ),
    yes: bool = typer.Option(False, "--yes", help="Required with --execute."),
    batch_size: int = typer.Option(
        1_000,
        "--batch-size",
        help="Complete instrument/date groups per committed batch.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Optional max complete instrument/date groups this command.",
    ),
    run_id: int | None = typer.Option(
        None,
        "--run-id",
        help="Continue the run created by classify; standalone execute creates one.",
    ),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Preview or route complete natural-key groups; API cost is always zero."""
    if not dry_run and not yes:
        raise typer.BadParameter("route execution requires --yes")
    output_mode = _parse_output_format(output)
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    parsed_assets = _parse_asset_types(asset_types, supported=DAILY_PRICE_ASSET_TYPES)
    try:
        result = BulkUnmatchedReconcileJob().route(
            date_from=parsed_from,
            date_to=parsed_to,
            market=market,
            asset_types=parsed_assets,
            batch_size=batch_size,
            limit=limit,
            execute=not dry_run,
            run_id=run_id,
            reporter=CliProgressReporter(stderr=output_mode == "json"),
            override_source="cli",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if _emit_job_json(result, output_mode):
        return
    typer.echo(
        "bulk-unmatched route "
        f"run_id={result.run_id or '-'} status={result.status} "
        f"groups={result.work_units_completed}/{result.work_units_total} "
        f"routed={result.rows_matched} inserted={result.rows_inserted} "
        f"shadowed={result.metrics.get('shadowed', 0)} "
        f"route_failed={result.metrics.get('route_failed', 0)} "
        f"remaining={result.metrics.get('remaining_groups', 0)} api_calls=0"
    )
    if result.error_message:
        typer.echo(f"resume_hint={result.error_message}")


@reconcile_bulk_unmatched_app.command("status")
def reconcile_bulk_unmatched_status(
    run_id: int = typer.Option(..., "--run-id", help="Reconcile workflow run ID."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Read one persisted reconcile checkpoint; API cost is always zero."""
    output_mode = _parse_output_format(output)
    try:
        payload = BulkUnmatchedReconcileJob().status(run_id=run_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if output_mode == "json":
        typer.echo(json.dumps(payload, default=_json_cli_default, sort_keys=True))
        return
    checkpoint = payload["checkpoint"]
    route_checkpoint = checkpoint["route"]
    route_observations = route_checkpoint.get(
        "observations_selected",
        int(route_checkpoint["routed"])
        + int(route_checkpoint["shadowed"])
        + int(route_checkpoint["route_failed"]),
    )
    typer.echo(
        "bulk-unmatched status "
        f"run_id={run_id} status={payload['status']} phase={checkpoint['phase']} "
        f"api_calls={payload['api_calls']}"
    )
    typer.echo(
        "  classify "
        f"rows={checkpoint['classify']['rows_processed']} "
        f"batches={checkpoint['classify']['batches_committed']} "
        f"checkpoint={checkpoint['classify'].get('last_trade_date') or '-'}"
        f"/{checkpoint['classify'].get('last_observation_id') or '-'}"
    )
    typer.echo(
        "  route "
        f"groups={route_checkpoint['groups_processed']} "
        f"observations={route_observations} "
        f"routed={route_checkpoint['routed']} "
        f"shadowed={route_checkpoint['shadowed']} "
        f"failed={route_checkpoint['route_failed']} "
        f"audits={route_checkpoint['identity_audits']} "
        f"checkpoint={route_checkpoint.get('last_trade_date') or '-'}"
        f"/{route_checkpoint.get('last_instrument_id') or '-'}"
    )
    typer.echo(
        "  validation "
        f"quality_runs={len(checkpoint['validation']['quality_check_run_ids'])} "
        f"issues={checkpoint['validation']['issue_count']}"
    )
    typer.echo(f"  resume_hint={payload['resume_hint']}")


@bulk_unmatched_app.command("summary")
def research_bulk_unmatched_summary(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market code to inspect."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of text."),
) -> None:
    """Summarize Bulk EOD unmatched staging rows by status and asset type."""
    _emit_reconcile_deprecation(
        "j21 research bulk-unmatched summary",
        "j21 reconcile bulk-unmatched summary",
    )
    reconcile_bulk_unmatched_summary(
        date_from=date_from,
        date_to=date_to,
        market=market,
        output="json" if as_json else "text",
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
    _emit_reconcile_deprecation(
        "j21 research bulk-unmatched list",
        "j21 reconcile bulk-unmatched list",
    )
    reconcile_bulk_unmatched_list(
        date_from=date_from,
        date_to=date_to,
        status=status,
        market=market,
        limit=limit,
        output="json" if as_json else "text",
    )


@bulk_unmatched_app.command("classify")
def research_bulk_unmatched_classify(
    date_from: str = typer.Option(..., "--from", help="Start trade date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End trade date in YYYY-MM-DD format."),
    market: str = typer.Option("US", "--market", help="Market code to classify."),
    limit: int | None = typer.Option(None, "--limit", help="Optional max rows to classify."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of text."),
) -> None:
    """Classify unresolved unmatched rows using strict provider-symbol matches."""
    _emit_reconcile_deprecation(
        "j21 research bulk-unmatched classify",
        "j21 reconcile bulk-unmatched classify",
    )
    reconcile_bulk_unmatched_classify(
        date_from=date_from,
        date_to=date_to,
        market=market,
        statuses="unresolved",
        advanced=False,
        batch_size=5_000,
        limit=limit,
        run_id=None,
        output="json" if as_json else "text",
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
        help="Asset type to read: stock, etf, fund, index, forex, or crypto.",
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


@research_app.command("technical-validate")
def research_technical_validate(
    symbols: str = typer.Option(
        "AAPL.US,META.US,SPY.US",
        "--symbols",
        help="Comma-separated canonical provider symbols.",
    ),
    date_from: str = typer.Option(..., "--from", help="Start date in YYYY-MM-DD format."),
    date_to: str = typer.Option(..., "--to", help="End date in YYYY-MM-DD format."),
    max_api_units: int = typer.Option(
        200,
        "--max-api-units",
        help="Hard weighted-unit budget; this diagnostic never permits more than 200.",
    ),
    tolerance: float = typer.Option(
        0.0002,
        "--tolerance",
        help="Maximum absolute error after provider four-decimal rounding.",
    ),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Compare local SMA20/EMA20/RSI14 with a bounded EODHD Technical sample."""
    parsed_symbols = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]
    if not parsed_symbols:
        raise typer.BadParameter("symbols must contain at least one provider symbol")
    if max_api_units <= 0 or max_api_units > 200:
        raise typer.BadParameter("max-api-units must be between 1 and 200")
    if tolerance < 0:
        raise typer.BadParameter("tolerance must be non-negative")
    normalized_output = output.strip().lower()
    if normalized_output not in {"text", "json"}:
        raise typer.BadParameter("output must be text or json")
    parsed_from, parsed_to = _parse_date_range(date_from, date_to)
    required_units = required_technical_validation_units(len(parsed_symbols))
    if required_units > max_api_units:
        raise typer.BadParameter(
            f"technical validation requires {required_units} units for {len(parsed_symbols)} "
            f"symbols, exceeding max-api-units={max_api_units}"
        )

    budget = WeightedApiBudget(max_api_units)
    client = _eodhd_client(
        eodhd_api_key_from_env(),
        api_budget=budget,
        progress_to_stderr=normalized_output == "json",
    )
    engine = create_engine(database_url_from_env())
    with engine.connect() as connection:
        try:
            comparisons = validate_technical_indicators(
                connection,
                client,
                provider_symbols=parsed_symbols,
                date_from=parsed_from,
                date_to=parsed_to,
                tolerance=tolerance,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    payload = {
        "status": "pass" if all(row.status == "pass" for row in comparisons) else "mismatch",
        "date_from": parsed_from,
        "date_to": parsed_to,
        "tolerance": tolerance,
        "api_units_required": required_units,
        "api_budget": asdict(budget.snapshot()),
        "comparisons": [row.to_dict() for row in comparisons],
    }
    if normalized_output == "json":
        typer.echo(json.dumps(payload, default=_json_cli_default, indent=2))
    else:
        typer.echo(
            f"technical-validate status={payload['status']} symbols={len(parsed_symbols)} "
            f"comparisons={len(comparisons)} api_units={budget.snapshot().consumed}/{max_api_units}"
        )
        typer.echo(
            "provider_symbol\tasset_type\tindicator\tperiod\tstatus\toverlap\tmax_abs_error"
        )
        for row in comparisons:
            error = "" if row.max_absolute_error is None else f"{row.max_absolute_error:.8f}"
            typer.echo(
                f"{row.provider_symbol}\t{row.asset_type}\t{row.local_field}\t{row.period}\t"
                f"{row.status}\t{row.overlapping_rows}\t{error}"
            )
    if payload["status"] != "pass":
        raise typer.Exit(code=1)


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
    supported_asset_types = supported or set(CANONICAL_ASSET_TYPES)
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


def _emit_reconcile_deprecation(old_command: str, new_command: str) -> None:
    """Keep v0.4 aliases visible while directing automation to the v0.5 path."""
    typer.echo(
        f"DEPRECATED v0.4: {old_command}; use {new_command}; old path removed in v0.5",
        err=True,
    )


def _parse_output_format(output: str) -> str:
    normalized = output.strip().lower()
    if normalized not in {"text", "json"}:
        raise typer.BadParameter("output must be text or json")
    return normalized


def _emit_job_json(result: JobResult, output: str) -> bool:
    if output != "json":
        return False
    typer.echo(json.dumps(result.to_dict(), default=_json_cli_default, indent=2))
    return True


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
    api_budget: WeightedApiBudget | None = None,
    progress_to_stderr: bool = False,
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
        api_budget=api_budget,
        progress_callback=(
            _echo_eodhd_event_stderr if progress_to_stderr else _echo_eodhd_event
        ),
    )


def _echo_eodhd_event(event: EodhdApiEvent) -> None:
    """Print EODHD request progress without exposing API keys."""
    typer.echo(_format_eodhd_event(event))


def _echo_eodhd_event_stderr(event: EodhdApiEvent) -> None:
    """Print EODHD progress to stderr so JSON stdout remains machine-readable."""
    typer.echo(_format_eodhd_event(event), err=True)


def _format_eodhd_event(event: EodhdApiEvent) -> str:
    """Format one EODHD request lifecycle event without including credentials."""
    return format_eodhd_event(event)
