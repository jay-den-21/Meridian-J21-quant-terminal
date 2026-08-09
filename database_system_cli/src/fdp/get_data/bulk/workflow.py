"""Execution engine for durable, resumable EODHD Bulk Daily work units."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from statistics import median
from typing import Mapping, Sequence

from fdp.get_data.contracts import (
    JobFailure,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
)
from fdp.get_data.historical.base import FATAL_HTTP_STATUS_CODES
from fdp.get_data.runtime import JobRuntime
from fdp.get_data.task_ledger import (
    DailyTaskScope,
    TaskAcquisition,
    TaskLedger,
    WorkUnitState,
)
from fdp.sources.eodhd.client import EodhdApiResponse, EodhdClient
from fdp.sources.eodhd.ingest import (
    BulkDailyPriceLoadResult,
    fetch_bulk_daily_prices,
    publish_bulk_daily_prices,
)
from fdp.sources.eodhd.ingest.common import record_api_call
from fdp.sources.eodhd.instruments import normalize_eodhd_asset_type
from fdp.sources.eodhd.identity import DatedInstrumentIdentityResolver
from fdp.storage.schema import ensure_runtime_schemas

THIN_RESPONSE_RATIO = 0.80
THIN_RESPONSE_MIN_SHORTFALL = 500
TYPE_THIN_RESPONSE_RATIO = 0.75
TYPE_THIN_RESPONSE_MIN_SHORTFALL = 100
THIN_RESPONSE_BASELINE_DAYS = 5
THIN_RESPONSE_MIN_BASELINE_DAYS = 3


@dataclass(frozen=True)
class DailyUnitOutcome:
    work_unit_id: int
    trade_date: date
    status: str
    status_code: int | None
    rows_fetched: int
    rows_matched: int
    rows_published: int
    rows_pending: int
    rows_rejected: int
    rows_shadowed: int
    api_calls: int
    api_units: int
    response_hash: str | None
    review_required: bool
    error_message: str | None
    metrics: dict[str, object]


@dataclass(frozen=True)
class DailyWorkflowExecution:
    outcomes: tuple[DailyUnitOutcome, ...]
    failures: tuple[JobFailure, ...]
    cancelled: bool
    stop_reason: str | None

    @property
    def review_required(self) -> bool:
        return any(outcome.review_required for outcome in self.outcomes)


class DailyBulkExecutor:
    """Fetch outside transactions, then publish and checkpoint each date atomically."""

    def __init__(
        self,
        *,
        runtime: JobRuntime,
        ledger: TaskLedger,
        client: EodhdClient,
        scope: DailyTaskScope,
        identity_resolver: DatedInstrumentIdentityResolver,
        reporter: ProgressReporter | None = None,
    ) -> None:
        self.runtime = runtime
        self.ledger = ledger
        self.client = client
        self.scope = scope
        self.identity_resolver = identity_resolver
        self.reporter = reporter or NullProgressReporter()

    def execute(
        self,
        acquisition: TaskAcquisition,
        *,
        parallel: bool,
        workers: int,
    ) -> DailyWorkflowExecution:
        pending = list(acquisition.pending_work_units)
        self.reporter.on_event(
            ProgressEvent(
                "start",
                "ingest.daily_workflow.fetch",
                len(acquisition.work_units) - len(pending),
                len(acquisition.work_units),
                message=(
                    f"run_id={acquisition.run_id} resumed={str(acquisition.resumed).lower()} "
                    f"reused={acquisition.reused_work_units}"
                ),
            )
        )
        if not pending:
            return DailyWorkflowExecution((), (), False, None)
        if parallel and workers > 1:
            return self._execute_parallel(acquisition.run_id, pending, workers=workers)
        return self._execute_sequential(acquisition.run_id, pending)

    def _execute_sequential(
        self,
        run_id: int,
        pending: Sequence[WorkUnitState],
    ) -> DailyWorkflowExecution:
        outcomes: list[DailyUnitOutcome] = []
        failures: list[JobFailure] = []
        cancelled = False
        stop_reason: str | None = None
        try:
            for unit in pending:
                outcome = self._execute_unit(run_id, unit)
                outcomes.append(outcome)
                self._report_unit(outcome, len(outcomes), len(pending))
                if outcome.status == "failed":
                    failures.append(
                        JobFailure(
                            unit.unit_key,
                            "request",
                            outcome.error_message or "Bulk Daily work unit failed",
                        )
                    )
                if outcome.status_code in FATAL_HTTP_STATUS_CODES:
                    stop_reason = (
                        f"fatal provider status {outcome.status_code} on {unit.unit_key}"
                    )
                    break
        except KeyboardInterrupt:
            cancelled = True
            stop_reason = "operator cancelled; committed work units are resumable"
        return DailyWorkflowExecution(
            tuple(outcomes), tuple(failures), cancelled, stop_reason
        )

    def _execute_parallel(
        self,
        run_id: int,
        pending: Sequence[WorkUnitState],
        *,
        workers: int,
    ) -> DailyWorkflowExecution:
        outcomes: list[DailyUnitOutcome] = []
        failures: list[JobFailure] = []
        cancelled = False
        stop_reason: str | None = None
        iterator = iter(pending)
        futures: dict[Future[DailyUnitOutcome], WorkUnitState] = {}

        def submit_next(executor: ThreadPoolExecutor) -> bool:
            try:
                unit = next(iterator)
            except StopIteration:
                return False
            futures[executor.submit(self._execute_unit, run_id, unit)] = unit
            return True

        with ThreadPoolExecutor(max_workers=workers) as executor:
            for _ in range(min(workers, len(pending))):
                submit_next(executor)
            try:
                stop_scheduling = False
                while futures:
                    completed, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                    for future in completed:
                        unit = futures.pop(future)
                        try:
                            outcome = future.result()
                        except Exception as exc:
                            outcome = self._record_exception(run_id, unit, exc)
                        outcomes.append(outcome)
                        self._report_unit(outcome, len(outcomes), len(pending))
                        if outcome.status == "failed":
                            failures.append(
                                JobFailure(
                                    unit.unit_key,
                                    "request",
                                    outcome.error_message or "Bulk Daily work unit failed",
                                )
                            )
                        if outcome.status_code in FATAL_HTTP_STATUS_CODES:
                            stop_scheduling = True
                            stop_reason = (
                                f"fatal provider status {outcome.status_code} "
                                f"on {unit.unit_key}"
                            )
                    if not stop_scheduling:
                        while len(futures) < workers and submit_next(executor):
                            pass
            except KeyboardInterrupt:
                cancelled = True
                stop_reason = "operator cancelled; draining already-started requests"
                for future, unit in list(futures.items()):
                    try:
                        outcome = future.result()
                    except Exception as exc:
                        outcome = self._record_exception(run_id, unit, exc)
                    outcomes.append(outcome)
                    self._report_unit(outcome, len(outcomes), len(pending))
                    if outcome.status == "failed":
                        failures.append(
                            JobFailure(
                                unit.unit_key,
                                "request",
                                outcome.error_message or "Bulk Daily work unit failed",
                            )
                        )
                futures.clear()
        outcomes.sort(key=lambda value: value.trade_date)
        return DailyWorkflowExecution(
            tuple(outcomes), tuple(failures), cancelled, stop_reason
        )

    def _execute_unit(self, run_id: int, unit: WorkUnitState) -> DailyUnitOutcome:
        with self.runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            claimed = self.ledger.claim_work_unit(
                connection,
                run_id=run_id,
                work_unit_id=unit.work_unit_id,
            )

        trade_date = claimed.trade_date
        try:
            with self.runtime.engine.connect() as connection:
                baseline = self.ledger.recent_verified_units(
                    connection,
                    series_fingerprint=claimed.series_fingerprint,
                    before_trade_date=trade_date,
                    limit=THIN_RESPONSE_BASELINE_DAYS,
                )
            responses = [
                fetch_bulk_daily_prices(
                    self.client,
                    exchange=self.scope.exchange,
                    trade_date=trade_date,
                    symbols=list(self.scope.symbols) or None,
                )
            ]
            first_check = _response_completeness(
                responses[0],
                trade_date=trade_date,
                asset_types=self.scope.asset_types,
                baseline=baseline,
            )
            if responses[0].success and first_check["review_required"]:
                responses.append(
                    fetch_bulk_daily_prices(
                        self.client,
                        exchange=self.scope.exchange,
                        trade_date=trade_date,
                        symbols=list(self.scope.symbols) or None,
                    )
                )
            final_response = _best_response(responses, trade_date=trade_date)
            final_check = _response_completeness(
                final_response,
                trade_date=trade_date,
                asset_types=self.scope.asset_types,
                baseline=baseline,
            )
            return self._publish_responses(
                run_id=run_id,
                unit=claimed,
                responses=responses,
                final_response=final_response,
                completeness=final_check,
            )
        except Exception as exc:
            return self._record_exception(run_id, claimed, exc)

    def _publish_responses(
        self,
        *,
        run_id: int,
        unit: WorkUnitState,
        responses: Sequence[EodhdApiResponse],
        final_response: EodhdApiResponse,
        completeness: Mapping[str, object],
    ) -> DailyUnitOutcome:
        trade_date = unit.trade_date
        published_results: list[BulkDailyPriceLoadResult] = []
        with self.runtime.engine.begin() as connection:
            ensure_runtime_schemas(connection)
            selected_published = False
            for response in responses:
                selected = response is final_response and not selected_published
                if not selected or _provider_date_mismatch(response, trade_date=trade_date):
                    record_api_call(
                        connection,
                        run_id=run_id,
                        work_unit_id=unit.work_unit_id,
                        response=response,
                        date_from=trade_date,
                        date_to=trade_date,
                    )
                    continue
                selected_published = True
                published_results.append(
                    publish_bulk_daily_prices(
                        connection,
                        response,
                        run_id=run_id,
                        work_unit_id=unit.work_unit_id,
                        exchange=self.scope.exchange,
                        trade_date=trade_date,
                        market=self.scope.market,
                        asset_types=list(self.scope.asset_types),
                        instrument_status=self.scope.instrument_status,
                        identity_resolver=self.identity_resolver,
                    )
                )

            successful = [result for result in published_results if result.status != "failed"]
            best_result = max(
                successful or published_results,
                key=lambda value: (value.rows_inserted, value.rows_fetched),
                default=None,
            )
            api_unit_cost = 100 + len(self.scope.symbols)
            api_calls = sum(response.retry_count + 1 for response in responses)
            api_units = api_calls * api_unit_cost
            review_reasons = list(completeness.get("reasons") or [])
            raw_rejections = 0
            if best_result is not None:
                raw_rejections = len(best_result.rejected_rows)
                if raw_rejections:
                    review_reasons.append(f"invalid_source_rows={raw_rejections}")
            provider_success = any(response.success for response in responses)
            publishable_success = provider_success and best_result is not None
            review_required = bool(review_reasons) and publishable_success
            if not publishable_success:
                status = "failed"
            elif review_required:
                status = "held"
            else:
                status = "success"
            error_message = (
                "; ".join(review_reasons)
                if review_reasons
                else final_response.error_message
            )
            type_counts = _response_asset_type_counts(final_response)
            response_hash = _response_hash(final_response)
            rows_fetched = final_response.rows_returned if provider_success else 0
            rows_published = best_result.rows_inserted if best_result is not None else 0
            rows_pending = (
                best_result.unmatched_rows + best_result.shadowed_rows
                if best_result is not None
                else 0
            )
            rows_rejected = raw_rejections
            rows_matched = best_result.rows_matched if best_result is not None else 0
            rows_shadowed = best_result.shadowed_rows if best_result is not None else 0
            accounted_rows = rows_published + rows_pending + rows_rejected
            closure_valid = not publishable_success or accounted_rows == rows_fetched
            if not closure_valid:
                review_reasons.append(
                    "source_row_closure_mismatch:"
                    f"fetched={rows_fetched};accounted={accounted_rows}"
                )
                status = "failed"
                review_required = False
                error_message = "; ".join(review_reasons)
            metrics = {
                "asset_type_counts": type_counts,
                "rows_matched": rows_matched,
                "rows_shadowed": rows_shadowed,
                "rejected_source_samples": [
                    {
                        "index": rejected.index,
                        "provider_symbol": rejected.provider_symbol,
                        "reason": rejected.reason,
                        "row": rejected.row,
                    }
                    for rejected in (best_result.rejected_rows[:20] if best_result else [])
                ],
                "response_attempts": len(responses),
                "http_attempts": api_calls,
                "completeness": dict(completeness),
                "response_hashes": [_response_hash(response) for response in responses],
                "provider_trade_date": (
                    best_result.trade_date.isoformat()
                    if best_result is not None and best_result.trade_date is not None
                    else trade_date.isoformat()
                ),
                "source_row_closure": {
                    "valid": closure_valid,
                    "fetched": rows_fetched,
                    "accounted": accounted_rows,
                },
            }
            self.ledger.finish_work_unit(
                connection,
                run_id=run_id,
                work_unit_id=unit.work_unit_id,
                status=status,
                rows_fetched=rows_fetched,
                rows_published=rows_published,
                rows_pending=rows_pending,
                rows_rejected=rows_rejected,
                api_calls=api_calls,
                api_units=api_units,
                response_hash=response_hash,
                quality_status=(
                    "source_closure_failed"
                    if not closure_valid
                    else "review_required"
                    if review_required
                    else "response_verified" if publishable_success else "execution_failed"
                ),
                metrics=metrics,
                error_message=error_message,
            )

        return DailyUnitOutcome(
            work_unit_id=unit.work_unit_id,
            trade_date=trade_date,
            status=status,
            status_code=final_response.status_code,
            rows_fetched=rows_fetched,
            rows_matched=rows_matched,
            rows_published=rows_published,
            rows_pending=rows_pending,
            rows_rejected=rows_rejected,
            rows_shadowed=rows_shadowed,
            api_calls=api_calls,
            api_units=api_units,
            response_hash=response_hash,
            review_required=review_required,
            error_message=error_message,
            metrics=metrics,
        )

    def _record_exception(
        self,
        run_id: int,
        unit: WorkUnitState,
        exc: Exception,
    ) -> DailyUnitOutcome:
        message = f"{type(exc).__name__}: {exc}"[:1_000]
        try:
            with self.runtime.engine.begin() as connection:
                current = self.ledger.load_work_unit(
                    connection,
                    work_unit_id=unit.work_unit_id,
                )
                if current.status == "running":
                    self.ledger.finish_work_unit(
                        connection,
                        run_id=run_id,
                        work_unit_id=unit.work_unit_id,
                        status="failed",
                        rows_fetched=0,
                        rows_published=0,
                        rows_pending=0,
                        rows_rejected=0,
                        api_calls=0,
                        api_units=0,
                        response_hash=None,
                        quality_status="execution_failed",
                        error_message=message,
                    )
        except Exception as checkpoint_exc:
            message = (
                f"{message}; checkpoint_failed={type(checkpoint_exc).__name__}:"
                f" {checkpoint_exc}"
            )[:1_000]
        return DailyUnitOutcome(
            work_unit_id=unit.work_unit_id,
            trade_date=unit.trade_date,
            status="failed",
            status_code=None,
            rows_fetched=0,
            rows_matched=0,
            rows_published=0,
            rows_pending=0,
            rows_rejected=0,
            rows_shadowed=0,
            api_calls=0,
            api_units=0,
            response_hash=None,
            review_required=False,
            error_message=message,
            metrics={},
        )

    def _report_unit(self, outcome: DailyUnitOutcome, completed: int, total: int) -> None:
        self.reporter.on_event(
            ProgressEvent(
                "unit_failed" if outcome.status == "failed" else "unit_completed",
                "ingest.daily_workflow.fetch",
                completed,
                total,
                unit=outcome.trade_date.isoformat(),
                message=outcome.status,
                counters={
                    "fetched": outcome.rows_fetched,
                    "published": outcome.rows_published,
                    "pending": outcome.rows_pending,
                    "rejected": outcome.rows_rejected,
                    "api_calls": outcome.api_calls,
                    "api_units": outcome.api_units,
                },
            )
        )


def _response_hash(response: EodhdApiResponse) -> str:
    payload = {
        "endpoint": response.endpoint,
        "status_code": response.status_code,
        "success": response.success,
        "payload": response.payload,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_trade_date(row: Mapping[str, object]) -> date | None:
    raw = row.get("date") or row.get("Date")
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _provider_date_mismatch(response: EodhdApiResponse, *, trade_date: date) -> bool:
    if not response.success or not isinstance(response.payload, list):
        return False
    observed = {
        value
        for row in response.payload
        if isinstance(row, Mapping) and (value := _row_trade_date(row)) is not None
    }
    return bool(observed and observed != {trade_date})


def _response_asset_type_counts(response: EodhdApiResponse) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(response.payload, list):
        return counts
    for row in response.payload:
        if not isinstance(row, Mapping):
            continue
        asset_type = normalize_eodhd_asset_type(row.get("type") or row.get("Type"))
        key = asset_type or "other"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _response_completeness(
    response: EodhdApiResponse,
    *,
    trade_date: date,
    asset_types: Sequence[str],
    baseline: Sequence[WorkUnitState],
) -> dict[str, object]:
    reasons: list[str] = []
    if not response.success:
        return {
            "review_required": False,
            "reasons": [],
            "baseline_days": len(baseline),
        }
    if _provider_date_mismatch(response, trade_date=trade_date):
        reasons.append("provider_trade_date_mismatch")
    if response.rows_returned == 0:
        reasons.append("empty_success_response")

    baseline_rows = [unit.rows_fetched for unit in baseline if unit.rows_fetched > 0]
    row_median: float | None = None
    if len(baseline_rows) >= THIN_RESPONSE_MIN_BASELINE_DAYS:
        row_median = float(median(baseline_rows))
        shortfall = row_median - response.rows_returned
        if (
            response.rows_returned < row_median * THIN_RESPONSE_RATIO
            and shortfall >= THIN_RESPONSE_MIN_SHORTFALL
        ):
            reasons.append(
                "thin_total_response:"
                f"rows={response.rows_returned};median={int(row_median)}"
            )

    current_types = _response_asset_type_counts(response)
    type_baselines: dict[str, float] = {}
    for asset_type in asset_types:
        values = [
            int(unit.metrics.get("asset_type_counts", {}).get(asset_type, 0))
            for unit in baseline
            if isinstance(unit.metrics.get("asset_type_counts"), Mapping)
        ]
        if len(values) < THIN_RESPONSE_MIN_BASELINE_DAYS:
            continue
        type_median = float(median(values))
        type_baselines[asset_type] = type_median
        current = current_types.get(asset_type, 0)
        shortfall = type_median - current
        if (
            current < type_median * TYPE_THIN_RESPONSE_RATIO
            and shortfall >= TYPE_THIN_RESPONSE_MIN_SHORTFALL
        ):
            reasons.append(
                f"thin_{asset_type}_response:rows={current};median={int(type_median)}"
            )
    return {
        "review_required": bool(reasons),
        "reasons": reasons,
        "baseline_days": len(baseline),
        "baseline_row_median": row_median,
        "baseline_asset_type_medians": type_baselines,
        "response_asset_type_counts": current_types,
    }


def _best_response(
    responses: Sequence[EodhdApiResponse],
    *,
    trade_date: date,
) -> EodhdApiResponse:
    if not responses:
        raise ValueError("responses must not be empty")
    return max(
        responses,
        key=lambda response: (
            int(response.success),
            int(not _provider_date_mismatch(response, trade_date=trade_date)),
            response.rows_returned,
        ),
    )
