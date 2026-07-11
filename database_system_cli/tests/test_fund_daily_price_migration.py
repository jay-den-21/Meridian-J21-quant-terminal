from contextlib import nullcontext
import gzip
import hashlib
from pathlib import Path
from typing import Any

import pytest

import fdp.migrate.fund_daily_price as migration


class ScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class PlanConnection:
    def __init__(self, values: list[int]) -> None:
        self.values = iter(values)

    def execute(self, statement, parameters=None) -> ScalarResult:
        return ScalarResult(next(self.values))


class NoopConnection:
    def execute(self, statement, parameters=None) -> object:
        return object()


class FakeEngine:
    def __init__(self) -> None:
        self.connection = NoopConnection()
        self.begin_count = 0

    def begin(self):
        self.begin_count += 1
        return nullcontext(self.connection)

    def connect(self):
        return nullcontext(self.connection)


def _run_record(**overrides: Any) -> dict[str, Any]:
    base = {
        "fund_split_run_id": 7,
        "status": "copying",
        "source_total_before": 100,
        "source_fund_rows": 10,
        "target_rows_before": 0,
        "rows_copied": 0,
        "rows_deleted": 0,
        "copy_last_source_id": 0,
        "delete_last_source_id": 0,
        "chunk_size": 10,
        "backup_path": "/tmp/fund.sql.gz",
        "backup_size_bytes": 123,
        "backup_sha256": "a" * 64,
        "verification_fingerprint": "b" * 64,
        "verification_details": '{"source_sample_rows": 1, "source_sample_checksum": 2}',
    }
    base.update(overrides)
    return base


def test_plan_reports_exact_split_readiness_counts() -> None:
    plan = migration.plan_fund_daily_prices(PlanConnection([100, 40, 0, 0, 0]))

    assert plan.source_total_rows == 100
    assert plan.source_fund_rows == 40
    assert plan.ready is True


def test_backup_validation_reads_gzip_and_hashes_uncompressed_sql(tmp_path: Path) -> None:
    backup = tmp_path / "fund.sql.gz"
    sql = b"CREATE TABLE fund_daily_price (id BIGINT);\n"
    with gzip.open(backup, "wb") as stream:
        stream.write(sql)

    evidence = migration.validate_backup_file(backup.resolve())

    assert evidence.size_bytes == backup.stat().st_size
    assert evidence.sha256 == hashlib.sha256(sql).hexdigest()


def test_backup_validation_rejects_relative_and_corrupt_gzip(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute path"):
        migration.validate_backup_file(Path("relative.sql.gz"))

    backup = tmp_path / "broken.sql.gz"
    backup.write_bytes(b"not gzip")
    with pytest.raises(ValueError, match="integrity validation"):
        migration.validate_backup_file(backup.resolve())


def test_copy_stops_at_max_chunks_and_preserves_resume_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    run = _run_record()
    monkeypatch.setattr(migration, "_load_run", lambda *args, **kwargs: run)
    prepared: list[bool] = []
    monkeypatch.setattr(migration, "_prepare_target_for_copy", lambda engine: prepared.append(True))
    monkeypatch.setattr(migration, "_next_source_id", lambda *args, **kwargs: 25)
    monkeypatch.setattr(migration, "_copy_source_range", lambda *args, **kwargs: 10)

    result = migration.copy_fund_daily_prices(
        engine,
        run_id=7,
        chunk_size=10,
        max_chunks=1,
    )

    assert result.status == "copying"
    assert result.chunks_completed == 1
    assert engine.begin_count == 1
    assert prepared == [True]


def test_finalize_resume_does_not_reapply_pre_delete_fingerprint_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    run = _run_record(status="finalizing")
    monkeypatch.setattr(migration, "_load_run", lambda *args, **kwargs: run)
    monkeypatch.setattr(
        migration,
        "validate_backup_file",
        lambda path: migration.BackupEvidence(path, 123, "a" * 64),
    )
    monkeypatch.setattr(
        migration,
        "_pre_finalize_details",
        lambda connection: (_ for _ in ()).throw(AssertionError("stale precheck")),
    )
    monkeypatch.setattr(migration, "_next_source_id", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration, "_post_finalize_details", lambda *args: {"ok": 1})
    monkeypatch.setattr(migration, "_post_finalize_passed", lambda *args: True)

    result = migration.finalize_fund_daily_prices(engine, run_id=7)

    assert result.status == "completed"
    assert result.verification.passed is True


def test_pre_and_post_finalize_invariants_are_strict() -> None:
    run = _run_record()
    pre = {
        "source_total_rows": 100,
        "source_fund_rows": 10,
        "source_unexpected_rows": 0,
        "target_total_rows": 10,
        "target_non_fund_rows": 0,
        "source_duplicate_groups": 0,
        "target_duplicate_groups": 0,
        "missing_target_rows": 0,
        "extra_target_rows": 0,
        "source_sample_rows": 2,
        "source_sample_checksum": 99,
        "target_sample_rows": 2,
        "target_sample_checksum": 99,
    }
    post = {
        "source_total_rows": 90,
        "source_fund_rows": 0,
        "source_unexpected_rows": 0,
        "target_total_rows": 10,
        "target_non_fund_rows": 0,
        "source_duplicate_groups": 0,
        "target_duplicate_groups": 0,
        "conserved_total_rows": 100,
        "baseline_total_rows": 100,
        "target_sample_rows": 2,
        "expected_target_sample_rows": 2,
        "target_sample_checksum": 99,
        "expected_target_sample_checksum": 99,
    }

    assert migration._pre_finalize_passed(pre, run) is True
    assert migration._post_finalize_passed(post, run) is True
    pre["missing_target_rows"] = 1
    post["conserved_total_rows"] = 99
    assert migration._pre_finalize_passed(pre, run) is False
    assert migration._post_finalize_passed(post, run) is False
