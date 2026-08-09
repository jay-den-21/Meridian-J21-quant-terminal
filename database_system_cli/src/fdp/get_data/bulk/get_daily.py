"""Shared one-day EODHD Bulk EOD ingest job."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from fdp.assets import US_BULK_EOD_ASSET_TYPES
from fdp.get_data.contracts import (
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressReporter,
)
from fdp.get_data.runtime import JobRuntime
from fdp.get_data.historical.get_market_calendar import MarketCalendarJob
from fdp.get_data.bulk.readiness import NEW_YORK, latest_provider_ready_trade_date
from fdp.sources.eodhd.retry import WeightedApiBudget
from fdp.sources.eodhd.ingest.common import normalize_symbols
from fdp.storage.tables import market_calendar

EODHD_BULK_FULL_EXCHANGE_API_CALL_COST = 100
SUPPORTED_BULK_ASSET_TYPES = set(US_BULK_EOD_ASSET_TYPES)
DEFAULT_EXCHANGE = "US"
DEFAULT_MARKET = "US"
DEFAULT_ASSET_TYPES = US_BULK_EOD_ASSET_TYPES
DEFAULT_SYMBOLS: tuple[str, ...] = ()
DEFAULT_TRADE_DATE: date | None = None
DEFAULT_INSTRUMENT_STATUS = "active"
SUPPORTED_INSTRUMENT_STATUSES = {"active", "all"}


class BulkDailyJob:
    """Load one exchange/date Bulk EOD response and stage unmatched observations."""

    job_key = "ingest.daily"
    job_module = "fdp.get_data.bulk.get_daily"

    def preflight(
        self,
        *,
        exchange: str | None = None,
        trade_date: date | None = None,
        symbols: list[str] | None = None,
        asset_types: list[str] | None = None,
        market: str | None = None,
        instrument_status: str | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        parameters, sources = self._resolve(
            exchange=exchange,
            trade_date=trade_date,
            symbols=symbols,
            asset_types=asset_types,
            market=market,
            instrument_status=instrument_status,
            override_source=override_source,
        )
        symbol_filter = parameters["symbols"]
        estimated_api_calls = EODHD_BULK_FULL_EXCHANGE_API_CALL_COST + (
            len(symbol_filter) if symbol_filter else 0
        )
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=[
                *(f"{asset_type}_daily_price" for asset_type in parameters["asset_types"]),
                "system.bulk_unmatched_daily_price_observation",
            ],
            work_units=1,
            estimated_api_calls=estimated_api_calls,
            parameters=parameters,
            parameter_sources=sources,
            warnings=(
                ["trade_date is omitted; EODHD will return its last trading day"]
                if parameters["trade_date"] is None
                else []
            ),
        )

    def run(
        self,
        *,
        exchange: str | None = None,
        trade_date: date | None = None,
        symbols: list[str] | None = None,
        asset_types: list[str] | None = None,
        market: str | None = None,
        instrument_status: str | None = None,
        execute: bool = False,
        manual: bool = False,
        new_run: bool = False,
        max_requests_per_minute: int | None = None,
        max_api_calls: int | None = None,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        override_source: str = "python",
        preflight: JobPreflight | None = None,
    ) -> JobResult:
        active_runtime = runtime or JobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()
        active_preflight = preflight or self.preflight(
            exchange=exchange,
            trade_date=trade_date,
            symbols=symbols,
            asset_types=asset_types,
            market=market,
            instrument_status=instrument_status,
            override_source=override_source,
        )
        parameters = active_preflight.parameters
        trade_date_value = parameters["trade_date"]
        calendar_refresh_result: JobResult | None = None
        calendar_api_units = 0
        if trade_date_value is None:
            calendar_from, calendar_to = self._latest_calendar_window()
            with active_runtime.engine.connect() as connection:
                calendar_complete = self._calendar_window_complete(
                    connection,
                    date_from=calendar_from,
                    date_to=calendar_to,
                )
            if not calendar_complete and execute:
                invocation_limit = (
                    max_api_calls
                    if max_api_calls is not None
                    else active_runtime.config.daily_call_budget
                )
                minimum_remaining = (
                    EODHD_BULK_FULL_EXCHANGE_API_CALL_COST
                    + 1  # /user budget check
                    + 2  # active instruments + symbol changes
                    + int(parameters["instrument_status"] == "all")
                )
                if invocation_limit < minimum_remaining + 1:
                    raise ValueError(
                        "max-api-calls is too small for latest-date calendar refresh and "
                        f"Daily prerequisites: required_at_least={minimum_remaining + 1}"
                    )
                calendar_budget = WeightedApiBudget(invocation_limit)
                calendar_client = active_runtime.client(
                    active_reporter,
                    max_requests_per_minute=max_requests_per_minute,
                    api_budget=calendar_budget,
                )
                calendar_runtime = JobRuntime(
                    engine=active_runtime.engine,
                    config=active_runtime.config,
                    injected_client=calendar_client,
                )
                calendar_refresh_result = MarketCalendarJob().run(
                    date_from=calendar_from,
                    date_to=calendar_to,
                    market=str(parameters["market"]),
                    runtime=calendar_runtime,
                    reporter=active_reporter,
                    override_source="daily_prerequisite",
                )
                if calendar_refresh_result.status != "success":
                    raise RuntimeError(
                        "latest-date calendar prerequisite failed: "
                        f"{calendar_refresh_result.error_message or calendar_refresh_result.status}"
                    )
                calendar_api_units = calendar_budget.snapshot().consumed
                max_api_calls = invocation_limit - calendar_api_units
            elif not calendar_complete:
                estimated = (
                    EODHD_BULK_FULL_EXCHANGE_API_CALL_COST
                    + 1  # calendar
                    + 1  # /user budget check
                    + 2  # active instruments + symbol changes
                    + int(parameters["instrument_status"] == "all")
                )
                invocation_limit = (
                    max_api_calls
                    if max_api_calls is not None
                    else active_runtime.config.daily_call_budget
                )
                if estimated > invocation_limit:
                    raise ValueError(
                        f"estimated EODHD API calls {estimated} exceed max-api-calls "
                        f"{invocation_limit}"
                    )
                pending_preflight = replace(
                    active_preflight,
                    estimated_api_calls=estimated,
                    warnings=[
                        *active_preflight.warnings,
                        "latest trade date is unresolved until the missing market calendar "
                        "window is refreshed after --execute --yes",
                    ],
                )
                return JobResult(
                    job=self.job_key,
                    status="dry_run",
                    run_id=None,
                    parameters=parameters,
                    parameter_sources=active_preflight.parameter_sources,
                    work_units_total=1,
                    preflight=pending_preflight,
                )
            with active_runtime.engine.connect() as connection:
                trade_date_value = latest_provider_ready_trade_date(
                    connection,
                    asset_types=parameters["asset_types"],
                )

        from fdp.get_data.bulk.get_daily_range import DailyRangeJob

        result = DailyRangeJob().run(
            execute=execute,
            manual=manual,
            new_run=new_run,
            date_from=trade_date_value,
            date_to=trade_date_value,
            exchange=parameters["exchange"],
            asset_types=parameters["asset_types"],
            market=parameters["market"],
            instrument_status=parameters["instrument_status"],
            symbols=parameters["symbols"],
            parallel=False,
            workers=1,
            max_requests_per_minute=max_requests_per_minute,
            max_api_calls=max_api_calls,
            runtime=active_runtime,
            reporter=active_reporter,
            override_source=override_source,
        )
        resolved_parameters = dict(result.parameters)
        resolved_parameters["trade_date"] = trade_date_value
        resolved_parameters.pop("date_from", None)
        resolved_parameters.pop("date_to", None)
        metrics = dict(result.metrics)
        if calendar_refresh_result is not None:
            metrics["latest_calendar_prerequisite"] = {
                "run_id": calendar_refresh_result.run_id,
                "api_calls": calendar_refresh_result.api_calls,
                "api_units": calendar_api_units,
            }
            metrics["api_units_consumed"] = int(
                metrics.get("api_units_consumed", 0)
            ) + calendar_api_units
            metrics["task_api_units_consumed"] = int(
                metrics.get("task_api_units_consumed", 0)
            ) + calendar_api_units
        resolved_preflight = result.preflight
        if resolved_preflight is not None:
            resolved_preflight = replace(
                resolved_preflight,
                job=self.job_key,
                job_module=self.job_module,
                estimated_api_calls=(
                    resolved_preflight.estimated_api_calls + calendar_api_units
                ),
                parameters=resolved_parameters,
            )
        return replace(
            result,
            job=self.job_key,
            parameters=resolved_parameters,
            metrics=metrics,
            api_calls=result.api_calls
            + (calendar_refresh_result.api_calls if calendar_refresh_result else 0),
            preflight=resolved_preflight,
        )

    @staticmethod
    def _latest_calendar_window() -> tuple[date, date]:
        current = datetime.now(UTC).astimezone(NEW_YORK).date()
        return current - timedelta(days=14), current

    @staticmethod
    def _calendar_window_complete(
        connection: object,
        *,
        date_from: date,
        date_to: date,
    ) -> bool:
        loaded = int(
            connection.execute(
                select(func.count())
                .select_from(market_calendar)
                .where(
                    market_calendar.c.calendar_date >= date_from,
                    market_calendar.c.calendar_date <= date_to,
                )
            ).scalar_one()
        )
        return loaded == (date_to - date_from).days + 1

    @staticmethod
    def _resolve(
        *,
        exchange: str | None,
        trade_date: date | None,
        symbols: list[str] | None,
        asset_types: list[str] | None,
        market: str | None,
        instrument_status: str | None,
        override_source: str,
    ) -> tuple[dict[str, object], dict[str, str]]:
        resolved_assets = [value.lower() for value in (asset_types or DEFAULT_ASSET_TYPES)]
        unsupported = set(resolved_assets) - SUPPORTED_BULK_ASSET_TYPES
        if unsupported:
            raise ValueError(f"unsupported bulk asset type(s): {', '.join(sorted(unsupported))}")
        resolved_status = (instrument_status or DEFAULT_INSTRUMENT_STATUS).lower()
        if resolved_status not in SUPPORTED_INSTRUMENT_STATUSES:
            raise ValueError("instrument_status must be active or all")
        normalized_symbols = normalize_symbols(symbols or list(DEFAULT_SYMBOLS))
        parameters = {
            "exchange": (exchange or DEFAULT_EXCHANGE).upper(),
            "trade_date": trade_date if trade_date is not None else DEFAULT_TRADE_DATE,
            "symbols": normalized_symbols,
            "asset_types": resolved_assets,
            "market": (market or DEFAULT_MARKET).upper(),
            "instrument_status": resolved_status,
            "source": "eodhd",
        }
        return parameters, {
            "exchange": override_source if exchange is not None else "job_default",
            "trade_date": override_source if trade_date is not None else "job_default",
            "symbols": override_source if symbols is not None else "job_default",
            "asset_types": override_source if asset_types is not None else "job_default",
            "market": override_source if market is not None else "job_default",
            "instrument_status": (
                override_source if instrument_status is not None else "job_default"
            ),
            "source": "job_default",
        }
