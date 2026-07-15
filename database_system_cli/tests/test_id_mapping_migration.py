from pathlib import Path


def test_id_mapping_migration_is_null_safe_and_preserves_unmatched_evidence() -> None:
    migration = (
        Path(__file__).parents[1] / "alembic" / "versions" / "0015_id_mapping_ingest.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | None = "0014_fund_compact_swap"' in migration
    assert "newer.valid_from <=> older.valid_from" in migration
    assert "newer.valid_to <=> older.valid_to" in migration
    assert "valid_from_key" in migration
    assert "coalesce(valid_from, '1000-01-01')" in migration
    assert "ix_identifier_history_instrument" in migration
    assert "if \"valid_from_key\" not in _column_names" in migration
    assert "if not _has_table(bind, UNMATCHED_TABLE, UNMATCHED_SCHEMA)" in migration
    assert "identifier_mapping_unmatched_observation" in migration
    assert "refusing downgrade while identifier mapping unmatched evidence exists" in migration
