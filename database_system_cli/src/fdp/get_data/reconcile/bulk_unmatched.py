"""Guided classify and route job for staged Bulk EOD observations."""

from __future__ import annotations

from datetime import date

from fdp.bulk_unmatched import (
    BulkUnmatchedSummaryRow,
    classify_bulk_unmatched_observations,
    route_bulk_unmatched_observations,
    summarize_bulk_unmatched_observations,
)
from fdp.get_data.contracts import JobFailure, JobPreflight, JobResult
from fdp.get_data.runtime import JobRuntime
from fdp.storage.schema import ensure_runtime_schemas


class BulkUnmatchedReconcileJob:
    """Provide the staged unmatched summary -> classify -> preview -> route flow."""

    job_key = "reconcile.bulk_unmatched"
    job_module = "fdp.get_data.reconcile.bulk_unmatched"

    def preflight(
        self,
        *,
        date_from: date,
        date_to: date,
        market: str = "US",
        asset_types: list[str] | None = None,
        limit: int | None = None,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        self._validate(date_from=date_from, date_to=date_to, limit=limit)
        resolved_assets = [value.lower() for value in (asset_types or ["stock", "etf", "index"])]
        active_runtime = runtime or JobRuntime.from_env()
        with active_runtime.engine.connect() as connection:
            rows = summarize_bulk_unmatched_observations(
                connection,
                date_from=date_from,
                date_to=date_to,
                market=market.upper(),
            )
        total = sum(row.row_count for row in rows)
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=[
                "system.bulk_unmatched_daily_price_observation",
                *(f"{asset_type}_daily_price" for asset_type in resolved_assets),
            ],
            work_units=total,
            estimated_api_calls=0,
            estimated_rows=total,
            parameters={
                "date_from": date_from,
                "date_to": date_to,
                "market": market.upper(),
                "asset_types": resolved_assets,
                "limit": limit,
            },
            parameter_sources={
                "date_from": override_source,
                "date_to": override_source,
                "market": override_source,
                "asset_types": override_source if asset_types is not None else "job_default",
                "limit": override_source if limit is not None else "job_default",
            },
        )

    def summary(
        self,
        *,
        date_from: date,
        date_to: date,
        market: str = "US",
        runtime: JobRuntime | None = None,
    ) -> list[BulkUnmatchedSummaryRow]:
        self._validate(date_from=date_from, date_to=date_to, limit=None)
        active_runtime = runtime or JobRuntime.from_env()
        with active_runtime.engine.connect() as connection:
            return summarize_bulk_unmatched_observations(
                connection,
                date_from=date_from,
                date_to=date_to,
                market=market.upper(),
            )

    def classify(
        self,
        *,
        date_from: date,
        date_to: date,
        market: str = "US",
        limit: int | None = None,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobResult:
        self._validate(date_from=date_from, date_to=date_to, limit=limit)
        active_runtime = runtime or JobRuntime.from_env()
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            result = classify_bulk_unmatched_observations(
                connection,
                date_from=date_from,
                date_to=date_to,
                market=market.upper(),
                limit=limit,
            )
        unresolved = result.needs_instrument + result.non_price_asset + result.unknown
        return JobResult(
            job=f"{self.job_key}.classify",
            status="success",
            run_id=None,
            parameters={
                "date_from": date_from,
                "date_to": date_to,
                "market": market.upper(),
                "limit": limit,
            },
            parameter_sources={
                "date_from": override_source,
                "date_to": override_source,
                "market": override_source,
                "limit": override_source if limit is not None else "job_default",
            },
            rows_fetched=result.scanned,
            rows_matched=result.matched,
            rows_rejected=unresolved,
            work_units_total=result.scanned,
            work_units_completed=result.scanned,
            metrics=result.to_dict(),
        )

    def route(
        self,
        *,
        date_from: date,
        date_to: date,
        market: str = "US",
        asset_types: list[str] | None = None,
        limit: int | None = None,
        execute: bool = False,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobResult:
        self._validate(date_from=date_from, date_to=date_to, limit=limit)
        resolved_assets = [value.lower() for value in (asset_types or ["stock", "etf", "index"])]
        active_runtime = runtime or JobRuntime.from_env()
        with active_runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            result = route_bulk_unmatched_observations(
                connection,
                date_from=date_from,
                date_to=date_to,
                market=market.upper(),
                asset_types=resolved_assets,
                dry_run=not execute,
                limit=limit,
            )
        status = (
            "dry_run"
            if result.dry_run
            else ("partial_failed" if result.rows_rejected else "success")
        )
        failures = (
            [JobFailure("route", "invalid_price_row", f"{result.rows_rejected} row(s) rejected")]
            if result.rows_rejected
            else []
        )
        return JobResult(
            job=f"{self.job_key}.route",
            status=status,
            run_id=None,
            parameters={
                "date_from": date_from,
                "date_to": date_to,
                "market": market.upper(),
                "asset_types": resolved_assets,
                "limit": limit,
                "execute": execute,
            },
            parameter_sources={
                "date_from": override_source,
                "date_to": override_source,
                "market": override_source,
                "asset_types": override_source if asset_types is not None else "job_default",
                "limit": override_source if limit is not None else "job_default",
                "execute": override_source,
            },
            rows_matched=result.routeable,
            rows_inserted=result.rows_inserted,
            rows_rejected=result.rows_rejected,
            work_units_total=result.routeable,
            work_units_completed=result.routed if execute else 0,
            work_units_failed=result.rows_rejected,
            failures=failures,
            metrics=result.to_dict(),
        )

    @staticmethod
    def _validate(*, date_from: date, date_to: date, limit: int | None) -> None:
        if date_to < date_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
