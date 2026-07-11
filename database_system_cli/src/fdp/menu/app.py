"""Bilingual arrow-key menu for human-operated J21 ingest jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
import shlex
import sys
from typing import Any

import typer

from fdp.get_data import (
    ActiveInstrumentsJob,
    BulkDailyJob,
    BulkUnmatchedReconcileJob,
    DailyRangeJob,
    DelistedInstrumentsJob,
    EtfDailyJob,
    FundDailyJob,
    HistoricalDailyJob,
    IndexDailyJob,
    JobPreflight,
    JobResult,
    JobRuntime,
    MarketCalendarJob,
    StockDailyJob,
)
from fdp.get_data.historical.get_index_daily import DEFAULT_PROVIDER_SYMBOLS
from fdp.get_data.registry import INGEST_JOB_DEFINITIONS
from fdp.menu.i18n import Language, tr
from fdp.menu.progress import TqdmProgressReporter
from fdp.menu.prompts import PromptSession


class MenuCancelled(Exception):
    """Raised when an operator cancels one prompt and returns to the menu."""


def run_terminal_menu(
    prompts: PromptSession | None = None,
    *,
    force_tty: bool = False,
) -> None:
    """Run the human menu without changing any job defaults or shelling out."""
    if not force_tty and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        raise RuntimeError(
            "j21 menu requires an interactive TTY; use j21 ingest in scripts or AI tools"
        )

    session = prompts or PromptSession()
    language = session.select(
        "选择语言 / Choose language",
        [("中文", "zh"), ("English", "en")],
        default="zh",
    )
    if language is None:
        return

    while True:
        typer.echo(f"\n{tr(language, 'main')}")
        action = session.select(
            tr(language, "choose_main"),
            [(tr(language, "ingest"), "ingest"), (tr(language, "exit"), "exit")],
            default="ingest",
        )
        if action in {None, "exit"}:
            return
        job_key = session.select(
            tr(language, "choose_job"),
            [
                (
                    f"{tr(language, definition.category)} > {tr(language, definition.label_key)}",
                    definition.key,
                )
                for definition in INGEST_JOB_DEFINITIONS
            ]
            + [(tr(language, "back"), "back")],
        )
        if job_key in {None, "back"}:
            continue
        try:
            JOB_HANDLERS[job_key](session, language)
        except MenuCancelled:
            typer.echo(tr(language, "cancelled"))
        except KeyboardInterrupt:
            typer.echo(f"\n{tr(language, 'cancelled')}")
        except Exception as exc:
            typer.echo(f"{tr(language, 'failed')}: {exc}", err=True)


def _run_instruments(session: PromptSession, language: Language) -> None:
    job = ActiveInstrumentsJob()
    market = "US"
    rename_from = None
    if _advanced(session, language):
        market = _text(session, tr(language, "market"), default="US")
        rename_from = _date_value(session, "rename-from", default=date(2022, 1, 1))
    runtime = JobRuntime.from_env()
    preflight = job.preflight(
        market=market,
        rename_from=rename_from,
        override_source="menu",
    )
    parameters = preflight.parameters
    command = _command(
        "ingest",
        "instruments",
        "--market",
        parameters["market"],
        "--rename-from",
        parameters["rename_from"],
    )
    _confirm_and_run(
        session,
        language,
        preflight,
        command,
        lambda reporter: job.run(
            market=market,
            rename_from=rename_from,
            runtime=runtime,
            reporter=reporter,
            override_source="menu",
            preflight=preflight,
        ),
    )


def _run_delisted(session: PromptSession, language: Language) -> None:
    job = DelistedInstrumentsJob()
    market = "US"
    if _advanced(session, language):
        market = _text(session, tr(language, "market"), default="US")
    runtime = JobRuntime.from_env()
    preflight = job.preflight(market=market, override_source="menu")
    command = _command("ingest", "delisted-instruments", "--market", market)
    _confirm_and_run(
        session,
        language,
        preflight,
        command,
        lambda reporter: job.run(
            market=market,
            runtime=runtime,
            reporter=reporter,
            override_source="menu",
            preflight=preflight,
        ),
    )


def _run_stock_daily(session: PromptSession, language: Language) -> None:
    _run_historical(session, language, StockDailyJob(), "stock")


def _run_etf_daily(session: PromptSession, language: Language) -> None:
    _run_historical(session, language, EtfDailyJob(), "etf")


def _run_fund_daily(session: PromptSession, language: Language) -> None:
    _run_historical(session, language, FundDailyJob(), "fund")


def _run_historical(
    session: PromptSession,
    language: Language,
    job: HistoricalDailyJob,
    asset_type: str,
) -> None:
    default_symbols = ",".join(job.default_symbols)
    symbols = _csv(_text(session, tr(language, "symbols"), default=default_symbols))
    date_from = _date_value(session, tr(language, "date_from"), default=job.default_date_from)
    date_to = _date_value(session, tr(language, "date_to"), default=job.default_date_to)
    instrument_status = session.select(
        tr(language, "status"),
        [("Active", "active"), ("Inactive/delisted", "inactive"), ("Both", "all")],
        default="active",
    )
    if instrument_status is None:
        raise MenuCancelled
    market = "US"
    if _advanced(session, language):
        market = _text(session, tr(language, "market"), default="US")
    runtime = JobRuntime.from_env()
    preflight = job.preflight(
        symbols=symbols,
        date_from=date_from,
        date_to=date_to,
        market=market,
        instrument_status=instrument_status,
        runtime=runtime,
        override_source="menu",
    )
    command = _command(
        "ingest",
        "history",
        "--symbols",
        ",".join(symbols),
        "--from",
        date_from,
        "--to",
        date_to,
        "--asset-types",
        asset_type,
        "--instrument-status",
        instrument_status,
        "--market",
        market,
    )
    _confirm_and_run(
        session,
        language,
        preflight,
        command,
        lambda reporter: job.run(
            symbols=symbols,
            date_from=date_from,
            date_to=date_to,
            market=market,
            instrument_status=instrument_status,
            runtime=runtime,
            reporter=reporter,
            override_source="menu",
            preflight=preflight,
        ),
    )


def _run_index_daily(session: PromptSession, language: Language) -> None:
    symbols = _csv(
        _text(
            session,
            tr(language, "provider_symbols"),
            default=",".join(DEFAULT_PROVIDER_SYMBOLS),
        )
    )
    date_from = _date_value(session, tr(language, "date_from"))
    date_to = _date_value(session, tr(language, "date_to"))
    market = "US"
    currency = "USD"
    if _advanced(session, language):
        market = _text(session, tr(language, "market"), default="US")
        currency = _text(session, tr(language, "currency"), default="USD")
    job = IndexDailyJob(currency=currency, currency_source="menu")
    runtime = JobRuntime.from_env()
    preflight = job.preflight(
        symbols=symbols,
        date_from=date_from,
        date_to=date_to,
        market=market,
        runtime=runtime,
        override_source="menu",
    )
    command = _command(
        "ingest",
        "indices",
        "--provider-symbols",
        ",".join(symbols),
        "--from",
        date_from,
        "--to",
        date_to,
        "--market",
        market,
        "--currency",
        currency,
    )
    _confirm_and_run(
        session,
        language,
        preflight,
        command,
        lambda reporter: job.run(
            symbols=symbols,
            date_from=date_from,
            date_to=date_to,
            market=market,
            runtime=runtime,
            reporter=reporter,
            override_source="menu",
            preflight=preflight,
        ),
    )


def _run_calendar(session: PromptSession, language: Language) -> None:
    date_from = _date_value(session, tr(language, "date_from"))
    date_to = _date_value(session, tr(language, "date_to"))
    market = "US"
    if _advanced(session, language):
        market = _text(session, tr(language, "market"), default="US")
    job = MarketCalendarJob()
    runtime = JobRuntime.from_env()
    preflight = job.preflight(
        date_from=date_from,
        date_to=date_to,
        market=market,
        override_source="menu",
    )
    command = _command(
        "ingest",
        "calendar",
        "--from",
        date_from,
        "--to",
        date_to,
        "--market",
        market,
    )
    _confirm_and_run(
        session,
        language,
        preflight,
        command,
        lambda reporter: job.run(
            date_from=date_from,
            date_to=date_to,
            market=market,
            runtime=runtime,
            reporter=reporter,
            override_source="menu",
            preflight=preflight,
        ),
    )


def _run_bulk_daily(session: PromptSession, language: Language) -> None:
    trade_date = _date_value(session, tr(language, "trade_date"), allow_blank=True)
    raw_symbols = session.text(tr(language, "symbols"), default="")
    if raw_symbols is None:
        raise MenuCancelled
    symbols = _csv(raw_symbols, allow_empty=True)
    asset_types = _assets(session, language, defaults={"stock", "etf", "fund"})
    instrument_status = session.select(
        tr(language, "status"),
        [("Active", "active"), ("Active + inactive", "all")],
        default="active",
    )
    if instrument_status is None:
        raise MenuCancelled
    exchange = "US"
    market = "US"
    if _advanced(session, language):
        exchange = _text(session, tr(language, "exchange"), default="US")
        market = _text(session, tr(language, "market"), default="US")
    job = BulkDailyJob()
    runtime = JobRuntime.from_env()
    preflight = job.preflight(
        exchange=exchange,
        trade_date=trade_date,
        symbols=symbols,
        asset_types=asset_types,
        market=market,
        instrument_status=instrument_status,
        override_source="menu",
    )
    args: list[Any] = ["ingest", "daily", "--exchange", exchange]
    if trade_date is not None:
        args.extend(["--date", trade_date])
    if symbols:
        args.extend(["--symbols", ",".join(symbols)])
    args.extend(
        [
            "--asset-types",
            ",".join(asset_types),
            "--market",
            market,
            "--instrument-status",
            instrument_status,
        ]
    )
    command = _command(*args)
    _confirm_and_run(
        session,
        language,
        preflight,
        command,
        lambda reporter: job.run(
            exchange=exchange,
            trade_date=trade_date,
            symbols=symbols,
            asset_types=asset_types,
            market=market,
            instrument_status=instrument_status,
            runtime=runtime,
            reporter=reporter,
            override_source="menu",
            preflight=preflight,
        ),
    )


def _run_daily_range(session: PromptSession, language: Language) -> None:
    date_from = _date_value(session, tr(language, "date_from"))
    date_to = _date_value(session, tr(language, "date_to"))
    asset_types = _assets(session, language, defaults={"stock", "etf", "fund"})
    instrument_status = session.select(
        tr(language, "status"),
        [("Active", "active"), ("Active + inactive", "all")],
        default="active",
    )
    if instrument_status is None:
        raise MenuCancelled
    runtime = JobRuntime.from_env()
    advanced = _advanced(session, language)
    exchange = "US"
    market = "US"
    parallel = workers = max_rpm = max_calls = None
    max_gb = None
    if advanced:
        exchange = _text(session, tr(language, "exchange"), default="US")
        market = _text(session, tr(language, "market"), default="US")
        mode = session.select(
            tr(language, "parallel"),
            [("Parallel", "parallel"), ("Sequential", "sequential")],
            default="parallel" if runtime.config.daily_range_parallel_enabled else "sequential",
        )
        if mode is None:
            raise MenuCancelled
        parallel = mode == "parallel"
        if parallel:
            workers = _int_value(
                session,
                tr(language, "workers"),
                default=runtime.config.daily_range_max_workers,
            )
        max_rpm = _int_value(
            session,
            tr(language, "max_rpm"),
            default=runtime.config.max_requests_per_minute,
        )
        max_calls = _int_value(
            session,
            tr(language, "max_calls"),
            default=runtime.config.daily_call_budget,
        )
        max_gb = _float_value(session, tr(language, "max_gb"), default=30.0)

    job = DailyRangeJob()
    preflight = job.preflight(
        date_from=date_from,
        date_to=date_to,
        exchange=exchange,
        asset_types=asset_types,
        market=market,
        instrument_status=instrument_status,
        max_estimated_gb=max_gb,
        parallel=parallel,
        workers=workers,
        max_requests_per_minute=max_rpm,
        max_api_calls=max_calls,
        runtime=runtime,
        override_source="menu",
    )
    parameters = preflight.parameters
    mode_flag = "--parallel" if parameters["parallel"] else "--sequential"
    command = _command(
        "ingest",
        "daily-range",
        "--from",
        date_from,
        "--to",
        date_to,
        "--exchange",
        parameters["exchange"],
        "--asset-types",
        ",".join(asset_types),
        "--market",
        parameters["market"],
        "--instrument-status",
        instrument_status,
        mode_flag,
        "--workers",
        parameters["workers"],
        "--max-requests-per-minute",
        parameters["max_requests_per_minute"],
        "--max-api-calls",
        parameters["max_api_calls"],
        "--max-estimated-gb",
        parameters["max_estimated_gb"],
        "--execute",
        "--yes",
    )
    _confirm_and_run(
        session,
        language,
        preflight,
        command,
        lambda reporter: job.run(
            execute=True,
            runtime=runtime,
            reporter=reporter,
            override_source="menu",
            preflight=preflight,
        ),
    )


def _run_bulk_unmatched(session: PromptSession, language: Language) -> None:
    date_from = _date_value(session, tr(language, "date_from"))
    date_to = _date_value(session, tr(language, "date_to"))
    asset_types = ["stock", "etf", "fund", "index"]
    market = "US"
    limit = None
    if _advanced(session, language):
        market = _text(session, tr(language, "market"), default="US")
        limit = _optional_int(session, tr(language, "limit"))
    runtime = JobRuntime.from_env()
    job = BulkUnmatchedReconcileJob()
    preflight = job.preflight(
        date_from=date_from,
        date_to=date_to,
        market=market,
        asset_types=asset_types,
        limit=limit,
        runtime=runtime,
        override_source="menu",
    )
    summary = job.summary(
        date_from=date_from,
        date_to=date_to,
        market=market,
        runtime=runtime,
    )
    _show_preflight(
        preflight,
        _command(
            "research",
            "bulk-unmatched",
            "classify",
            "--from",
            date_from,
            "--to",
            date_to,
            "--market",
            market,
        ),
    )
    for row in summary:
        typer.echo(
            f"  status={row.classification_status} "
            f"asset_type={row.classified_asset_type or '-'} count={row.row_count}"
        )
    if not session.confirm(tr(language, "confirm_classify"), default=False):
        raise MenuCancelled
    classify_result = job.classify(
        date_from=date_from,
        date_to=date_to,
        market=market,
        limit=limit,
        runtime=runtime,
        override_source="menu",
    )
    _show_result(classify_result, language)
    route_preview = job.route(
        date_from=date_from,
        date_to=date_to,
        market=market,
        asset_types=asset_types,
        limit=limit,
        execute=False,
        runtime=runtime,
        override_source="menu",
    )
    route_command = _command(
        "ingest",
        "bulk-unmatched-route",
        "--from",
        date_from,
        "--to",
        date_to,
        "--asset-types",
        ",".join(asset_types),
        "--market",
        market,
        "--execute",
        "--yes",
    )
    typer.echo(f"\nEquivalent CLI: {route_command}")
    _show_result(route_preview, language)
    if not session.confirm(tr(language, "confirm_route"), default=False):
        raise MenuCancelled
    routed = job.route(
        date_from=date_from,
        date_to=date_to,
        market=market,
        asset_types=asset_types,
        limit=limit,
        execute=True,
        runtime=runtime,
        override_source="menu",
    )
    _show_result(routed, language)


def _confirm_and_run(
    session: PromptSession,
    language: Language,
    preflight: JobPreflight,
    command: str,
    runner: Callable[[TqdmProgressReporter], JobResult],
) -> None:
    _show_preflight(preflight, command)
    if not session.confirm(tr(language, "confirm"), default=False):
        raise MenuCancelled
    reporter = TqdmProgressReporter()
    try:
        result = runner(reporter)
    finally:
        reporter.close()
    _show_result(result, language)


def _show_preflight(preflight: JobPreflight, command: str) -> None:
    typer.echo("\nPreflight")
    typer.echo(f"  job={preflight.job}")
    typer.echo(f"  job_module=src/{preflight.job_module.replace('.', '/')}.py")
    typer.echo(f"  target_tables={','.join(preflight.target_tables)}")
    typer.echo(
        f"  work_units={preflight.work_units} estimated_api_calls={preflight.estimated_api_calls}"
    )
    if preflight.estimated_rows is not None:
        typer.echo(f"  estimated_rows={preflight.estimated_rows}")
    if preflight.estimated_gb is not None:
        typer.echo(f"  estimated_gb={preflight.estimated_gb:.2f}")
    for key, value in preflight.parameters.items():
        typer.echo(f"  {key}={value} source={preflight.parameter_sources.get(key, '-')}")
    for warning in preflight.warnings:
        typer.echo(f"  warning={warning}")
    typer.echo(f"Equivalent CLI: {command}")


def _show_result(result: JobResult, language: Language) -> None:
    typer.echo(f"\n{tr(language, 'completed')}: job={result.job} status={result.status}")
    typer.echo(
        f"  run_id={result.run_id or '-'} fetched={result.rows_fetched} "
        f"matched={result.rows_matched} inserted={result.rows_inserted} "
        f"unmatched={result.rows_unmatched} rejected={result.rows_rejected} "
        f"api_calls={result.api_calls}"
    )
    if result.missing_symbols:
        typer.echo(f"  missing_symbols={','.join(result.missing_symbols)}")
    for failure in result.failures[:10]:
        typer.echo(
            f"  failure unit={failure.unit} category={failure.category} message={failure.message}"
        )
    if len(result.failures) > 10:
        typer.echo(f"  ... {len(result.failures) - 10} more failure(s)")


def _advanced(session: PromptSession, language: Language) -> bool:
    answer = session.confirm(tr(language, "advanced"), default=False)
    if answer is None:
        raise MenuCancelled
    return answer


def _assets(session: PromptSession, language: Language, *, defaults: set[str]) -> list[str]:
    selected = session.checkbox(
        tr(language, "asset_types"),
        [("Stock", "stock"), ("ETF", "etf"), ("Fund", "fund")],
        defaults=defaults,
    )
    if not selected:
        raise MenuCancelled
    return selected


def _text(session: PromptSession, message: str, *, default: str = "") -> str:
    while True:
        value = session.text(message, default=default)
        if value is None:
            raise MenuCancelled
        normalized = value.strip()
        if normalized:
            return normalized
        typer.echo("value is required", err=True)


def _csv(value: str, *, allow_empty: bool = False) -> list[str]:
    values = [item.strip().upper() for item in value.split(",") if item.strip()]
    if not values and not allow_empty:
        raise ValueError("at least one symbol is required")
    return list(dict.fromkeys(values))


def _date_value(
    session: PromptSession,
    message: str,
    *,
    default: date | None = None,
    allow_blank: bool = False,
) -> date | None:
    default_text = default.isoformat() if default is not None else ""
    while True:
        raw = session.text(message, default=default_text)
        if raw is None:
            raise MenuCancelled
        value = raw.strip()
        if not value and allow_blank:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            typer.echo("date must be YYYY-MM-DD", err=True)


def _int_value(session: PromptSession, message: str, *, default: int) -> int:
    while True:
        raw = session.text(message, default=str(default))
        if raw is None:
            raise MenuCancelled
        try:
            value = int(raw)
        except ValueError:
            typer.echo("value must be an integer", err=True)
            continue
        if value > 0:
            return value
        typer.echo("value must be positive", err=True)


def _optional_int(session: PromptSession, message: str) -> int | None:
    while True:
        raw = session.text(message, default="")
        if raw is None:
            raise MenuCancelled
        if not raw.strip():
            return None
        try:
            value = int(raw)
        except ValueError:
            typer.echo("value must be an integer", err=True)
            continue
        if value > 0:
            return value
        typer.echo("value must be positive", err=True)


def _float_value(session: PromptSession, message: str, *, default: float) -> float:
    while True:
        raw = session.text(message, default=str(default))
        if raw is None:
            raise MenuCancelled
        try:
            value = float(raw)
        except ValueError:
            typer.echo("value must be numeric", err=True)
            continue
        if value > 0:
            return value
        typer.echo("value must be positive", err=True)


def _command(*parts: Any) -> str:
    return shlex.join(["poetry", "run", "j21", *(str(part) for part in parts)])


JOB_HANDLERS: dict[str, Callable[[PromptSession, Language], None]] = {
    "instruments": _run_instruments,
    "delisted_instruments": _run_delisted,
    "stock_daily": _run_stock_daily,
    "etf_daily": _run_etf_daily,
    "fund_daily": _run_fund_daily,
    "index_daily": _run_index_daily,
    "bulk_daily": _run_bulk_daily,
    "daily_range": _run_daily_range,
    "market_calendar": _run_calendar,
    "bulk_unmatched": _run_bulk_unmatched,
}
