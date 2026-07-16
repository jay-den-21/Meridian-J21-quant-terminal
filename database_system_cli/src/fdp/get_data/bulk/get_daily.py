"""Shared one-day EODHD Bulk EOD ingest job."""

from __future__ import annotations

from datetime import date

from fdp.assets import US_BULK_EOD_ASSET_TYPES
from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
)
from fdp.get_data.runtime import JobRuntime
from fdp.sources.eodhd.ingest import load_bulk_daily_prices
from fdp.sources.eodhd.ingest.common import normalize_symbols
from fdp.storage.schema import ensure_runtime_schemas

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
        active_reporter.on_event(ProgressEvent("start", self.job_key, 0, 1))
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            result = load_bulk_daily_prices(
                connection,
                active_runtime.client(active_reporter),
                exchange=parameters["exchange"],
                trade_date=parameters["trade_date"],
                symbols=parameters["symbols"] or None,
                market=parameters["market"],
                asset_types=parameters["asset_types"],
                instrument_status=parameters["instrument_status"],
            )
        failed = 1 if result.status == "failed" else 0
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                self.job_key,
                1,
                1,
                message=result.status,
                counters={
                    "fetched": result.rows_fetched,
                    "inserted": result.rows_inserted,
                    "unmatched": result.unmatched_rows,
                    "shadowed": result.shadowed_rows,
                    "rejected": result.rows_rejected,
                    "failed": failed,
                    "api_calls": result.api_calls,
                },
            )
        )
        failures = (
            [
                JobFailure(
                    str(parameters["trade_date"] or "latest"),
                    "request",
                    result.error_message or result.status,
                )
            ]
            if failed
            else []
        )
        return JobResult(
            job=self.job_key,
            status=result.status,
            run_id=result.run_id,
            parameters=parameters,
            parameter_sources=active_preflight.parameter_sources,
            rows_fetched=result.rows_fetched,
            rows_matched=result.rows_matched,
            rows_inserted=result.rows_inserted,
            rows_rejected=result.rows_rejected,
            rows_unmatched=result.unmatched_rows,
            api_calls=result.api_calls,
            work_units_total=1,
            work_units_completed=1,
            work_units_failed=failed,
            failures=failures,
            metrics={"rows_shadowed": result.shadowed_rows},
            error_message=result.error_message,
            preflight=active_preflight,
        )

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
