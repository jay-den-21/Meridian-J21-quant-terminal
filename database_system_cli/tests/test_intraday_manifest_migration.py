from pathlib import Path


def test_intraday_manifest_migration_has_single_file_identity_and_safe_downgrade() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0020_intraday_file_manifest.py"
    ).read_text()

    assert 'revision: str = "0020_intraday_manifest"' in migration
    assert 'down_revision: str | None = "0019_daily_task_ledger"' in migration
    for value in (
        "intraday_file_manifest",
        "uq_intraday_manifest_identity",
        "uq_intraday_manifest_storage_path",
        "content_hash",
        "file_sha256",
        "timestamp_min_utc",
        "timestamp_max_utc",
        "schema_version",
        "_validate_existing_table",
        "_ensure_indexes",
        "ix_intraday_manifest_run_id",
        "ix_intraday_manifest_symbol_date",
        "fk_intraday_manifest_run",
        "fk_intraday_manifest_instrument",
        'columns["manifest_id"].get("autoincrement")',
        '"current_timestamp" not in default',
    ):
        assert value in migration
    assert "refusing downgrade while intraday manifest evidence exists" in migration
