from pathlib import Path


def test_guided_reconcile_migration_is_resumable_and_online() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0016_guided_bulk_reconcile.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | None = "0015_id_mapping_ingest"' in migration
    assert '"checkpoint_json" not in _column_names' in migration
    assert '"last_classified_run_id" not in _column_names' in migration
    assert "instrument_identity_resolution_audit" in migration
    assert "ix_bulk_unmatched_market_status_date_id" in migration
    assert "CLASSIFY_INDEX_COLUMNS" in migration
    assert "refusing incompatible" in migration
    assert "actual_classify_columns != CLASSIFY_INDEX_COLUMNS" in migration
    assert "ALGORITHM=INPLACE, LOCK=NONE" in migration
    assert "online index creation did not create" in migration
    assert "refusing downgrade while identity resolution audit evidence exists" in migration
    assert "refusing downgrade while reconcile checkpoints exist" in migration
    assert "refusing downgrade while classify run markers exist" in migration
