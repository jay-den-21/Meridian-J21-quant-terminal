from pathlib import Path


def test_daily_task_ledger_migration_adds_identity_lease_and_work_units() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0019_daily_task_ledger.py"
    ).read_text()

    assert 'revision: str = "0019_daily_task_ledger"' in migration
    assert 'down_revision: str | None = "0018_protect_external_a_share"' in migration
    for value in (
        "task_fingerprint",
        "active_resume_key",
        "lease_owner",
        "lease_expires_at",
        "ingestion_task_work_unit",
        "unit_fingerprint",
        "series_fingerprint",
        "work_unit_id",
        "response_hash",
        "quality_status",
    ):
        assert value in migration
    assert "refusing downgrade while durable work-unit evidence exists" in migration
    assert "refusing downgrade while resumable task evidence exists" in migration
