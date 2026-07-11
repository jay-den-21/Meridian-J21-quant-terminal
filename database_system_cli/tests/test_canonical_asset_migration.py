from pathlib import Path


VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def test_canonical_asset_migration_adds_fund_and_adopts_existing_daily_tables() -> None:
    migration = (VERSIONS / "0012_canonical_asset_daily_tables.py").read_text()

    assert 'revision: str = "0012_canonical_asset_daily_tables"' in migration
    assert 'down_revision: str | None = "0011_drop_us_share_snapshots"' in migration
    assert '_ensure_daily_price_table("fund", volume_nullable=False)' in migration
    assert '_ensure_daily_price_table("forex", volume_nullable=True)' in migration
    assert '_ensure_daily_price_table("crypto", volume_nullable=False)' in migration
    assert '_create_instrument_view("fund")' in migration
    assert "refusing downgrade while canonical daily tables contain data" in migration


def test_fund_split_run_migration_tracks_backup_and_checkpoints() -> None:
    migration = (VERSIONS / "0013_fund_daily_price_split_run.py").read_text()

    assert 'revision: str = "0013_fund_daily_price_split_run"' in migration
    assert 'down_revision: str | None = "0012_canonical_asset_daily_tables"' in migration
    for column in (
        "copy_last_source_id",
        "delete_last_source_id",
        "backup_sha256",
        "verification_fingerprint",
    ):
        assert f'"{column}"' in migration
    assert "refusing downgrade while fund daily-price split runs exist" in migration
