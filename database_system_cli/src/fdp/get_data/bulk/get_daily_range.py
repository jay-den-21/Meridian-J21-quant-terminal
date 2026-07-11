"""Guarded multi-day EODHD Bulk EOD ingest job."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

from sqlalchemy import func, select

from fdp.get_data.bulk.get_daily import (
    DEFAULT_ASSET_TYPES,
    DEFAULT_EXCHANGE,
    DEFAULT_INSTRUMENT_STATUS,
    DEFAULT_MARKET,
    EODHD_BULK_FULL_EXCHANGE_API_CALL_COST,
    SUPPORTED_BULK_ASSET_TYPES,
    SUPPORTED_INSTRUMENT_STATUSES,
)
from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
    resolved_value,
)
from fdp.get_data.historical.base import (
    DEFAULT_MAX_CONSECUTIVE_GLOBAL_FAILURES,
    FATAL_HTTP_STATUS_CODES,
    GLOBAL_TRANSIENT_STATUS_CODES,
)
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.ingest import BulkDailyPriceLoadResult, load_bulk_daily_prices
from fdp.sources.eodhd.identity import DatedInstrumentIdentityResolver
from fdp.sources.eodhd.retry import WeightedApiBudget
from fdp.storage.schema import ensure_runtime_schemas
from fdp.storage.tables import instrument, market_calendar

DEFAULT_DATE_FROM: date | None = None
DEFAULT_DATE_TO: date | None = None
DEFAULT_BYTES_PER_ROW = 600
DEFAULT_MAX_ESTIMATED_GB = 30.0


class DailyRangeJob:
    """Estimate and optionally execute one full-exchange Bulk EOD call per trading day."""

    job_key = "ingest.daily_range"
    job_module = "fdp.get_data.bulk.get_daily_range"

    def preflight(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        exchange: str | None = None,
        asset_types: list[str] | None = None,
        market: str | None = None,
        instrument_status: str | None = None,
        bytes_per_row: int | None = None,
        max_estimated_gb: float | None = None,
        parallel: bool | None = None,
        workers: int | None = None,
        max_requests_per_minute: int | None = None,
        max_api_calls: int | None = None,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        active_runtime = runtime or JobRuntime.from_env()
        parameters, sources = self._resolve(
            date_from=date_from,
            date_to=date_to,
            exchange=exchange,
            asset_types=asset_types,
            market=market,
            instrument_status=instrument_status,
            bytes_per_row=bytes_per_row,
            max_estimated_gb=max_estimated_gb,
            parallel=parallel,
            workers=workers,
            max_requests_per_minute=max_requests_per_minute,
            max_api_calls=max_api_calls,
            runtime=active_runtime,
            override_source=override_source,
        )
        with active_runtime.engine.connect() as connection:
            self._ensure_calendar_coverage(
                connection,
                date_from=parameters["date_from"],
                date_to=parameters["date_to"],
            )
            trade_dates = self._load_trading_dates(
                connection,
                date_from=parameters["date_from"],
                date_to=parameters["date_to"],
            )
            scoped_instruments = self._count_instruments(
                connection,
                market=parameters["market"],
                asset_types=parameters["asset_types"],
                instrument_status=parameters["instrument_status"],
            )
        if not trade_dates:
            raise ValueError("no trading days found in market_calendar for this range")
        estimated_rows = len(trade_dates) * scoped_instruments
        estimated_gb = estimated_rows * parameters["bytes_per_row"] / (1024**3)
        estimated_api_calls = len(trade_dates) * EODHD_BULK_FULL_EXCHANGE_API_CALL_COST
        if estimated_gb > parameters["max_estimated_gb"]:
            raise ValueError(
                f"estimated storage {estimated_gb:.2f}GB exceeds max-estimated-gb "
                f"{parameters['max_estimated_gb']:.2f}GB"
            )
        if estimated_api_calls > parameters["max_api_calls"]:
            raise ValueError(
                f"estimated EODHD API calls {estimated_api_calls} exceed max-api-calls "
                f"{parameters['max_api_calls']}; split the range or raise the budget explicitly"
            )
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=[
                *(f"{asset_type}_daily_price" for asset_type in parameters["asset_types"]),
                "system.bulk_unmatched_daily_price_observation",
            ],
            work_units=len(trade_dates),
            estimated_api_calls=estimated_api_calls,
            estimated_rows=estimated_rows,
            estimated_gb=estimated_gb,
            parameters=parameters,
            parameter_sources=sources,
        )

    def run(
        self,
        *,
        execute: bool = False,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        preflight: JobPreflight | None = None,
        override_source: str = "python",
        **options: Any,
    ) -> JobResult:
        active_runtime = runtime or JobRuntime.from_env()
        active_preflight = preflight or self.preflight(
            runtime=active_runtime,
            override_source=override_source,
            **options,
        )
        parameters = active_preflight.parameters
        if not execute:
            return JobResult(
                job=self.job_key,
                status="dry_run",
                run_id=None,
                parameters=parameters,
                parameter_sources=active_preflight.parameter_sources,
                work_units_total=active_preflight.work_units,
                preflight=active_preflight,
            )

        active_reporter = reporter or NullProgressReporter()
        with active_runtime.engine.connect() as connection:
            trade_dates = self._load_trading_dates(
                connection,
                date_from=parameters["date_from"],
                date_to=parameters["date_to"],
            )
            identity_resolver = DatedInstrumentIdentityResolver.from_connection(
                connection,
                market=parameters["market"],
                asset_types=parameters["asset_types"],
                instrument_status=parameters["instrument_status"],
            )
        api_budget = WeightedApiBudget(parameters["max_api_calls"])
        client = active_runtime.client(
            active_reporter,
            max_requests_per_minute=parameters["max_requests_per_minute"],
            api_budget=api_budget,
        )
        active_reporter.on_event(
            ProgressEvent("start", self.job_key, 0, len(trade_dates), message="daily range started")
        )
        results, failures, cancelled = self._execute_dates(
            active_runtime,
            client,
            trade_dates=trade_dates,
            exchange=parameters["exchange"],
            market=parameters["market"],
            asset_types=parameters["asset_types"],
            instrument_status=parameters["instrument_status"],
            identity_resolver=identity_resolver,
            parallel=parameters["parallel"],
            workers=parameters["workers"],
            reporter=active_reporter,
        )
        totals = self._totals(results)
        budget_snapshot = api_budget.snapshot()
        completed = len(results) + len(
            [failure for failure in failures if failure.category == "exception"]
        )
        failed_days = len(failures)
        partial_days = sum(result.status == "partial_failed" for result in results)
        if cancelled:
            status = "cancelled"
        elif failed_days and not any(result.status != "failed" for result in results):
            status = "failed"
        elif failed_days or partial_days:
            status = "partial_failed"
        else:
            status = "success"
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                self.job_key,
                completed,
                len(trade_dates),
                message=status,
                counters={
                    **totals,
                    "failed": failed_days,
                    "api_calls": totals["api_calls"],
                    "api_units": budget_snapshot.consumed,
                },
            )
        )
        error_message = (
            "; ".join(f"{failure.unit}: {failure.message}" for failure in failures) or None
        )
        return JobResult(
            job=self.job_key,
            status=status,
            run_id=None,
            parameters=parameters,
            parameter_sources=active_preflight.parameter_sources,
            rows_fetched=totals["rows_fetched"],
            rows_matched=totals["rows_matched"],
            rows_inserted=totals["rows_inserted"],
            rows_rejected=totals["rows_rejected"],
            rows_unmatched=totals["rows_unmatched"],
            api_calls=totals["api_calls"],
            work_units_total=len(trade_dates),
            work_units_completed=completed,
            work_units_failed=failed_days,
            failures=failures,
            metrics={
                "api_units_limit": budget_snapshot.limit,
                "api_units_consumed": budget_snapshot.consumed,
                "api_units_remaining": budget_snapshot.remaining,
            },
            error_message=error_message,
            preflight=active_preflight,
        )

    def _execute_dates(
        self,
        runtime: JobRuntime,
        client: Any,
        *,
        trade_dates: list[date],
        exchange: str,
        market: str,
        asset_types: list[str],
        instrument_status: str,
        identity_resolver: DatedInstrumentIdentityResolver,
        parallel: bool,
        workers: int,
        reporter: ProgressReporter,
    ) -> tuple[list[BulkDailyPriceLoadResult], list[JobFailure], bool]:
        results: list[BulkDailyPriceLoadResult] = []
        failures: list[JobFailure] = []
        completed = 0
        consecutive_global_failures = 0
        cancelled = False

        def record(result: BulkDailyPriceLoadResult, trade_date: date) -> bool:
            nonlocal completed, consecutive_global_failures
            results.append(result)
            completed += 1
            if result.status == "failed":
                failures.append(
                    JobFailure(
                        trade_date.isoformat(),
                        "request",
                        result.error_message or result.status,
                    )
                )
            counters = self._totals(results)
            reporter.on_event(
                ProgressEvent(
                    "unit_failed" if result.status == "failed" else "unit_completed",
                    self.job_key,
                    completed,
                    len(trade_dates),
                    unit=trade_date.isoformat(),
                    message=result.status,
                    counters={**counters, "failed": len(failures)},
                )
            )
            if result.status_code in FATAL_HTTP_STATUS_CODES:
                return True
            if result.status == "failed" and (
                result.status_code is None or result.status_code in GLOBAL_TRANSIENT_STATUS_CODES
            ):
                consecutive_global_failures += 1
                return consecutive_global_failures >= DEFAULT_MAX_CONSECUTIVE_GLOBAL_FAILURES
            consecutive_global_failures = 0
            return False

        if parallel and workers > 1:
            executor = ThreadPoolExecutor(max_workers=workers)
            futures: dict[Future[BulkDailyPriceLoadResult], date] = {
                executor.submit(
                    self._run_one_day,
                    runtime,
                    client,
                    trade_date=trade_date,
                    exchange=exchange,
                    market=market,
                    asset_types=asset_types,
                    instrument_status=instrument_status,
                    identity_resolver=identity_resolver,
                ): trade_date
                for trade_date in trade_dates
            }
            try:
                stop_requested = False
                for future in as_completed(futures):
                    if future.cancelled():
                        continue
                    trade_date = futures[future]
                    try:
                        should_stop = record(future.result(), trade_date)
                    except Exception as exc:
                        completed += 1
                        failures.append(JobFailure(trade_date.isoformat(), "exception", str(exc)))
                        reporter.on_event(
                            ProgressEvent(
                                "unit_failed",
                                self.job_key,
                                completed,
                                len(trade_dates),
                                unit=trade_date.isoformat(),
                                message=str(exc),
                                counters={"failed": len(failures)},
                            )
                        )
                        should_stop = True
                    if should_stop and not stop_requested:
                        stop_requested = True
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
            except KeyboardInterrupt:
                cancelled = True
                for pending in futures:
                    pending.cancel()
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
            return results, failures, cancelled

        try:
            for trade_date in trade_dates:
                try:
                    result = self._run_one_day(
                        runtime,
                        client,
                        trade_date=trade_date,
                        exchange=exchange,
                        market=market,
                        asset_types=asset_types,
                        instrument_status=instrument_status,
                        identity_resolver=identity_resolver,
                    )
                except Exception as exc:
                    completed += 1
                    failures.append(JobFailure(trade_date.isoformat(), "exception", str(exc)))
                    reporter.on_event(
                        ProgressEvent(
                            "unit_failed",
                            self.job_key,
                            completed,
                            len(trade_dates),
                            unit=trade_date.isoformat(),
                            message=str(exc),
                            counters={"failed": len(failures)},
                        )
                    )
                    break
                if record(result, trade_date):
                    break
        except KeyboardInterrupt:
            cancelled = True
        return results, failures, cancelled

    @staticmethod
    def _run_one_day(
        runtime: JobRuntime,
        client: Any,
        *,
        trade_date: date,
        exchange: str,
        market: str,
        asset_types: list[str],
        instrument_status: str,
        identity_resolver: DatedInstrumentIdentityResolver,
    ) -> BulkDailyPriceLoadResult:
        with runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            return load_bulk_daily_prices(
                connection,
                client,
                exchange=exchange,
                trade_date=trade_date,
                market=market,
                asset_types=asset_types,
                instrument_status=instrument_status,
                identity_resolver=identity_resolver,
            )

    @staticmethod
    def _totals(results: list[BulkDailyPriceLoadResult]) -> dict[str, int]:
        return {
            "rows_fetched": sum(result.rows_fetched for result in results),
            "rows_matched": sum(result.rows_matched for result in results),
            "rows_inserted": sum(result.rows_inserted for result in results),
            "rows_rejected": sum(result.rows_rejected for result in results),
            "rows_unmatched": sum(result.unmatched_rows for result in results),
            "api_calls": sum(result.api_calls for result in results),
        }

    @staticmethod
    def _resolve(
        *,
        date_from: date | None,
        date_to: date | None,
        exchange: str | None,
        asset_types: list[str] | None,
        market: str | None,
        instrument_status: str | None,
        bytes_per_row: int | None,
        max_estimated_gb: float | None,
        parallel: bool | None,
        workers: int | None,
        max_requests_per_minute: int | None,
        max_api_calls: int | None,
        runtime: JobRuntime,
        override_source: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        resolved_from, from_source = resolved_value(
            date_from,
            DEFAULT_DATE_FROM,
            name="date_from",
            explicit_source=override_source,
        )
        resolved_to, to_source = resolved_value(
            date_to,
            DEFAULT_DATE_TO,
            name="date_to",
            explicit_source=override_source,
        )
        if resolved_to < resolved_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        resolved_assets = [value.lower() for value in (asset_types or DEFAULT_ASSET_TYPES)]
        unsupported = set(resolved_assets) - SUPPORTED_BULK_ASSET_TYPES
        if unsupported:
            raise ValueError(f"unsupported bulk asset type(s): {', '.join(sorted(unsupported))}")
        resolved_status = (instrument_status or DEFAULT_INSTRUMENT_STATUS).lower()
        if resolved_status not in SUPPORTED_INSTRUMENT_STATUSES:
            raise ValueError("instrument_status must be active or all")
        resolved_parallel = (
            runtime.config.daily_range_parallel_enabled if parallel is None else parallel
        )
        resolved_workers = (
            workers if workers is not None else runtime.config.daily_range_max_workers
        )
        if not resolved_parallel:
            resolved_workers = 1
        values = {
            "date_from": resolved_from,
            "date_to": resolved_to,
            "exchange": (exchange or DEFAULT_EXCHANGE).upper(),
            "asset_types": resolved_assets,
            "market": (market or DEFAULT_MARKET).upper(),
            "instrument_status": resolved_status,
            "bytes_per_row": (
                bytes_per_row if bytes_per_row is not None else DEFAULT_BYTES_PER_ROW
            ),
            "max_estimated_gb": (
                max_estimated_gb if max_estimated_gb is not None else DEFAULT_MAX_ESTIMATED_GB
            ),
            "parallel": resolved_parallel,
            "workers": resolved_workers,
            "max_requests_per_minute": (
                max_requests_per_minute
                if max_requests_per_minute is not None
                else runtime.config.max_requests_per_minute
            ),
            "max_api_calls": (
                max_api_calls if max_api_calls is not None else runtime.config.daily_call_budget
            ),
            "source": "eodhd",
        }
        if values["bytes_per_row"] <= 0 or values["max_estimated_gb"] <= 0:
            raise ValueError("storage estimate controls must be positive")
        if values["workers"] <= 0 or values["max_requests_per_minute"] <= 0:
            raise ValueError("workers and max_requests_per_minute must be positive")
        if values["max_requests_per_minute"] > 1_000:
            raise ValueError("max_requests_per_minute must be less than or equal to 1000")
        if values["max_api_calls"] <= 0:
            raise ValueError("max_api_calls must be positive")
        sources = {
            "date_from": from_source,
            "date_to": to_source,
            "exchange": override_source if exchange is not None else "job_default",
            "asset_types": override_source if asset_types is not None else "job_default",
            "market": override_source if market is not None else "job_default",
            "instrument_status": (
                override_source if instrument_status is not None else "job_default"
            ),
            "bytes_per_row": override_source if bytes_per_row is not None else "job_default",
            "max_estimated_gb": override_source if max_estimated_gb is not None else "job_default",
            "parallel": override_source if parallel is not None else "runtime_config",
            "workers": override_source if workers is not None else "runtime_config",
            "max_requests_per_minute": (
                override_source if max_requests_per_minute is not None else "runtime_config"
            ),
            "max_api_calls": override_source if max_api_calls is not None else "runtime_config",
            "source": "job_default",
        }
        return values, sources

    @staticmethod
    def _load_trading_dates(connection: Any, *, date_from: date, date_to: date) -> list[date]:
        return list(
            connection.execute(
                select(market_calendar.c.calendar_date)
                .where(
                    market_calendar.c.calendar_date >= date_from,
                    market_calendar.c.calendar_date <= date_to,
                    market_calendar.c.is_trading_day.is_(True),
                )
                .order_by(market_calendar.c.calendar_date)
            ).scalars()
        )

    @staticmethod
    def _ensure_calendar_coverage(connection: Any, *, date_from: date, date_to: date) -> None:
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
            raise ValueError(
                "market_calendar coverage is incomplete for this range: "
                f"loaded_days={loaded_days} expected_days={expected_days}; "
                "run calendar ingest before estimating or executing a large backfill"
            )

    @staticmethod
    def _count_instruments(
        connection: Any,
        *,
        market: str,
        asset_types: list[str],
        instrument_status: str,
    ) -> int:
        conditions = [
            instrument.c.provider == "EODHD",
            instrument.c.market == market,
            instrument.c.asset_type.in_(asset_types),
        ]
        if instrument_status == "active":
            conditions.append(instrument.c.is_active.is_(True))
        elif instrument_status != "all":
            raise ValueError("instrument_status must be active or all")
        return int(
            connection.execute(
                select(func.count())
                .select_from(instrument)
                .where(*conditions)
            ).scalar_one()
        )
