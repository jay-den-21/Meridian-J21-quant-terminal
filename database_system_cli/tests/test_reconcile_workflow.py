from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest

import fdp.get_data.reconcile.bulk_unmatched as reconcile_module
from fdp.bulk_unmatched import (
    BulkUnmatchedClassifyBatchResult,
    BulkUnmatchedRouteFailure,
    BulkUnmatchedRouteResult,
)
from fdp.get_data.reconcile import BulkUnmatchedReconcileJob
from fdp.get_data.reconcile.workflow import (
    assert_reconcile_route_scope,
    new_reconcile_checkpoint,
    new_route_reconcile_checkpoint,
    parse_reconcile_checkpoint,
)


class FakeEngine:
    def __init__(self, *, fail_after_begin_calls: set[int] | None = None) -> None:
        self.connections: list[object] = []
        self.begin_calls = 0
        self.fail_after_begin_calls = fail_after_begin_calls or set()

    @contextmanager
    def begin(self):
        self.begin_calls += 1
        call_number = self.begin_calls
        connection = object()
        self.connections.append(connection)
        yield connection
        if call_number in self.fail_after_begin_calls:
            raise RuntimeError("simulated commit failure")

    @contextmanager
    def connect(self):
        connection = object()
        self.connections.append(connection)
        yield connection


def test_checkpoint_records_both_phase_cursors_and_aggregates() -> None:
    checkpoint = new_reconcile_checkpoint(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 3),
        market="US",
        source_statuses=["unresolved", "unknown"],
        status_counts={"unresolved": 10, "unknown": 2},
        snapshot_max_by_status={"unresolved": 100, "unknown": 120},
    )

    assert checkpoint["classify"]["last_observation_id"] == 0
    assert checkpoint["route"]["last_instrument_id"] is None
    assert checkpoint["route"]["last_trade_date"] is None
    assert checkpoint["route"]["groups_processed"] == 0
    assert checkpoint["route"]["observations_selected"] == 0
    assert checkpoint["validation"]["quality_check_run_ids"] == []


def test_route_resume_rejects_changed_asset_scope() -> None:
    checkpoint = new_route_reconcile_checkpoint(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 3),
        market="US",
        asset_types=["stock", "etf"],
    )

    with pytest.raises(ValueError, match="asset_types do not match"):
        assert_reconcile_route_scope(
            checkpoint,
            date_from=date(2024, 1, 2),
            date_to=date(2024, 1, 3),
            market="US",
            asset_types=["stock"],
        )


def test_checkpoint_parser_rejects_missing_phase_sections() -> None:
    checkpoint = new_reconcile_checkpoint(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 3),
        market="US",
        source_statuses=["unresolved"],
        status_counts={"unresolved": 1},
        snapshot_max_by_status={"unresolved": 1},
    )
    del checkpoint["route"]

    with pytest.raises(ValueError, match=r"missing fields: \['route'\]"):
        parse_reconcile_checkpoint(checkpoint)


