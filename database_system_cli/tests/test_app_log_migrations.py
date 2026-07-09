from pathlib import Path


VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


APP_LOG_TABLES = {
    "app_request_run",
    "instrument_search_snapshot",
    "instrument_search_result",
    "screener_snapshot",
    "screener_snapshot_member",
    "quote_snapshot",
    "live_ohlcv_snapshot",
    "websocket_event",
}


LEGACY_SNAPSHOT_TABLES = APP_LOG_TABLES - {"app_request_run"}


def test_app_log_snapshot_migration_creates_log_schema_without_instrument_fk() -> None:
    migration = (VERSIONS / "0010_create_app_log_snapshot_schema.py").read_text()

    assert 'revision: str = "0010_app_log_snapshots"' in migration
    assert 'down_revision: str | None = "0009_bulk_unmatched"' in migration
    assert "CREATE SCHEMA IF NOT EXISTS app_log" in migration
    for table_name in APP_LOG_TABLES:
        assert f"app_log.{table_name}" in migration

    assert "REFERENCES us_share.instrument" not in migration
    assert "instrument_id BIGINT NULL" in migration


def test_legacy_snapshot_drop_migration_verifies_counts_before_drop() -> None:
    migration = (VERSIONS / "0011_drop_legacy_us_share_snapshots.py").read_text()

    assert 'revision: str = "0011_drop_us_share_snapshots"' in migration
    assert 'down_revision: str | None = "0010_app_log_snapshots"' in migration
    assert "_assert_copy_count_matches(table_name)" in migration
    assert "DROP TABLE IF EXISTS {LEGACY_SCHEMA}.{table_name}" in migration
    for table_name in LEGACY_SNAPSHOT_TABLES:
        assert f'"{table_name}"' in migration
