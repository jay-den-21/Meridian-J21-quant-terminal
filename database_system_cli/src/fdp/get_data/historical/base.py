"""Shared historical daily job orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from fdp.assets import HISTORICAL_EOD_ASSET_TYPES, US_BULK_EOD_ASSET_TYPES
from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
    resolved_value,
)
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.ingest import load_historical_daily_price_unit
from fdp.sources.eodhd.ingest.common import (
    InstrumentStatus,
    create_task_run,
    finish_task_run,
    load_active_instruments,
    normalize_symbols,
)
from fdp.storage.schema import ensure_runtime_schemas

FATAL_HTTP_STATUS_CODES = {401, 402, 403}
GLOBAL_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_MAX_CONSECUTIVE_GLOBAL_FAILURES = 3


@dataclass(frozen=True)
class ResolvedHistoricalOptions:
    symbols: list[str]
    date_from: date
    date_to: date
    market: str
    instrument_status: InstrumentStatus
    parameters: dict[str, Any]
    parameter_sources: dict[str, str]


class HistoricalDailyJob:
    """Shared stock/ETF/Fund/index historical EOD job used by all entrypoints."""

    job_key = "ingest.history"
    job_module = "fdp.get_data.historical.base"
    job_name = "eodhd_historical_daily_price"

    def __init__(
        self,
        *,
        asset_types: tuple[str, ...] = US_BULK_EOD_ASSET_TYPES,
        default_symbols: tuple[str, ...] = (),
        default_date_from: date | None = None,
        default_date_to: date | None = None,
        default_market: str = "US",
        default_instrument_status: InstrumentStatus = "active",
        job_module: str | None = None,
    ) -> None:
        unsupported = set(asset_types) - set(HISTORICAL_EOD_ASSET_TYPES)
        if unsupported:
            raise ValueError(
                f"unsupported historical asset type(s): {', '.join(sorted(unsupported))}"
            )
        self.asset_types = asset_types
        self.default_symbols = default_symbols
        self.default_date_from = default_date_from
        self.default_date_to = default_date_to
        self.default_market = default_market
        self.default_instrument_status = default_instrument_status
        if job_module is not None:
            self.job_module = job_module

    @property
    def target_tables(self) -> list[str]:
        return [f"{asset_type}_daily_price" for asset_type in self.asset_types]

    def preflight(
        self,
        *,
        symbols: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        market: str | None = None,
        instrument_status: InstrumentStatus | None = None,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        active_runtime = runtime or JobRuntime.from_env()
        options = self._resolve_options(
            symbols=symbols,
            date_from=date_from,
            date_to=date_to,
            market=market,
            instrument_status=instrument_status,
            override_source=override_source,
        )
        with active_runtime.engine.connect() as connection:
            instruments = self._preflight_instruments(connection, options)
        missing_symbols = self._missing_symbols(options.symbols, instruments)
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=self.target_tables,
            work_units=len(options.symbols),
            estimated_api_calls=len(instruments),
            parameters=options.parameters,
            parameter_sources=options.parameter_sources,
            missing_symbols=missing_symbols,
            warnings=(
                [f"{len(missing_symbols)} symbol(s) do not match the instrument master"]
                if missing_symbols
                else []
            ),
        )

    def run(
        self,
        *,
        symbols: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        market: str | None = None,
        instrument_status: InstrumentStatus | None = None,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        override_source: str = "python",
        preflight: JobPreflight | None = None,
    ) -> JobResult:
        active_runtime = runtime or JobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()
        options = self._resolve_options(
            symbols=symbols,
            date_from=date_from,
            date_to=date_to,
            market=market,
            instrument_status=instrument_status,
            override_source=override_source,
        )
        active_preflight = preflight or self.preflight(
            symbols=options.symbols,
            date_from=options.date_from,
            date_to=options.date_to,
            market=options.market,
            instrument_status=options.instrument_status,
            runtime=active_runtime,
            override_source=override_source,
        )

        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            run_id, instruments = self._prepare_run(connection, options)

        missing_symbols = self._missing_symbols(options.symbols, instruments)
        failures = [
            JobFailure(
                unit=symbol,
                category="missing_instrument",
                message="symbol does not match the selected instrument status and asset type",
            )
            for symbol in missing_symbols
        ]
        completed = 0
        failed = 0
        rows_fetched = 0
        rows_inserted = 0
        rows_rejected = 0
        api_calls = 0
        consecutive_global_failures = 0
        cancelled = False
        fatal_stop = False

        active_reporter.on_event(
            ProgressEvent(
                kind="start",
                job=self.job_key,
                completed=completed,
                total=len(options.symbols),
                message="historical ingest started",
            )
        )
        for missing_symbol in missing_symbols:
            completed += 1
            failed += 1
            rows_rejected += 1
            active_reporter.on_event(
                ProgressEvent(
                    kind="unit_failed",
                    job=self.job_key,
                    completed=completed,
                    total=len(options.symbols),
                    unit=missing_symbol,
                    message="missing instrument",
                    counters={"failed": failed},
                )
            )

        client = None
        if instruments:
            try:
                client = active_runtime.client(active_reporter)
            except Exception as exc:
                fatal_stop = True
                failures.append(
                    JobFailure(
                        unit=self.job_key,
                        category="runtime_error",
                        message=str(exc),
                    )
                )
                active_reporter.on_event(
                    ProgressEvent(
                        kind="unit_failed",
                        job=self.job_key,
                        completed=completed,
                        total=len(options.symbols),
                        unit=self.job_key,
                        message=str(exc),
                        counters={"failed": failed, "api_calls": api_calls},
                    )
                )
        try:
            for instrument_row in instruments if not fatal_stop else []:
                provider_symbol = str(instrument_row["provider_symbol"])
                active_reporter.on_event(
                    ProgressEvent(
                        kind="unit_started",
                        job=self.job_key,
                        completed=completed,
                        total=len(options.symbols),
                        unit=provider_symbol,
                    )
                )
                try:
                    with active_runtime.engine.begin() as connection:
                        unit_result = load_historical_daily_price_unit(
                            connection,
                            client,
                            run_id=run_id,
                            instrument_row=instrument_row,
                            date_from=options.date_from,
                            date_to=options.date_to,
                        )
                except Exception as exc:
                    completed += 1
                    failed += 1
                    fatal_stop = True
                    failures.append(
                        JobFailure(
                            unit=provider_symbol,
                            category="runtime_error",
                            message=str(exc),
                        )
                    )
                    active_reporter.on_event(
                        ProgressEvent(
                            kind="unit_failed",
                            job=self.job_key,
                            completed=completed,
                            total=len(options.symbols),
                            unit=provider_symbol,
                            message=str(exc),
                            counters={
                                "fetched": rows_fetched,
                                "inserted": rows_inserted,
                                "rejected": rows_rejected,
                                "failed": failed,
                                "api_calls": api_calls,
                            },
                        )
                    )
                    break

                completed += 1
                rows_fetched += unit_result.rows_fetched
                rows_inserted += unit_result.rows_inserted
                rows_rejected += unit_result.rows_rejected
                api_calls += unit_result.api_calls

                if unit_result.status == "success":
                    consecutive_global_failures = 0
                    active_reporter.on_event(
                        ProgressEvent(
                            kind="unit_completed",
                            job=self.job_key,
                            completed=completed,
                            total=len(options.symbols),
                            unit=provider_symbol,
                            counters={
                                "fetched": rows_fetched,
                                "inserted": rows_inserted,
                                "rejected": rows_rejected,
                                "failed": failed,
                                "api_calls": api_calls,
                            },
                        )
                    )
                    continue

                failed += 1
                category = self._failure_category(unit_result.status_code)
                failures.append(
                    JobFailure(
                        unit=provider_symbol,
                        category=category,
                        message=unit_result.error_message or unit_result.status,
                    )
                )
                active_reporter.on_event(
                    ProgressEvent(
                        kind="unit_failed",
                        job=self.job_key,
                        completed=completed,
                        total=len(options.symbols),
                        unit=provider_symbol,
                        message=unit_result.error_message,
                        counters={
                            "fetched": rows_fetched,
                            "inserted": rows_inserted,
                            "rejected": rows_rejected,
                            "failed": failed,
                            "api_calls": api_calls,
                        },
                    )
                )
                if unit_result.status_code in FATAL_HTTP_STATUS_CODES:
                    fatal_stop = True
                    break
                if self._is_global_transient(unit_result.status_code):
                    consecutive_global_failures += 1
                    if consecutive_global_failures >= DEFAULT_MAX_CONSECUTIVE_GLOBAL_FAILURES:
                        fatal_stop = True
                        break
                else:
                    consecutive_global_failures = 0
        except KeyboardInterrupt:
            cancelled = True

        status = self._result_status(
            completed_successfully=completed - failed,
            failures=failures,
            cancelled=cancelled,
            fatal_stop=fatal_stop,
        )
        error_message = (
            "; ".join(f"{failure.unit}: {failure.message}" for failure in failures) or None
        )
        if cancelled:
            error_message = "cancelled by operator" + (
                f"; {error_message}" if error_message else ""
            )
        elif fatal_stop and error_message is None:
            error_message = "batch stopped after a fatal or repeated global failure"

        persisted_status = "failed" if status in {"failed", "cancelled"} else status
        if status == "cancelled" and completed - failed > 0:
            persisted_status = "partial_failed"
        with active_runtime.engine.begin() as connection:
            finish_task_run(
                connection,
                run_id=run_id,
                status=persisted_status,
                rows_fetched=rows_fetched,
                rows_inserted=rows_inserted,
                rows_updated=0,
                rows_rejected=rows_rejected,
                api_calls=api_calls,
                error_message=error_message,
            )

        active_reporter.on_event(
            ProgressEvent(
                kind="finish",
                job=self.job_key,
                completed=completed,
                total=len(options.symbols),
                message=status,
                counters={
                    "fetched": rows_fetched,
                    "inserted": rows_inserted,
                    "rejected": rows_rejected,
                    "failed": failed,
                    "api_calls": api_calls,
                },
            )
        )
        return JobResult(
            job=self.job_key,
            status=status,
            run_id=run_id,
            parameters=options.parameters,
            parameter_sources=options.parameter_sources,
            rows_fetched=rows_fetched,
            rows_matched=len(instruments),
            rows_inserted=rows_inserted,
            rows_rejected=rows_rejected,
            api_calls=api_calls,
            work_units_total=len(options.symbols),
            work_units_completed=completed,
            work_units_failed=failed,
            missing_symbols=missing_symbols,
            failures=failures,
            error_message=error_message,
            preflight=active_preflight,
        )

    def _resolve_options(
        self,
        *,
        symbols: list[str] | None,
        date_from: date | None,
        date_to: date | None,
        market: str | None,
        instrument_status: InstrumentStatus | None,
        override_source: str,
    ) -> ResolvedHistoricalOptions:
        resolved_symbols, symbols_source = resolved_value(
            symbols,
            list(self.default_symbols) if self.default_symbols else None,
            name="symbols",
            explicit_source=override_source,
        )
        normalized_symbols = normalize_symbols(list(resolved_symbols))
        if not normalized_symbols:
            raise ValueError("symbols must contain at least one symbol")
        resolved_from, from_source = resolved_value(
            date_from,
            self.default_date_from,
            name="date_from",
            explicit_source=override_source,
        )
        resolved_to, to_source = resolved_value(
            date_to,
            self.default_date_to,
            name="date_to",
            explicit_source=override_source,
        )
        if resolved_to < resolved_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        resolved_market, market_source = resolved_value(
            market,
            self.default_market,
            name="market",
            explicit_source=override_source,
        )
        resolved_status, status_source = resolved_value(
            instrument_status,
            self.default_instrument_status,
            name="instrument_status",
            explicit_source=override_source,
        )
        if resolved_status not in {"active", "inactive", "all"}:
            raise ValueError("instrument_status must be active, inactive, or all")

        parameters = {
            "symbols": normalized_symbols,
            "date_from": resolved_from,
            "date_to": resolved_to,
            "market": str(resolved_market).upper(),
            "instrument_status": resolved_status,
            "asset_types": list(self.asset_types),
        }
        sources = {
            "symbols": symbols_source,
            "date_from": from_source,
            "date_to": to_source,
            "market": market_source,
            "instrument_status": status_source,
            "asset_types": "job_default",
        }
        return ResolvedHistoricalOptions(
            symbols=normalized_symbols,
            date_from=resolved_from,
            date_to=resolved_to,
            market=parameters["market"],
            instrument_status=resolved_status,
            parameters=parameters,
            parameter_sources=sources,
        )

    def _preflight_instruments(
        self,
        connection: Any,
        options: ResolvedHistoricalOptions,
    ) -> list[dict[str, object]]:
        return load_active_instruments(
            connection,
            symbols=options.symbols,
            market=options.market,
            asset_types=list(self.asset_types),
            instrument_status=options.instrument_status,
        )

    def _prepare_run(
        self,
        connection: Any,
        options: ResolvedHistoricalOptions,
    ) -> tuple[int, list[dict[str, object]]]:
        run_id = create_task_run(
            connection,
            market=options.market,
            job_name=self.job_name,
            target_table=",".join(self.target_tables),
            date_from=options.date_from,
            date_to=options.date_to,
        )
        return run_id, self._preflight_instruments(connection, options)

    @staticmethod
    def _missing_symbols(
        requested_symbols: list[str],
        instruments: list[dict[str, object]],
    ) -> list[str]:
        found: set[str] = set()
        for row in instruments:
            found.add(str(row["symbol"]).upper())
            found.add(str(row["provider_symbol"]).upper())
        return [symbol for symbol in requested_symbols if symbol not in found]

    @staticmethod
    def _failure_category(status_code: int | None) -> str:
        if status_code in FATAL_HTTP_STATUS_CODES:
            return "authentication_or_entitlement"
        if status_code is None or status_code in GLOBAL_TRANSIENT_STATUS_CODES:
            return "global_transient"
        return "symbol_request"

    @staticmethod
    def _is_global_transient(status_code: int | None) -> bool:
        return status_code is None or status_code in GLOBAL_TRANSIENT_STATUS_CODES

    @staticmethod
    def _result_status(
        *,
        completed_successfully: int,
        failures: list[JobFailure],
        cancelled: bool,
        fatal_stop: bool,
    ) -> str:
        if cancelled:
            return "cancelled"
        if not failures and not fatal_stop:
            return "success"
        if completed_successfully > 0:
            return "partial_failed"
        return "failed"
