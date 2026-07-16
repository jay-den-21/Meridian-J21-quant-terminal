"""Guided, resumable classify and route jobs for staged Bulk EOD rows."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date
from typing import Any

from fdp.bulk_unmatched import (
    ADVANCED_CLASSIFICATION_STATUSES,
    DEFAULT_CLASSIFICATION_STATUSES,
    BulkUnmatchedSummaryRow,
    classify_bulk_unmatched_batch,
    count_bulk_unmatched_route_groups,
    inspect_bulk_unmatched_classify_snapshot,
    list_bulk_unmatched_observations,
    route_bulk_unmatched_observations,
    summarize_bulk_unmatched_observations,
    validate_classification_statuses,
)
from fdp.get_data.contracts import (
    JobFailure,
    JobPreflight,
    JobResult,
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
)
from fdp.get_data.reconcile.workflow import (
    assert_reconcile_route_scope,
    assert_reconcile_scope,
    create_reconcile_run,
    load_reconcile_run,
    new_reconcile_checkpoint,
    new_route_reconcile_checkpoint,
    save_reconcile_checkpoint,
)
from fdp.get_data.runtime import JobRuntime
from fdp.quality.validation import (
    create_bulk_route_quality_check,
    finish_bulk_route_quality_check,
    record_bulk_route_quality_issues,
    validate_daily_prices,
)
from fdp.sources.eodhd.identity import DatedInstrumentIdentityResolver
from fdp.storage.schema import ensure_runtime_schemas

DEFAULT_CLASSIFY_BATCH_SIZE = 5_000
DEFAULT_ROUTE_GROUP_BATCH_SIZE = 1_000
BACKLOG_WARNING_THRESHOLD = 100_000
DEFAULT_ROUTE_ASSET_TYPES = ["stock", "etf", "fund", "index"]


class BulkUnmatchedReconcileJob:
    """Run local Bulk staging reconciliation without provider API calls.

    Input: an inclusive date range, refreshable staging states, and batch limits.
    Output: one durable workflow run ID plus versioned Job results/checkpoints.
    Flow: snapshot -> classify batches -> route batches -> quality validation.
    """

    job_key = "reconcile.bulk_unmatched"
    job_module = "fdp.get_data.reconcile.bulk_unmatched"

    def preflight(
        self,
        *,
        date_from: date,
        date_to: date,
        market: str = "US",
        asset_types: list[str] | None = None,
        statuses: list[str] | None = None,
        batch_size: int = DEFAULT_CLASSIFY_BATCH_SIZE,
        limit: int | None = None,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobPreflight:
        """Freeze a read-only classifier snapshot before confirmation."""
        self._validate(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            batch_size=batch_size,
        )
        resolved_statuses = list(
            validate_classification_statuses(statuses or DEFAULT_CLASSIFICATION_STATUSES)
        )
        resolved_assets = self._asset_types(asset_types)
        normalized_market = market.upper()
        active_runtime = runtime or JobRuntime.from_env()
        with active_runtime.engine.connect() as connection:
            snapshot = inspect_bulk_unmatched_classify_snapshot(
                connection,
                date_from=date_from,
                date_to=date_to,
                market=normalized_market,
                statuses=resolved_statuses,
            )
        warnings: list[str] = []
        advanced = sorted(set(resolved_statuses) & ADVANCED_CLASSIFICATION_STATUSES)
        if advanced:
            warnings.append(
                "advanced reclassification states selected: " + ", ".join(advanced)
            )
        if snapshot.total > BACKLOG_WARNING_THRESHOLD:
            warnings.append(
                f"large local backlog: {snapshot.total:,} rows; checkpointed batches will be used"
            )
        parameters = {
            "date_from": date_from,
            "date_to": date_to,
            "market": normalized_market,
            "asset_types": resolved_assets,
            "statuses": resolved_statuses,
            "batch_size": batch_size,
            "limit": limit,
            "status_counts": snapshot.status_counts,
            "snapshot_max_by_status": snapshot.snapshot_max_by_status,
        }
        return JobPreflight(
            job=self.job_key,
            job_module=self.job_module,
            target_tables=[
                "system.bulk_unmatched_daily_price_observation",
                "system.ingestion_task_run",
                "system.instrument_identity_resolution_audit",
                *(f"{asset_type}_daily_price" for asset_type in resolved_assets),
            ],
            work_units=snapshot.total,
            estimated_api_calls=0,
            estimated_rows=snapshot.total,
            parameters=parameters,
            parameter_sources={
                "date_from": override_source,
                "date_to": override_source,
                "market": override_source,
                "asset_types": override_source if asset_types is not None else "job_default",
                "statuses": override_source if statuses is not None else "job_default",
                "batch_size": override_source,
                "limit": override_source if limit is not None else "job_default",
                "status_counts": "database_snapshot",
                "snapshot_max_by_status": "database_snapshot",
            },
            warnings=warnings,
        )

    def summary(
        self,
        *,
        date_from: date,
        date_to: date,
        market: str = "US",
        runtime: JobRuntime | None = None,
    ) -> list[BulkUnmatchedSummaryRow]:
        self._validate(date_from=date_from, date_to=date_to, limit=None, batch_size=1)
        active_runtime = runtime or JobRuntime.from_env()
        with active_runtime.engine.connect() as connection:
            return summarize_bulk_unmatched_observations(
                connection,
                date_from=date_from,
                date_to=date_to,
                market=market.upper(),
            )

    def list(
        self,
        *,
        date_from: date,
        date_to: date,
        market: str = "US",
        status: str | None = None,
        limit: int = 50,
        runtime: JobRuntime | None = None,
    ) -> list[dict[str, object]]:
        self._validate(date_from=date_from, date_to=date_to, limit=limit, batch_size=1)
        active_runtime = runtime or JobRuntime.from_env()
        with active_runtime.engine.connect() as connection:
            return list_bulk_unmatched_observations(
                connection,
                date_from=date_from,
                date_to=date_to,
                market=market.upper(),
                status=status,
                limit=limit,
            )

    def status(
        self,
        *,
        run_id: int,
        runtime: JobRuntime | None = None,
    ) -> dict[str, object]:
        """Return the durable task status and parsed checkpoint for one run ID."""
        if run_id <= 0:
            raise ValueError("run_id must be positive")
        active_runtime = runtime or JobRuntime.from_env()
        with active_runtime.engine.connect() as connection:
            state = load_reconcile_run(connection, run_id=run_id)
        return {
            "run_id": state.run_id,
            "status": state.status,
            "checkpoint": state.checkpoint,
            "rows_fetched": state.rows_fetched,
            "rows_inserted": state.rows_inserted,
            "rows_updated": state.rows_updated,
            "rows_rejected": state.rows_rejected,
            "api_calls": state.api_calls,
            "error_message": state.error_message,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
            "resume_hint": self._resume_hint(state.run_id, state.checkpoint),
        }

    def classify(
        self,
        *,
        date_from: date,
        date_to: date,
        market: str = "US",
        statuses: list[str] | None = None,
        batch_size: int = DEFAULT_CLASSIFY_BATCH_SIZE,
        limit: int | None = None,
        run_id: int | None = None,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        preflight: JobPreflight | None = None,
        override_source: str = "python",
    ) -> JobResult:
        """Classify checkpointed batches and preserve the last committed cursor."""
        self._validate(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            batch_size=batch_size,
        )
        normalized_market = market.upper()
        resolved_statuses = list(
            validate_classification_statuses(statuses or DEFAULT_CLASSIFICATION_STATUSES)
        )
        active_runtime = runtime or JobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()
        active_preflight = preflight
        if run_id is None:
            active_preflight = active_preflight or self.preflight(
                date_from=date_from,
                date_to=date_to,
                market=normalized_market,
                statuses=resolved_statuses,
                batch_size=batch_size,
                limit=limit,
                runtime=active_runtime,
                override_source=override_source,
            )
            checkpoint = new_reconcile_checkpoint(
                date_from=date_from,
                date_to=date_to,
                market=normalized_market,
                source_statuses=resolved_statuses,
                status_counts=active_preflight.parameters["status_counts"],
                snapshot_max_by_status=active_preflight.parameters[
                    "snapshot_max_by_status"
                ],
            )
            with active_runtime.engine.begin() as connection:
                ensure_runtime_schemas(connection)
                run_id = create_reconcile_run(connection, checkpoint=checkpoint)
        else:
            if run_id <= 0:
                raise ValueError("run_id must be positive")
            with active_runtime.engine.begin() as connection:
                ensure_runtime_schemas(connection)
                state = load_reconcile_run(connection, run_id=run_id)
                checkpoint = state.checkpoint
                assert_reconcile_scope(
                    checkpoint,
                    date_from=date_from,
                    date_to=date_to,
                    market=normalized_market,
                    source_statuses=resolved_statuses,
                )
                if checkpoint["phase"] != "classify":
                    raise ValueError(
                        f"reconcile run {run_id} is already in phase {checkpoint['phase']}"
                    )
                save_reconcile_checkpoint(
                    connection,
                    run_id=run_id,
                    checkpoint=checkpoint,
                    status="running",
                )

        with active_runtime.engine.connect() as connection:
            identity_resolver = DatedInstrumentIdentityResolver.from_connection(
                connection,
                market=normalized_market,
                asset_types=DEFAULT_ROUTE_ASSET_TYPES,
                instrument_status="all",
            )

        classify_state = checkpoint["classify"]
        frozen_total = sum(int(value) for value in classify_state["status_counts"].values())
        already_processed = int(classify_state["rows_processed"])
        remaining_at_start = max(0, frozen_total - already_processed)
        command_target = min(remaining_at_start, limit or remaining_at_start)
        command_processed = 0
        active_reporter.on_event(
            ProgressEvent(
                "start",
                f"{self.job_key}.classify",
                0,
                command_target,
                message=f"run_id={run_id}",
            )
        )

        error_message: str | None = None
        status = "success"
        failures: list[JobFailure] = []
        try:
            while (
                int(classify_state["status_index"]) < len(resolved_statuses)
                and command_processed < command_target
            ):
                status_index = int(classify_state["status_index"])
                source_status = resolved_statuses[status_index]
                snapshot_max = int(
                    classify_state["snapshot_max_by_status"].get(source_status, 0)
                )
                current_batch_size = min(
                    batch_size,
                    command_target - command_processed,
                )
                next_checkpoint = deepcopy(checkpoint)
                next_classify_state = next_checkpoint["classify"]
                with active_runtime.engine.begin() as connection:
                    ensure_runtime_schemas(connection)
                    batch = classify_bulk_unmatched_batch(
                        connection,
                        date_from=date_from,
                        date_to=date_to,
                        source_status=source_status,
                        snapshot_max_observation_id=snapshot_max,
                        run_id=run_id,
                        market=normalized_market,
                        after_trade_date=(
                            date.fromisoformat(
                                str(next_classify_state["last_trade_date"])
                            )
                            if next_classify_state["last_trade_date"] is not None
                            else None
                        ),
                        after_observation_id=int(
                            next_classify_state["last_observation_id"]
                        ),
                        batch_size=current_batch_size,
                        identity_resolver=identity_resolver,
                    )
                    if batch.scanned:
                        next_classify_state["rows_processed"] = (
                            int(next_classify_state["rows_processed"]) + batch.scanned
                        )
                        next_classify_state["batches_committed"] = (
                            int(next_classify_state["batches_committed"]) + 1
                        )
                        next_classify_state[
                            "last_observation_id"
                        ] = batch.last_observation_id
                        next_classify_state["last_trade_date"] = (
                            batch.last_trade_date.isoformat()
                            if batch.last_trade_date is not None
                            else None
                        )
                        target_counts = Counter(
                            next_classify_state["target_status_counts"]
                        )
                        target_counts.update(batch.target_status_counts)
                        next_classify_state["target_status_counts"] = dict(
                            sorted(target_counts.items())
                        )
                    else:
                        next_classify_state["status_index"] = status_index + 1
                        next_classify_state["current_status"] = (
                            resolved_statuses[status_index + 1]
                            if status_index + 1 < len(resolved_statuses)
                            else None
                        )
                        next_classify_state["last_observation_id"] = 0
                        next_classify_state["last_trade_date"] = None
                    next_checkpoint["classify"] = next_classify_state
                    save_reconcile_checkpoint(
                        connection,
                        run_id=run_id,
                        checkpoint=next_checkpoint,
                        rows_fetched=int(next_classify_state["rows_processed"]),
                        rows_updated=int(next_classify_state["rows_processed"]),
                    )
                checkpoint = next_checkpoint
                classify_state = checkpoint["classify"]
                if batch.scanned:
                    command_processed += batch.scanned
                    active_reporter.on_event(
                        ProgressEvent(
                            "unit_completed",
                            f"{self.job_key}.classify",
                            command_processed,
                            command_target,
                            unit=source_status,
                            message=f"checkpoint={batch.last_observation_id}",
                            counters={
                                "batches": int(classify_state["batches_committed"]),
                                "matched": int(
                                    classify_state["target_status_counts"].get("matched", 0)
                                ),
                            },
                        )
                    )
        except KeyboardInterrupt:
            status = "cancelled"
            error_message = "operator cancelled; resume with the same run_id"
            failures.append(JobFailure(str(run_id), "cancelled", error_message))
        except Exception as exc:
            status = (
                "partial_failed"
                if int(classify_state["rows_processed"]) > already_processed
                else "failed"
            )
            error_message = self._concise_exception(exc)
            failures.append(JobFailure(str(run_id), "classification", error_message))

        remaining = max(0, frozen_total - int(classify_state["rows_processed"]))
        completed_all = int(classify_state["status_index"]) >= len(resolved_statuses)
        if status == "success" and remaining == 0:
            classify_state["status_index"] = len(resolved_statuses)
            classify_state["current_status"] = None
            classify_state["last_observation_id"] = 0
            classify_state["last_trade_date"] = None
            completed_all = True
        if status == "success" and completed_all:
            checkpoint["phase"] = "route"
        elif status == "success" and command_processed >= command_target and not completed_all:
            status = "partial_failed"
            error_message = "classification limit reached; resume with the same run_id"
            failures.append(JobFailure(str(run_id), "limit_reached", error_message))

        target_counts = {
            key: int(value)
            for key, value in classify_state["target_status_counts"].items()
        }
        if completed_all:
            remaining = 0
        with active_runtime.engine.begin() as connection:
            save_reconcile_checkpoint(
                connection,
                run_id=run_id,
                checkpoint=checkpoint,
                status=status,
                rows_fetched=int(classify_state["rows_processed"]),
                rows_updated=int(classify_state["rows_processed"]),
                rows_rejected=(
                    int(classify_state["rows_processed"])
                    - target_counts.get("matched", 0)
                ),
                error_message=error_message,
                finished=True,
            )
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                f"{self.job_key}.classify",
                command_processed,
                command_target,
                message=status,
                counters={
                    "batches": int(classify_state["batches_committed"]),
                    "matched": target_counts.get("matched", 0),
                    "remaining": remaining,
                    "api_calls": 0,
                },
            )
        )
        return JobResult(
            job=f"{self.job_key}.classify",
            status=status,
            run_id=run_id,
            parameters={
                "date_from": date_from,
                "date_to": date_to,
                "market": normalized_market,
                "statuses": resolved_statuses,
                "batch_size": batch_size,
                "limit": limit,
            },
            parameter_sources={
                "date_from": override_source,
                "date_to": override_source,
                "market": override_source,
                "statuses": override_source if statuses is not None else "job_default",
                "batch_size": override_source,
                "limit": override_source if limit is not None else "job_default",
            },
            rows_fetched=int(classify_state["rows_processed"]),
            rows_matched=target_counts.get("matched", 0),
            rows_rejected=(
                int(classify_state["rows_processed"]) - target_counts.get("matched", 0)
            ),
            api_calls=0,
            work_units_total=frozen_total,
            work_units_completed=int(classify_state["rows_processed"]),
            work_units_failed=1 if status in {"failed", "partial_failed"} else 0,
            failures=failures,
            metrics={
                "source_statuses": resolved_statuses,
                "target_status_counts": target_counts,
                "batches_committed": int(classify_state["batches_committed"]),
                "last_observation_id": classify_state["last_observation_id"],
                "last_trade_date": classify_state["last_trade_date"],
                "snapshot_max_by_status": classify_state["snapshot_max_by_status"],
                "remaining_eligible": remaining,
                "checkpoint_phase": checkpoint["phase"],
            },
            error_message=error_message,
            preflight=active_preflight,
        )

    def route(
        self,
        *,
        date_from: date,
        date_to: date,
        market: str = "US",
        asset_types: list[str] | None = None,
        limit: int | None = None,
        batch_size: int = DEFAULT_ROUTE_GROUP_BATCH_SIZE,
        execute: bool = False,
        run_id: int | None = None,
        runtime: JobRuntime | None = None,
        reporter: ProgressReporter | None = None,
        override_source: str = "python",
    ) -> JobResult:
        """Dry-run or execute complete-group route batches with durable resume state."""
        self._validate(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            batch_size=batch_size,
        )
        normalized_market = market.upper()
        resolved_assets = self._asset_types(asset_types)
        active_runtime = runtime or JobRuntime.from_env()
        active_reporter = reporter or NullProgressReporter()

        if not execute:
            if run_id is not None:
                with active_runtime.engine.connect() as connection:
                    state = load_reconcile_run(connection, run_id=run_id)
                    assert_reconcile_route_scope(
                        state.checkpoint,
                        date_from=date_from,
                        date_to=date_to,
                        market=normalized_market,
                        asset_types=resolved_assets,
                    )
                    if state.checkpoint["phase"] != "route":
                        raise ValueError(
                            f"reconcile run {run_id} is in phase "
                            f"{state.checkpoint['phase']}, not route"
                        )
            with active_runtime.engine.connect() as connection:
                remaining = count_bulk_unmatched_route_groups(
                    connection,
                    date_from=date_from,
                    date_to=date_to,
                    market=normalized_market,
                    asset_types=resolved_assets,
                )
                preview_groups = min(remaining, limit or batch_size)
                result = route_bulk_unmatched_observations(
                    connection,
                    date_from=date_from,
                    date_to=date_to,
                    market=normalized_market,
                    asset_types=resolved_assets,
                    dry_run=True,
                    limit=max(1, preview_groups),
                )
            metrics = result.to_dict()
            metrics.update(
                {
                    "remaining_groups": remaining,
                    "preview_groups": preview_groups,
                    "api_calls": 0,
                }
            )
            return JobResult(
                job=f"{self.job_key}.route",
                status="dry_run",
                run_id=run_id,
                parameters={
                    "date_from": date_from,
                    "date_to": date_to,
                    "market": normalized_market,
                    "asset_types": resolved_assets,
                    "limit": limit,
                    "batch_size": batch_size,
                    "execute": False,
                },
                parameter_sources=self._route_parameter_sources(
                    asset_types=asset_types,
                    limit=limit,
                    override_source=override_source,
                ),
                rows_matched=result.routeable,
                rows_rejected=result.rows_rejected,
                api_calls=0,
                work_units_total=remaining,
                metrics=metrics,
            )

        if run_id is None:
            checkpoint = new_route_reconcile_checkpoint(
                date_from=date_from,
                date_to=date_to,
                market=normalized_market,
                asset_types=resolved_assets,
            )
            with active_runtime.engine.begin() as connection:
                ensure_runtime_schemas(connection)
                run_id = create_reconcile_run(connection, checkpoint=checkpoint)
        else:
            if run_id <= 0:
                raise ValueError("run_id must be positive")
            with active_runtime.engine.begin() as connection:
                ensure_runtime_schemas(connection)
                state = load_reconcile_run(connection, run_id=run_id)
                checkpoint = state.checkpoint
                assert_reconcile_route_scope(
                    checkpoint,
                    date_from=date_from,
                    date_to=date_to,
                    market=normalized_market,
                    asset_types=resolved_assets,
                )
                if checkpoint["phase"] != "route":
                    raise ValueError(
                        f"reconcile run {run_id} is in phase "
                        f"{checkpoint['phase']}, not route"
                    )
                if not checkpoint["route"].get("asset_types"):
                    checkpoint["route"]["asset_types"] = list(resolved_assets)
                save_reconcile_checkpoint(
                    connection,
                    run_id=run_id,
                    checkpoint=checkpoint,
                    status="running",
                )

        route_state = checkpoint["route"]
        with active_runtime.engine.connect() as connection:
            remaining_at_start = count_bulk_unmatched_route_groups(
                connection,
                date_from=date_from,
                date_to=date_to,
                market=normalized_market,
                asset_types=resolved_assets,
            )
        already_processed = int(route_state["groups_processed"])
        if route_state.get("groups_total") is None:
            route_state["groups_total"] = already_processed + remaining_at_start
        command_target = min(remaining_at_start, limit or remaining_at_start)
        command_processed = 0
        command_route_failed = 0
        status = "success"
        error_message: str | None = None
        failures: list[JobFailure] = []
        stalled = False
        active_reporter.on_event(
            ProgressEvent(
                "start",
                f"{self.job_key}.route",
                0,
                command_target,
                message=f"run_id={run_id}",
            )
        )
        try:
            while command_processed < command_target:
                current_batch_size = min(
                    batch_size,
                    command_target - command_processed,
                )
                next_checkpoint = deepcopy(checkpoint)
                next_route_state = next_checkpoint["route"]
                with active_runtime.engine.begin() as connection:
                    ensure_runtime_schemas(connection)
                    batch = route_bulk_unmatched_observations(
                        connection,
                        date_from=date_from,
                        date_to=date_to,
                        market=normalized_market,
                        asset_types=resolved_assets,
                        dry_run=False,
                        limit=current_batch_size,
                        run_id=run_id,
                    )
                    if batch.groups_selected == 0:
                        stalled = True
                    else:
                        if batch.route_failures:
                            quality_check_run_id = next_route_state.get(
                                "identity_quality_check_run_id"
                            )
                            if quality_check_run_id is None:
                                quality_check_run_id = create_bulk_route_quality_check(
                                    connection,
                                    market=normalized_market,
                                    date_from=date_from,
                                    date_to=date_to,
                                )
                                next_route_state[
                                    "identity_quality_check_run_id"
                                ] = quality_check_run_id
                            new_quality_issues = record_bulk_route_quality_issues(
                                connection,
                                check_run_id=int(quality_check_run_id),
                                market=normalized_market,
                                failures=batch.route_failures,
                            )
                            next_route_state["identity_quality_issue_count"] = int(
                                next_route_state["identity_quality_issue_count"]
                            ) + int(new_quality_issues)
                        next_route_state["groups_processed"] = (
                            int(next_route_state["groups_processed"])
                            + batch.groups_selected
                        )
                        next_route_state["observations_selected"] = int(
                            next_route_state.get("observations_selected", 0)
                        ) + int(batch.observations_selected)
                        next_route_state["batches_committed"] = (
                            int(next_route_state["batches_committed"]) + 1
                        )
                        for key in (
                            "routed",
                            "shadowed",
                            "route_failed",
                            "rows_inserted",
                            "identity_audits",
                        ):
                            next_route_state[key] = int(next_route_state[key]) + int(
                                getattr(batch, key)
                            )
                        next_route_state[
                            "last_instrument_id"
                        ] = batch.last_instrument_id
                        next_route_state["last_trade_date"] = (
                            batch.last_trade_date.isoformat()
                            if batch.last_trade_date is not None
                            else None
                        )
                        next_checkpoint["route"] = next_route_state
                        save_reconcile_checkpoint(
                            connection,
                            run_id=run_id,
                            checkpoint=next_checkpoint,
                            rows_fetched=int(
                                next_checkpoint["classify"]["rows_processed"]
                            ),
                            rows_inserted=int(next_route_state["rows_inserted"]),
                            rows_updated=int(
                                next_checkpoint["classify"]["rows_processed"]
                            ),
                            rows_rejected=self._workflow_rejected_rows(
                                next_checkpoint
                            ),
                        )
                if stalled:
                    break
                checkpoint = next_checkpoint
                route_state = checkpoint["route"]
                command_processed += batch.groups_selected
                command_route_failed += batch.route_failed
                active_reporter.on_event(
                    ProgressEvent(
                        "unit_completed",
                        f"{self.job_key}.route",
                        command_processed,
                        command_target,
                        unit=f"batch-{route_state['batches_committed']}",
                        message=(
                            "checkpoint="
                            f"{batch.last_trade_date}/{batch.last_instrument_id}"
                        ),
                        counters={
                            "routed": int(route_state["routed"]),
                            "shadowed": int(route_state["shadowed"]),
                            "route_failed": int(route_state["route_failed"]),
                            "api_calls": 0,
                        },
                    )
                )
        except KeyboardInterrupt:
            status = "cancelled"
            error_message = "operator cancelled; resume with the same run_id"
            failures.append(JobFailure(str(run_id), "cancelled", error_message))
        except Exception as exc:
            status = "partial_failed" if command_processed else "failed"
            error_message = self._concise_exception(exc)
            failures.append(JobFailure(str(run_id), "route", error_message))

        with active_runtime.engine.connect() as connection:
            remaining = count_bulk_unmatched_route_groups(
                connection,
                date_from=date_from,
                date_to=date_to,
                market=normalized_market,
                asset_types=resolved_assets,
            )
        route_state["groups_total"] = max(
            int(route_state["groups_total"] or 0),
            int(route_state["groups_processed"]) + remaining,
        )
        if status == "success" and remaining == 0:
            checkpoint["phase"] = "validation"
        elif status == "success" and stalled:
            status = "partial_failed" if command_processed else "failed"
            error_message = (
                "route selection stalled while matched groups remain; "
                "resume after reviewing concurrent staging changes"
            )
            failures.append(JobFailure(str(run_id), "route_stalled", error_message))
        elif status == "success" and command_processed >= command_target and remaining > 0:
            status = "partial_failed"
            error_message = "route limit reached; resume with the same run_id"
            failures.append(JobFailure(str(run_id), "limit_reached", error_message))
        if status == "success" and command_route_failed:
            status = "partial_failed"
            error_message = f"{command_route_failed} route row(s) require review"
            failures.append(JobFailure(str(run_id), "route_failed", error_message))

        checkpoint["route"] = route_state
        with active_runtime.engine.begin() as connection:
            identity_quality_check_run_id = route_state.get(
                "identity_quality_check_run_id"
            )
            if identity_quality_check_run_id is not None:
                finish_bulk_route_quality_check(
                    connection,
                    check_run_id=int(identity_quality_check_run_id),
                    status="success" if remaining == 0 else status,
                    issues_found=int(route_state["identity_quality_issue_count"]),
                    error_message=error_message if remaining else None,
                )
            save_reconcile_checkpoint(
                connection,
                run_id=run_id,
                checkpoint=checkpoint,
                status=status,
                rows_fetched=int(checkpoint["classify"]["rows_processed"]),
                rows_inserted=int(route_state["rows_inserted"]),
                rows_updated=int(checkpoint["classify"]["rows_processed"]),
                rows_rejected=self._workflow_rejected_rows(checkpoint),
                error_message=error_message,
                finished=True,
            )
        active_reporter.on_event(
            ProgressEvent(
                "finish",
                f"{self.job_key}.route",
                command_processed,
                command_target,
                message=status,
                counters={
                    "routed": int(route_state["routed"]),
                    "remaining": remaining,
                    "route_failed": int(route_state["route_failed"]),
                    "api_calls": 0,
                },
            )
        )
        return JobResult(
            job=f"{self.job_key}.route",
            status=status,
            run_id=run_id,
            parameters={
                "date_from": date_from,
                "date_to": date_to,
                "market": normalized_market,
                "asset_types": resolved_assets,
                "limit": limit,
                "batch_size": batch_size,
                "execute": True,
            },
            parameter_sources=self._route_parameter_sources(
                asset_types=asset_types,
                limit=limit,
                override_source=override_source,
            ),
            rows_matched=int(route_state["routed"]),
            rows_inserted=int(route_state["rows_inserted"]),
            rows_rejected=(
                int(route_state["shadowed"]) + int(route_state["route_failed"])
            ),
            api_calls=0,
            work_units_total=int(route_state["groups_total"]),
            work_units_completed=int(route_state["groups_processed"]),
            work_units_failed=int(route_state["route_failed"]),
            failures=failures,
            metrics={
                **deepcopy(route_state),
                "remaining_groups": remaining,
                "identity_quality_check_run_id": route_state.get(
                    "identity_quality_check_run_id"
                ),
                "identity_quality_issue_count": int(
                    route_state["identity_quality_issue_count"]
                ),
                "checkpoint_phase": checkpoint["phase"],
                "api_calls": 0,
            },
            error_message=error_message,
        )

    def validate(
        self,
        *,
        date_from: date,
        date_to: date,
        run_id: int,
        market: str = "US",
        asset_types: list[str] | None = None,
        runtime: JobRuntime | None = None,
        override_source: str = "python",
    ) -> JobResult:
        """Run existing daily-price quality checks and close one guided workflow."""
        self._validate(date_from=date_from, date_to=date_to, limit=None, batch_size=1)
        if run_id <= 0:
            raise ValueError("run_id must be positive")
        normalized_market = market.upper()
        resolved_assets = self._asset_types(asset_types)
        active_runtime = runtime or JobRuntime.from_env()
        try:
            with active_runtime.engine.begin() as connection:
                ensure_runtime_schemas(connection)
                state = load_reconcile_run(connection, run_id=run_id)
                checkpoint = state.checkpoint
                assert_reconcile_route_scope(
                    checkpoint,
                    date_from=date_from,
                    date_to=date_to,
                    market=normalized_market,
                    asset_types=resolved_assets,
                )
                if checkpoint["phase"] != "validation":
                    raise ValueError(
                        f"reconcile run {run_id} is in phase "
                        f"{checkpoint['phase']}, not validation"
                    )
                validation = validate_daily_prices(
                    connection,
                    date_from=date_from,
                    date_to=date_to,
                    asset_types=resolved_assets,
                    market=normalized_market,
                )
                quality_run_ids = [
                    summary.check_run_id for summary in validation.table_summaries
                ]
                identity_quality_check_run_id = checkpoint["route"].get(
                    "identity_quality_check_run_id"
                )
                if identity_quality_check_run_id is not None:
                    quality_run_ids.insert(0, int(identity_quality_check_run_id))
                identity_quality_issues = int(
                    checkpoint["route"].get("identity_quality_issue_count", 0)
                )
                quality_issue_count = validation.issues_found + identity_quality_issues
                route_observations = int(
                    checkpoint["route"].get(
                        "observations_selected",
                        int(checkpoint["route"]["routed"])
                        + int(checkpoint["route"]["shadowed"])
                        + int(checkpoint["route"]["route_failed"]),
                    )
                )
                closed_observations = (
                    int(checkpoint["route"]["routed"])
                    + int(checkpoint["route"]["shadowed"])
                    + int(checkpoint["route"]["route_failed"])
                )
                route_closure_ok = (
                    route_observations == closed_observations
                    and int(checkpoint["route"]["rows_inserted"])
                    == int(checkpoint["route"]["routed"])
                )
                checkpoint["validation"] = {
                    "quality_check_run_ids": quality_run_ids,
                    "issue_count": quality_issue_count,
                }
                checkpoint["phase"] = "complete"
                route_failed = int(checkpoint["route"]["route_failed"])
                status = (
                    "success"
                    if quality_issue_count == 0
                    and route_failed == 0
                    and route_closure_ok
                    else "partial_failed"
                )
                error_message = None
                if quality_issue_count or route_failed:
                    error_message = (
                        f"quality_issues={quality_issue_count};"
                        f"route_failed={route_failed}; review retained audit rows"
                    )
                if not route_closure_ok:
                    closure_message = (
                        "route_closure_mismatch:"
                        f"selected={route_observations};"
                        f"closed={closed_observations};"
                        f"canonical={checkpoint['route']['rows_inserted']};"
                        f"routed={checkpoint['route']['routed']}"
                    )
                    error_message = ";".join(
                        value for value in (error_message, closure_message) if value
                    )
                save_reconcile_checkpoint(
                    connection,
                    run_id=run_id,
                    checkpoint=checkpoint,
                    status=status,
                    rows_fetched=int(checkpoint["classify"]["rows_processed"]),
                    rows_inserted=int(checkpoint["route"]["rows_inserted"]),
                    rows_updated=int(checkpoint["classify"]["rows_processed"]),
                    rows_rejected=self._workflow_rejected_rows(checkpoint),
                    error_message=error_message,
                    finished=True,
                )
        except ValueError:
            raise
        except Exception as exc:
            concise = self._concise_exception(exc)
            try:
                with active_runtime.engine.begin() as connection:
                    state = load_reconcile_run(connection, run_id=run_id)
                    save_reconcile_checkpoint(
                        connection,
                        run_id=run_id,
                        checkpoint=state.checkpoint,
                        status="failed",
                        error_message=concise,
                        finished=True,
                    )
            except Exception as checkpoint_exc:
                concise = (
                    f"{concise}; checkpoint_update_failed="
                    f"{self._concise_exception(checkpoint_exc)}"
                )[:1_000]
            return JobResult(
                job=f"{self.job_key}.validate",
                status="failed",
                run_id=run_id,
                parameters={
                    "date_from": date_from,
                    "date_to": date_to,
                    "market": normalized_market,
                    "asset_types": resolved_assets,
                },
                parameter_sources={
                    "date_from": override_source,
                    "date_to": override_source,
                    "market": override_source,
                    "asset_types": (
                        override_source if asset_types is not None else "job_default"
                    ),
                },
                api_calls=0,
                failures=[JobFailure(str(run_id), "quality_validation", concise)],
                error_message=concise,
            )

        return JobResult(
            job=f"{self.job_key}.validate",
            status=status,
            run_id=run_id,
            parameters={
                "date_from": date_from,
                "date_to": date_to,
                "market": normalized_market,
                "asset_types": resolved_assets,
            },
            parameter_sources={
                "date_from": override_source,
                "date_to": override_source,
                "market": override_source,
                "asset_types": override_source if asset_types is not None else "job_default",
            },
            rows_inserted=int(checkpoint["route"]["rows_inserted"]),
            rows_rejected=(
                int(checkpoint["route"]["route_failed"]) + validation.issues_found
            ),
            api_calls=0,
            work_units_total=len(validation.table_summaries)
            + int(identity_quality_check_run_id is not None),
            work_units_completed=len(validation.table_summaries)
            + int(identity_quality_check_run_id is not None),
            work_units_failed=sum(
                summary.issues_found > 0 for summary in validation.table_summaries
            )
            + int(identity_quality_issues > 0)
            + int(not route_closure_ok),
            metrics={
                "quality_check_run_ids": quality_run_ids,
                "quality_issue_count": quality_issue_count,
                "route_failed": int(checkpoint["route"]["route_failed"]),
                "route_observations_selected": route_observations,
                "route_observations_closed": closed_observations,
                "route_closure_ok": route_closure_ok,
                "checkpoint_phase": checkpoint["phase"],
                "api_calls": 0,
            },
            error_message=error_message,
        )

    @staticmethod
    def _route_parameter_sources(
        *,
        asset_types: list[str] | None,
        limit: int | None,
        override_source: str,
    ) -> dict[str, str]:
        return {
            "date_from": override_source,
            "date_to": override_source,
            "market": override_source,
            "asset_types": override_source if asset_types is not None else "job_default",
            "limit": override_source if limit is not None else "job_default",
            "batch_size": override_source,
            "execute": override_source,
        }

    @staticmethod
    def _resume_hint(run_id: int, checkpoint: dict[str, Any]) -> str:
        phase = str(checkpoint["phase"])
        date_args = (
            f"--from {checkpoint['date_from']} --to {checkpoint['date_to']} "
            f"--market {checkpoint['market']}"
        )
        if phase == "classify":
            statuses = ",".join(checkpoint["source_statuses"])
            advanced = (
                " --advanced"
                if set(checkpoint["source_statuses"])
                & ADVANCED_CLASSIFICATION_STATUSES
                else ""
            )
            return (
                "poetry run j21 reconcile bulk-unmatched classify "
                f"{date_args} --statuses {statuses} --run-id {run_id}{advanced}"
            )
        if phase == "route":
            asset_types = checkpoint["route"].get("asset_types") or DEFAULT_ROUTE_ASSET_TYPES
            return (
                "poetry run j21 reconcile bulk-unmatched route "
                f"{date_args} --asset-types {','.join(asset_types)} "
                f"--run-id {run_id} --execute --yes"
            )
        if phase == "validation":
            return (
                "poetry run j21 menu; choose Bulk unmatched -> Resume and enter "
                f"run_id {run_id}"
            )
        return "workflow complete; no resume needed"

    @staticmethod
    def _workflow_rejected_rows(checkpoint: dict[str, Any]) -> int:
        classify = checkpoint["classify"]
        matched = int(classify["target_status_counts"].get("matched", 0))
        classification_rejected = int(classify["rows_processed"]) - matched
        route = checkpoint["route"]
        return (
            classification_rejected
            + int(route["shadowed"])
            + int(route["route_failed"])
        )

    @staticmethod
    def _asset_types(asset_types: list[str] | None) -> list[str]:
        resolved = [value.lower() for value in (asset_types or DEFAULT_ROUTE_ASSET_TYPES)]
        unsupported = sorted(set(resolved) - set(DEFAULT_ROUTE_ASSET_TYPES))
        if unsupported:
            raise ValueError(f"unsupported route asset type(s): {', '.join(unsupported)}")
        return list(dict.fromkeys(resolved))

    @staticmethod
    def _validate(
        *,
        date_from: date,
        date_to: date,
        limit: int | None,
        batch_size: int,
    ) -> None:
        if date_to < date_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

    @staticmethod
    def _concise_exception(exc: Exception) -> str:
        return " ".join(str(exc).split())[:1_000] or exc.__class__.__name__
