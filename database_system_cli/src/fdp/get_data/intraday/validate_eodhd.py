"""Fixture-testable EODHD 1-minute Parquet validation Job."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select

from fdp.get_data.api_budget import remote_api_capacity_metrics
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
from fdp.intraday import (
    ManifestConflictError,
    publish_intraday_artifact,
    resolve_intraday_data_root,
    write_intraday_parquet,
)
from fdp.intraday.models import IntradayBar
from fdp.intraday.sessions import NEW_YORK
from fdp.sources.eodhd.ingest.common import (
    create_task_run,
    finish_task_run,
    normalize_symbols,
    record_api_call,
)
from fdp.sources.eodhd.client import EodhdApiResponse
from fdp.sources.eodhd.intraday import parse_intraday_rows
from fdp.sources.eodhd.retry import EodhdApiBudgetExceeded, WeightedApiBudget
from fdp.storage.schema import ensure_runtime_schemas
from fdp.storage.tables import instrument

SOURCE = "eodhd"
INTERVAL = "1m"
ASSET_TYPE = "stock"
MAX_DAYS_PER_REQUEST = 120
UNITS_PER_REQUEST = 5
PUBLIC_MAX_API_UNITS = 200
DEFAULT_MAX_API_UNITS = 200
SUPPORTED_MARKET = "US"
SUPPORTED_EXCHANGES = {
    "AMEX",
    "NASDAQ",
    "NASDAQ CAPITAL MARKET",
    "NASDAQ GLOBAL MARKET",
    "NASDAQ GLOBAL SELECT MARKET",
    "NYSE",
    "NYSE AMERICAN",
    "NYSE ARCA",
    "NYSE MKT",
}


@dataclass(frozen=True)
class RequestWindow:
    date_from: date
    date_to: date

    @property
    def from_timestamp(self) -> int:
        local = datetime.combine(self.date_from, time.min, tzinfo=NEW_YORK)
        return int(local.astimezone(UTC).timestamp())

    @property
    def to_timestamp(self) -> int:
        local_exclusive = datetime.combine(
            self.date_to + timedelta(days=1),
            time.min,
            tzinfo=NEW_YORK,
        )
        return int(local_exclusive.astimezone(UTC).timestamp()) - 1

    @property
    def key(self) -> str:
        return f"{self.date_from.isoformat()}..{self.date_to.isoformat()}"


@dataclass(frozen=True)
class ResolvedIntradayOptions:
    symbols: list[str]
    date_from: date
    date_to: date
    source: str
    interval: str
    market: str
    max_api_units: int
    data_root: Path
    parameters: dict[str, Any]
    parameter_sources: dict[str, str]


class EodhdIntradayValidationJob:
    """Validate a small explicit EODHD US-stock sample into Parquet and manifest rows."""

    job_key = "validate.intraday"
    job_module = "fdp.get_data.intraday.validate_eodhd"
    job_name = "eodhd_intraday_1m_validation"

    def preflight(
        self,
        *,
        symbols: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        source: str | None = None,
        interval: str | None = None,
        market: str | None = None,
        max_api_units: int | None = None,
        data_root: str | Path | None = None,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        options = self._resolve_options(
            symbols=symbols,
            date_from=date_from,
            date_to=date_to,
            source=source,
            interval=interval,
            market=market,
            max_api_units=max_api_units,
            data_root=data_root,
            override_source=override_source,
        )
        active_runtime = runtime or JobRuntime.from_env()
        with active_runtime.engine.connect() as connection:
            instruments = self._load_instruments(connection, options)
        missing = self._missing_symbols(options.symbols, instruments)
        windows = intraday_request_windows(options.date_from, options.date_to)
        requests = len(instruments) * len(windows)
        estimated_units = 1 + requests * UNITS_PER_REQUEST if requests else 0
        if estimated_units > options.max_api_units:
            raise ValueError(
                f"estimated intraday API units {estimated_units} exceed max-api-calls "
                f"{options.max_api_units}"
            )
        warnings = [
            "validation-only: writes raw EODHD 1m Parquet and manifest rows; no production backfill"
        ]
        if missing:
            warnings.append(
                f"{len(missing)} symbol(s) are not active US stock instruments on NYSE/Nasdaq"
            )
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=["system.intraday_file_manifest"],
            work_units=requests,
            estimated_api_calls=estimated_units,
            parameters={
                **options.parameters,
                "request_windows": [window.key for window in windows],
                "matched_instruments": len(instruments),
                "instrument_fingerprint": self._instrument_fingerprint(instruments),
            },
            parameter_sources=options.parameter_sources,
            missing_symbols=missing,
            warnings=warnings,
        )

    def run(
        self,
        *,
        symbols: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        source: str | None = None,
        interval: str | None = None,
        market: str | None = None,
        max_api_units: int | None = None,
        data_root: str | Path | None = None,
        execute: bool = False,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        override_source: str = "python",
        preflight: JobPreflight | None = None,
    ) -> JobResult:
        options = self._resolve_options(
            symbols=symbols,
            date_from=date_from,
            date_to=date_to,
            source=source,
            interval=interval,
            market=market,
            max_api_units=max_api_units,
            data_root=data_root,
            override_source=override_source,
        )
        active_runtime = runtime or JobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()
        active_preflight = preflight or self.preflight(
            symbols=options.symbols,
            date_from=options.date_from,
            date_to=options.date_to,
            source=options.source,
            interval=options.interval,
            market=options.market,
            max_api_units=options.max_api_units,
            data_root=options.data_root,
            runtime=active_runtime,
            override_source=override_source,
        )
        self._validate_preflight(active_preflight, options)
        if not execute:
            return JobResult(
                job=self.job_key,
                status="dry_run",
                run_id=None,
                parameters=active_preflight.parameters,
                parameter_sources=active_preflight.parameter_sources,
                work_units_total=active_preflight.work_units,
                missing_symbols=active_preflight.missing_symbols,
                preflight=active_preflight,
            )

        # Validate again before constructing the API client or creating any files.
        resolve_intraday_data_root(options.data_root, create=False)
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            instruments = self._load_instruments(connection, options)
            self._validate_execution_scope(active_preflight, options, instruments)
            run_id = create_task_run(
                connection,
                market=options.market,
                job_name=self.job_name,
                target_table="intraday_file_manifest",
                target_schema="system",
                date_from=options.date_from,
                date_to=options.date_to,
            )

        failures = [
            JobFailure(symbol, "missing_instrument", "not an active NYSE/Nasdaq US stock")
            for symbol in self._missing_symbols(options.symbols, instruments)
        ]
        windows = intraday_request_windows(options.date_from, options.date_to)
        total_units = len(instruments) * len(windows)
        try:
            active_reporter.on_event(ProgressEvent("start", self.job_key, 0, total_units))
        except Exception as exc:
            with active_runtime.engine.begin() as connection:
                finish_task_run(
                    connection,
                    run_id=run_id,
                    status="failed",
                    rows_fetched=0,
                    rows_inserted=0,
                    rows_updated=0,
                    rows_rejected=0,
                    api_calls=0,
                    error_message=f"progress reporter failed: {exc}",
                )
            raise
        if not instruments:
            message = "; ".join(
                f"{failure.unit}: {failure.message}" for failure in failures
            ) or "no eligible instruments"
            with active_runtime.engine.begin() as connection:
                finish_task_run(
                    connection,
                    run_id=run_id,
                    status="failed",
                    rows_fetched=0,
                    rows_inserted=0,
                    rows_updated=0,
                    rows_rejected=0,
                    api_calls=0,
                    error_message=message,
                )
            active_reporter.on_event(
                ProgressEvent("finish", self.job_key, 0, 0, message="failed")
            )
            return JobResult(
                job=self.job_key,
                status="failed",
                run_id=run_id,
                parameters=active_preflight.parameters,
                parameter_sources=active_preflight.parameter_sources,
                missing_symbols=active_preflight.missing_symbols,
                failures=failures,
                error_message=message,
                preflight=active_preflight,
            )
        budget = WeightedApiBudget(options.max_api_units)
        rows_fetched = rows_accepted = rows_rejected = 0
        manifests_inserted = manifests_reused = 0
        files_created = 0
        completed = failed = http_requests = 0
        api_units = 0
        remote_metrics: dict[str, int | str] = {}
        unexpected_error: Exception | None = None
        active_provider_symbol: str | None = None
        active_window: RequestWindow | None = None

        try:
            client = active_runtime.client(active_reporter, api_budget=budget)
            if active_runtime.injected_client is client:
                client.api_budget = budget
                client.progress_callback = active_reporter.on_api_event
            user_response = client.get_user()
            http_requests += user_response.retry_count + 1
            with active_runtime.engine.begin() as connection:
                record_api_call(connection, run_id=run_id, response=user_response)
            remote_metrics = remote_api_capacity_metrics(
                user_response,
                required_units=total_units * UNITS_PER_REQUEST,
            )
            for instrument_row in instruments:
                for window in windows:
                    unit = f"{instrument_row['provider_symbol']}:{window.key}"
                    active_provider_symbol = str(instrument_row["provider_symbol"])
                    active_window = window
                    active_reporter.on_event(
                        ProgressEvent("unit_started", self.job_key, completed, total_units, unit=unit)
                    )
                    unit_event: ProgressEvent
                    try:
                        response = client.get_intraday(
                            str(instrument_row["provider_symbol"]),
                            from_timestamp=window.from_timestamp,
                            to_timestamp=window.to_timestamp,
                            interval=options.interval,
                        )
                        http_requests += response.retry_count + 1
                        with active_runtime.engine.begin() as connection:
                            record_api_call(
                                connection,
                                run_id=run_id,
                                response=response,
                                provider_symbol=str(instrument_row["provider_symbol"]),
                                date_from=window.date_from,
                                date_to=window.date_to,
                            )
                        if not response.success:
                            raise RuntimeError(response.error_message or "EODHD intraday request failed")
                        rows_fetched += response.rows_returned
                        parsed = parse_intraday_rows(
                            response.payload,
                            instrument_id=int(instrument_row["instrument_id"]),
                            provider_symbol=str(instrument_row["provider_symbol"]),
                        )
                        in_window = [
                            bar
                            for bar in parsed.accepted
                            if window.date_from <= bar.trade_date <= window.date_to
                            and options.date_from <= bar.trade_date <= options.date_to
                        ]
                        outside_count = len(parsed.accepted) - len(in_window)
                        rows_rejected += len(parsed.rejected) + outside_count
                        rows_accepted += len(in_window)
                        published = self._publish_grouped_bars(
                            active_runtime,
                            run_id=run_id,
                            bars=in_window,
                            data_root=options.data_root,
                        )
                        manifests_inserted += published["inserted"]
                        manifests_reused += published["reused"]
                        files_created += published["files_created"]
                        unit_problem = False
                        if not in_window:
                            unit_problem = True
                            failures.append(
                                JobFailure(
                                    unit,
                                    "no_data",
                                    "provider response contained no valid 1m bars in the requested "
                                    f"window; rejected={len(parsed.rejected)} "
                                    f"outside_window={outside_count}",
                                )
                            )
                            failed += 1
                        elif parsed.rejected or outside_count:
                            unit_problem = True
                            failures.append(
                                JobFailure(
                                    unit,
                                    "invalid_payload",
                                    f"rejected={len(parsed.rejected)} outside_window={outside_count}",
                                )
                            )
                            failed += 1
                        completed += 1
                        unit_event = ProgressEvent(
                            "unit_failed" if unit_problem else "unit_completed",
                            self.job_key,
                            completed,
                            total_units,
                            unit=unit,
                            message="validation issues retained" if unit_problem else None,
                            counters={
                                "bars": rows_accepted,
                                "manifests": manifests_inserted,
                                "rejected": rows_rejected,
                            },
                        )
                    except EodhdApiBudgetExceeded:
                        raise
                    except (ManifestConflictError, OSError, RuntimeError, TypeError, ValueError) as exc:
                        completed += 1
                        failed += 1
                        failures.append(JobFailure(unit, "validation", str(exc)))
                        unit_event = ProgressEvent(
                            "unit_failed",
                            self.job_key,
                            completed,
                            total_units,
                            unit=unit,
                            message=str(exc),
                        )
                    active_reporter.on_event(unit_event)
        except EodhdApiBudgetExceeded as exc:
            if exc.completed_attempts:
                exhausted_response = EodhdApiResponse(
                    endpoint=exc.endpoint or "/intraday/unknown",
                    status_code=exc.status_code,
                    success=False,
                    retry_count=exc.retry_count,
                    rows_returned=0,
                    duration_ms=exc.duration_ms,
                    payload=[],
                    error_message=exc.prior_error or str(exc),
                )
                http_requests += exc.completed_attempts
                try:
                    with active_runtime.engine.begin() as connection:
                        record_api_call(
                            connection,
                            run_id=run_id,
                            response=exhausted_response,
                            provider_symbol=active_provider_symbol,
                            date_from=active_window.date_from if active_window else None,
                            date_to=active_window.date_to if active_window else None,
                        )
                except Exception as audit_exc:
                    unexpected_error = audit_exc
                    failures.append(
                        JobFailure(
                            self.job_key,
                            "api_audit",
                            f"failed to retain completed API attempt: {audit_exc}",
                        )
                    )
            failures.append(JobFailure(self.job_key, "api_budget", str(exc)))
            failed += max(total_units - completed, 0)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            failures.append(JobFailure(self.job_key, "runtime", str(exc)))
            failed += max(total_units - completed, 0)
        except Exception as exc:
            unexpected_error = exc
            failures.append(JobFailure(self.job_key, "unexpected", str(exc)))
            failed += max(total_units - completed, 0)

        api_units = budget.snapshot().consumed
        status = (
            "failed"
            if unexpected_error is not None
            else self._status(
                total_units=total_units,
                completed=completed,
                failures=failures,
                rows_accepted=rows_accepted,
            )
        )
        error_message = "; ".join(
            f"{failure.unit}: {failure.message}" for failure in failures[:20]
        ) or None
        with active_runtime.engine.begin() as connection:
            finish_task_run(
                connection,
                run_id=run_id,
                status=status,
                rows_fetched=rows_fetched,
                rows_inserted=manifests_inserted,
                rows_updated=0,
                rows_rejected=rows_rejected,
                api_calls=http_requests,
                error_message=error_message,
            )
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                self.job_key,
                completed,
                total_units,
                message=status,
                counters={
                    "bars": rows_accepted,
                    "manifests": manifests_inserted,
                    "rejected": rows_rejected,
                    "api_units": api_units,
                },
            )
        )
        if unexpected_error is not None:
            raise unexpected_error
        return JobResult(
            job=self.job_key,
            status=status,
            run_id=run_id,
            parameters=active_preflight.parameters,
            parameter_sources=active_preflight.parameter_sources,
            rows_fetched=rows_fetched,
            rows_matched=rows_accepted,
            rows_inserted=manifests_inserted,
            rows_rejected=rows_rejected,
            api_calls=http_requests,
            work_units_total=total_units,
            work_units_completed=completed,
            work_units_failed=failed,
            missing_symbols=active_preflight.missing_symbols,
            failures=failures,
            metrics={
                "api_units_consumed": api_units,
                "manifests_inserted": manifests_inserted,
                "manifests_reused": manifests_reused,
                "files_created": files_created,
                "data_root": str(options.data_root),
                **remote_metrics,
            },
            error_message=error_message,
            preflight=active_preflight,
        )

    @staticmethod
    def _publish_grouped_bars(
        runtime: JobRuntime,
        *,
        run_id: int,
        bars: list[IntradayBar],
        data_root: Path,
    ) -> dict[str, int]:
        grouped: dict[date, list[IntradayBar]] = defaultdict(list)
        for bar in bars:
            grouped[bar.trade_date].append(bar)
        totals = {"inserted": 0, "reused": 0, "files_created": 0}
        for trade_date_value in sorted(grouped):
            artifact = write_intraday_parquet(grouped[trade_date_value], root=data_root)
            result = publish_intraday_artifact(
                runtime.engine,
                run_id=run_id,
                artifact=artifact,
                data_root=data_root,
            )
            totals[result.status] += 1
            totals["files_created"] += int(artifact.created)
        return totals

    @staticmethod
    def _status(
        *,
        total_units: int,
        completed: int,
        failures: list[JobFailure],
        rows_accepted: int,
    ) -> str:
        if not failures and completed == total_units:
            return "success"
        if rows_accepted:
            return "partial_failed"
        return "failed"

    @staticmethod
    def _load_instruments(connection: Any, options: ResolvedIntradayOptions) -> list[dict[str, object]]:
        result = connection.execute(
            select(
                instrument.c.instrument_id,
                instrument.c.symbol,
                instrument.c.provider_symbol,
                instrument.c.exchange,
            ).where(
                instrument.c.market == options.market,
                instrument.c.provider == "EODHD",
                instrument.c.asset_type == ASSET_TYPE,
                instrument.c.is_active.is_(True),
                instrument.c.exchange.in_(SUPPORTED_EXCHANGES),
                or_(
                    instrument.c.symbol.in_(options.symbols),
                    instrument.c.provider_symbol.in_(options.symbols),
                ),
            )
        )
        rows = [dict(row) for row in result.mappings()]
        by_symbol: dict[str, dict[str, object]] = {}
        for row in rows:
            by_symbol[str(row["symbol"]).upper()] = row
            by_symbol[str(row["provider_symbol"]).upper()] = row
        ordered: list[dict[str, object]] = []
        seen: set[int] = set()
        for symbol in options.symbols:
            row = by_symbol.get(symbol)
            if row is not None and int(row["instrument_id"]) not in seen:
                ordered.append(row)
                seen.add(int(row["instrument_id"]))
        return ordered

    @staticmethod
    def _missing_symbols(
        requested: list[str],
        instruments: list[dict[str, object]],
    ) -> list[str]:
        found = {
            value
            for row in instruments
            for value in (
                str(row["symbol"]).upper(),
                str(row["provider_symbol"]).upper(),
            )
        }
        return [symbol for symbol in requested if symbol not in found]

    def _validate_preflight(
        self,
        preflight: JobPreflight,
        options: ResolvedIntradayOptions,
    ) -> None:
        if preflight.job != self.job_key or preflight.job_module != self.job_module:
            raise ValueError("preflight job identity does not match intraday validation")
        if preflight.target_tables != ["system.intraday_file_manifest"]:
            raise ValueError("preflight target table does not match intraday validation")
        expected = {
            "symbols": options.symbols,
            "date_from": options.date_from,
            "date_to": options.date_to,
            "source": options.source,
            "interval": options.interval,
            "market": options.market,
            "max_api_units": options.max_api_units,
            "data_root": str(options.data_root),
        }
        for key, value in expected.items():
            if preflight.parameters.get(key) != value:
                raise ValueError(f"preflight {key} does not match the run invocation")

    @staticmethod
    def _validate_execution_scope(
        preflight: JobPreflight,
        options: ResolvedIntradayOptions,
        instruments: list[dict[str, object]],
    ) -> None:
        windows = intraday_request_windows(options.date_from, options.date_to)
        requests = len(instruments) * len(windows)
        estimated_units = 1 + requests * UNITS_PER_REQUEST if requests else 0
        actual = {
            "work_units": requests,
            "estimated_api_calls": estimated_units,
            "missing_symbols": EodhdIntradayValidationJob._missing_symbols(
                options.symbols,
                instruments,
            ),
            "request_windows": [window.key for window in windows],
            "matched_instruments": len(instruments),
            "instrument_fingerprint": EodhdIntradayValidationJob._instrument_fingerprint(
                instruments
            ),
        }
        expected = {
            "work_units": preflight.work_units,
            "estimated_api_calls": preflight.estimated_api_calls,
            "missing_symbols": preflight.missing_symbols,
            "request_windows": preflight.parameters.get("request_windows"),
            "matched_instruments": preflight.parameters.get("matched_instruments"),
            "instrument_fingerprint": preflight.parameters.get("instrument_fingerprint"),
        }
        changed = [key for key in actual if actual[key] != expected[key]]
        if changed:
            raise ValueError(
                "intraday execution scope changed after preflight; rerun preflight: "
                f"fields={','.join(changed)}"
            )

    @staticmethod
    def _instrument_fingerprint(instruments: list[dict[str, object]]) -> str:
        """Bind an approved preflight to the exact instrument identities it resolved."""
        payload = "|".join(
            f"{int(row['instrument_id'])}:{str(row['provider_symbol']).upper()}"
            for row in sorted(instruments, key=lambda item: int(item["instrument_id"]))
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _resolve_options(
        *,
        symbols: list[str] | None,
        date_from: date | None,
        date_to: date | None,
        source: str | None,
        interval: str | None,
        market: str | None,
        max_api_units: int | None,
        data_root: str | Path | None,
        override_source: str,
    ) -> ResolvedIntradayOptions:
        raw_symbols, symbols_source = resolved_value(
            symbols, None, name="symbols", explicit_source=override_source
        )
        normalized_symbols = normalize_symbols(list(raw_symbols))
        if not normalized_symbols:
            raise ValueError("symbols must contain at least one symbol")
        resolved_from, from_source = resolved_value(
            date_from, None, name="date_from", explicit_source=override_source
        )
        resolved_to, to_source = resolved_value(
            date_to, None, name="date_to", explicit_source=override_source
        )
        if resolved_to < resolved_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        normalized_source = (source or SOURCE).strip().lower()
        normalized_interval = (interval or INTERVAL).strip().lower()
        normalized_market = (market or SUPPORTED_MARKET).strip().upper()
        if normalized_source != SOURCE:
            raise ValueError("intraday validation currently supports only source=eodhd")
        if normalized_interval != INTERVAL:
            raise ValueError("intraday validation currently supports only interval=1m")
        if normalized_market != SUPPORTED_MARKET:
            raise ValueError("intraday validation currently supports only market=US")
        resolved_limit = DEFAULT_MAX_API_UNITS if max_api_units is None else max_api_units
        if not 1 <= resolved_limit <= PUBLIC_MAX_API_UNITS:
            raise ValueError(
                f"max-api-calls must be between 1 and {PUBLIC_MAX_API_UNITS} for validation"
            )
        resolved_root = resolve_intraday_data_root(data_root, create=False)
        parameters = {
            "symbols": normalized_symbols,
            "date_from": resolved_from,
            "date_to": resolved_to,
            "source": normalized_source,
            "interval": normalized_interval,
            "market": normalized_market,
            "max_api_units": resolved_limit,
            "data_root": str(resolved_root),
            "dataset_kind": "validation",
        }
        parameter_sources = {
            "symbols": symbols_source,
            "date_from": from_source,
            "date_to": to_source,
            "source": override_source if source is not None else "job_default",
            "interval": override_source if interval is not None else "job_default",
            "market": override_source if market is not None else "job_default",
            "max_api_units": (
                override_source if max_api_units is not None else "job_default"
            ),
            "data_root": override_source if data_root is not None else "environment",
            "dataset_kind": "job_default",
        }
        return ResolvedIntradayOptions(
            symbols=normalized_symbols,
            date_from=resolved_from,
            date_to=resolved_to,
            source=normalized_source,
            interval=normalized_interval,
            market=normalized_market,
            max_api_units=resolved_limit,
            data_root=resolved_root,
            parameters=parameters,
            parameter_sources=parameter_sources,
        )


def intraday_request_windows(date_from: date, date_to: date) -> list[RequestWindow]:
    """Split an inclusive date range into EODHD's maximum 120-calendar-day windows."""
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")
    windows: list[RequestWindow] = []
    cursor = date_from
    while cursor <= date_to:
        end = min(cursor + timedelta(days=MAX_DAYS_PER_REQUEST - 1), date_to)
        windows.append(RequestWindow(cursor, end))
        cursor = end + timedelta(days=1)
    return windows