def _configure_classify_job(
    monkeypatch: pytest.MonkeyPatch,
    *,
    engine: FakeEngine,
    status_count: int,
    batch: BulkUnmatchedClassifyBatchResult | None,
) -> tuple[BulkUnmatchedReconcileJob, list[dict[str, object]]]:
    job = BulkUnmatchedReconcileJob()
    preflight = SimpleNamespace(
        parameters={
            "status_counts": {"unresolved": status_count},
            "snapshot_max_by_status": {"unresolved": status_count},
        }
    )
    monkeypatch.setattr(job, "preflight", lambda **kwargs: preflight)
    monkeypatch.setattr(reconcile_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(reconcile_module, "create_reconcile_run", lambda connection, checkpoint: 71)
    monkeypatch.setattr(
        reconcile_module.DatedInstrumentIdentityResolver,
        "from_connection",
        lambda connection, **kwargs: object(),
    )
    if batch is not None:
        monkeypatch.setattr(
            reconcile_module,
            "classify_bulk_unmatched_batch",
            lambda connection, **kwargs: batch,
        )
    saved: list[dict[str, object]] = []

    def fake_save(connection, **kwargs):
        saved.append(
            {
                "checkpoint": deepcopy(kwargs["checkpoint"]),
                "status": kwargs.get("status", "running"),
            }
        )

    monkeypatch.setattr(reconcile_module, "save_reconcile_checkpoint", fake_save)
    return job, saved


def test_classify_exact_last_batch_advances_to_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    job, _ = _configure_classify_job(
        monkeypatch,
        engine=engine,
        status_count=1,
        batch=BulkUnmatchedClassifyBatchResult(
            source_status="unresolved",
            scanned=1,
            updated=1,
            target_status_counts={"matched": 1},
            last_observation_id=9,
            last_trade_date=date(2024, 1, 2),
        ),
    )

    result = job.classify(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        runtime=SimpleNamespace(engine=engine),
    )

    assert result.status == "success"
    assert result.work_units_completed == 1
    assert result.metrics["remaining_eligible"] == 0
    assert result.metrics["checkpoint_phase"] == "route"


def test_classify_empty_snapshot_advances_without_querying_a_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    job, _ = _configure_classify_job(
        monkeypatch,
        engine=engine,
        status_count=0,
        batch=None,
    )
    monkeypatch.setattr(
        reconcile_module,
        "classify_bulk_unmatched_batch",
        lambda connection, **kwargs: pytest.fail("empty snapshot must not query a batch"),
    )

    result = job.classify(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        runtime=SimpleNamespace(engine=engine),
    )

    assert result.status == "success"
    assert result.metrics["checkpoint_phase"] == "route"


def test_classify_commit_failure_does_not_persist_uncommitted_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(fail_after_begin_calls={2})
    job, saved = _configure_classify_job(
        monkeypatch,
        engine=engine,
        status_count=1,
        batch=BulkUnmatchedClassifyBatchResult(
            source_status="unresolved",
            scanned=1,
            updated=1,
            target_status_counts={"matched": 1},
            last_observation_id=9,
            last_trade_date=date(2024, 1, 2),
        ),
    )

    result = job.classify(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        runtime=SimpleNamespace(engine=engine),
    )

    assert result.status == "failed"
    assert result.work_units_completed == 0
    assert saved[-1]["checkpoint"]["classify"]["last_observation_id"] == 0
    assert saved[-1]["checkpoint"]["classify"]["rows_processed"] == 0


def test_route_job_commits_each_batch_with_its_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    runtime = SimpleNamespace(engine=engine)
    counts = iter([2, 0])
    route_connections: list[object] = []
    checkpoint_connections: list[object] = []
    routed_batches = iter([
        BulkUnmatchedRouteResult(
            dry_run=False,
            routeable=1,
            rows_inserted=1,
            rows_rejected=0,
            routed=1,
            groups_selected=1,
            identity_audits=1,
            last_instrument_id=10,
            last_trade_date=date(2024, 1, 2),
        ),
        BulkUnmatchedRouteResult(
            dry_run=False,
            routeable=1,
            rows_inserted=1,
            rows_rejected=0,
            routed=1,
            groups_selected=1,
            identity_audits=1,
            last_instrument_id=11,
            last_trade_date=date(2024, 1, 2),
        ),
    ])

    monkeypatch.setattr(reconcile_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(reconcile_module, "create_reconcile_run", lambda connection, checkpoint: 71)
    monkeypatch.setattr(
        reconcile_module,
        "count_bulk_unmatched_route_groups",
        lambda connection, **kwargs: next(counts),
    )

    def fake_route(connection, **kwargs):
        route_connections.append(connection)
        assert kwargs["run_id"] == 71
        assert kwargs["limit"] == 1
        return next(routed_batches)

    def fake_save(connection, **kwargs):
        checkpoint_connections.append(connection)

    monkeypatch.setattr(reconcile_module, "route_bulk_unmatched_observations", fake_route)
    monkeypatch.setattr(reconcile_module, "save_reconcile_checkpoint", fake_save)

    result = BulkUnmatchedReconcileJob().route(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        batch_size=1,
        execute=True,
        runtime=runtime,
    )

    assert result.status == "success"
    assert result.run_id == 71
    assert result.work_units_completed == 2
    assert result.metrics["checkpoint_phase"] == "validation"
    assert route_connections == checkpoint_connections[:2]
    assert result.api_calls == 0


def test_route_commit_failure_keeps_last_committed_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(fail_after_begin_calls={2})
    runtime = SimpleNamespace(engine=engine)
    counts = iter([1, 1])
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(reconcile_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(reconcile_module, "create_reconcile_run", lambda connection, checkpoint: 71)
    monkeypatch.setattr(
        reconcile_module,
        "count_bulk_unmatched_route_groups",
        lambda connection, **kwargs: next(counts),
    )
    monkeypatch.setattr(
        reconcile_module,
        "route_bulk_unmatched_observations",
        lambda connection, **kwargs: BulkUnmatchedRouteResult(
            dry_run=False,
            routeable=1,
            rows_inserted=1,
            rows_rejected=0,
            routed=1,
            groups_selected=1,
            identity_audits=1,
            last_instrument_id=10,
            last_trade_date=date(2024, 1, 2),
        ),
    )

    def fake_save(connection, **kwargs):
        saved.append(deepcopy(kwargs["checkpoint"]))

    monkeypatch.setattr(reconcile_module, "save_reconcile_checkpoint", fake_save)

    result = BulkUnmatchedReconcileJob().route(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        batch_size=1,
        execute=True,
        runtime=runtime,
    )

    assert result.status == "failed"
    assert result.work_units_completed == 0
    assert saved[-1]["route"]["groups_processed"] == 0
    assert saved[-1]["route"]["rows_inserted"] == 0


def test_route_reports_stall_when_count_and_batch_selection_disagree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    runtime = SimpleNamespace(engine=engine)
    counts = iter([1, 1])
    monkeypatch.setattr(reconcile_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(reconcile_module, "create_reconcile_run", lambda connection, checkpoint: 71)
    monkeypatch.setattr(
        reconcile_module,
        "count_bulk_unmatched_route_groups",
        lambda connection, **kwargs: next(counts),
    )
    monkeypatch.setattr(
        reconcile_module,
        "route_bulk_unmatched_observations",
        lambda connection, **kwargs: BulkUnmatchedRouteResult(
            dry_run=False,
            routeable=0,
            rows_inserted=0,
            rows_rejected=0,
            routed=0,
        ),
    )
    monkeypatch.setattr(reconcile_module, "save_reconcile_checkpoint", lambda *args, **kwargs: None)

    result = BulkUnmatchedReconcileJob().route(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        batch_size=1,
        execute=True,
        runtime=runtime,
    )

    assert result.status == "failed"
    assert result.metrics["remaining_groups"] == 1
    assert result.failures[0].category == "route_stalled"


def test_route_conflict_issue_and_checkpoint_share_the_batch_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    runtime = SimpleNamespace(engine=engine)
    counts = iter([1, 0])
    route_connections: list[object] = []
    issue_connections: list[object] = []
    checkpoint_connections: list[object] = []
    monkeypatch.setattr(reconcile_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(reconcile_module, "create_reconcile_run", lambda connection, checkpoint: 71)
    monkeypatch.setattr(
        reconcile_module,
        "count_bulk_unmatched_route_groups",
        lambda connection, **kwargs: next(counts),
    )

    def fake_route(connection, **kwargs):
        route_connections.append(connection)
        return BulkUnmatchedRouteResult(
            dry_run=False,
            routeable=1,
            rows_inserted=0,
            rows_rejected=1,
            routed=0,
            observations_selected=1,
            groups_selected=1,
            route_failed=1,
            last_instrument_id=10,
            last_trade_date=date(2024, 1, 2),
            route_failures=(
                BulkUnmatchedRouteFailure(
                    observation_id=9,
                    instrument_id=10,
                    symbol="OLD",
                    provider_symbol="OLD.US",
                    trade_date=date(2024, 1, 2),
                    asset_type="stock",
                    reason="canonical_provider_symbol_conflict",
                ),
            ),
        )

    def fake_record(connection, **kwargs):
        issue_connections.append(connection)
        return len(kwargs["failures"])

    monkeypatch.setattr(reconcile_module, "route_bulk_unmatched_observations", fake_route)
    monkeypatch.setattr(
        reconcile_module,
        "create_bulk_route_quality_check",
        lambda connection, **kwargs: 301,
    )
    monkeypatch.setattr(reconcile_module, "record_bulk_route_quality_issues", fake_record)
    monkeypatch.setattr(
        reconcile_module,
        "finish_bulk_route_quality_check",
        lambda connection, **kwargs: None,
    )
    monkeypatch.setattr(
        reconcile_module,
        "save_reconcile_checkpoint",
        lambda connection, **kwargs: checkpoint_connections.append(connection),
    )

    result = BulkUnmatchedReconcileJob().route(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        batch_size=1,
        execute=True,
        runtime=runtime,
    )

    assert result.status == "partial_failed"
    assert result.metrics["identity_quality_check_run_id"] == 301
    assert result.metrics["identity_quality_issue_count"] == 1
    assert route_connections == issue_connections
    assert route_connections == checkpoint_connections[:1]


def test_validation_marks_route_count_closure_mismatch_partial_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    checkpoint = new_route_reconcile_checkpoint(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        market="US",
        asset_types=["stock"],
    )
    checkpoint["phase"] = "validation"
    checkpoint["route"].update(
        {
            "observations_selected": 2,
            "routed": 1,
            "shadowed": 0,
            "route_failed": 0,
            "rows_inserted": 1,
        }
    )
    monkeypatch.setattr(reconcile_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(
        reconcile_module,
        "load_reconcile_run",
        lambda connection, run_id: SimpleNamespace(checkpoint=deepcopy(checkpoint)),
    )
    monkeypatch.setattr(
        reconcile_module,
        "validate_daily_prices",
        lambda connection, **kwargs: SimpleNamespace(
            issues_found=0,
            table_summaries=[],
        ),
    )
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(
        reconcile_module,
        "save_reconcile_checkpoint",
        lambda connection, **kwargs: saved.append(kwargs),
    )

    result = BulkUnmatchedReconcileJob().validate(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        run_id=71,
        asset_types=["stock"],
        runtime=SimpleNamespace(engine=engine),
    )

    assert result.status == "partial_failed"
    assert result.metrics["route_closure_ok"] is False
    assert "route_closure_mismatch" in str(result.error_message)
    assert saved[-1]["status"] == "partial_failed"


def test_validation_returns_original_failure_when_failure_checkpoint_cannot_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(fail_after_begin_calls={1, 2})
    checkpoint = new_route_reconcile_checkpoint(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        market="US",
        asset_types=["stock"],
    )
    checkpoint["phase"] = "validation"
    monkeypatch.setattr(reconcile_module, "ensure_runtime_schemas", lambda connection: None)
    monkeypatch.setattr(
        reconcile_module,
        "load_reconcile_run",
        lambda connection, run_id: SimpleNamespace(checkpoint=deepcopy(checkpoint)),
    )
    monkeypatch.setattr(
        reconcile_module,
        "validate_daily_prices",
        lambda connection, **kwargs: SimpleNamespace(
            issues_found=0,
            table_summaries=[],
        ),
    )
    monkeypatch.setattr(
        reconcile_module,
        "save_reconcile_checkpoint",
        lambda connection, **kwargs: None,
    )

    result = BulkUnmatchedReconcileJob().validate(
        date_from=date(2024, 1, 2),
        date_to=date(2024, 1, 2),
        run_id=71,
        asset_types=["stock"],
        runtime=SimpleNamespace(engine=engine),
    )

    assert result.status == "failed"
    assert "simulated commit failure" in str(result.error_message)
    assert "checkpoint_update_failed" in str(result.error_message)
