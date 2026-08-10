from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

import fdp.intraday.manifest as manifest_module
from fdp.intraday.manifest import ManifestConflictError, publish_intraday_artifact
from fdp.intraday.models import IntradayBar
from fdp.intraday.sessions import NEW_YORK, classify_us_equity_session
from fdp.intraday.storage import write_intraday_parquet


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS system")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS us_share")
        connection.exec_driver_sql(
            "CREATE TABLE us_share.instrument (instrument_id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE system.ingestion_task_run (run_id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE system.intraday_file_manifest (
                manifest_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL, dataset_kind TEXT NOT NULL, source TEXT NOT NULL,
                market TEXT NOT NULL, asset_type TEXT NOT NULL, interval TEXT NOT NULL,
                instrument_id INTEGER NOT NULL, provider_symbol TEXT NOT NULL,
                trade_date DATE NOT NULL, bucket INTEGER NOT NULL,
                storage_path TEXT NOT NULL UNIQUE, content_hash TEXT NOT NULL,
                file_sha256 TEXT NOT NULL, row_count INTEGER NOT NULL,
                file_size_bytes INTEGER NOT NULL, timestamp_min_utc DATETIME NOT NULL,
                timestamp_max_utc DATETIME NOT NULL, schema_version INTEGER NOT NULL,
                status TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (dataset_kind, source, instrument_id, interval, trade_date)
            )
            """
        )
        connection.execute(text("INSERT INTO us_share.instrument VALUES (101)"))
        connection.execute(text("INSERT INTO system.ingestion_task_run VALUES (1)"))
    return engine


def _bar(*, close: str = "100.50000000") -> IntradayBar:
    timestamp = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    return IntradayBar(
        instrument_id=101,
        provider_symbol="AAPL.US",
        timestamp_utc=timestamp,
        trade_date=timestamp.astimezone(NEW_YORK).date(),
        session=classify_us_equity_session(timestamp),
        open=Decimal("100.00000000"),
        high=Decimal("102.00000000"),
        low=Decimal("99.00000000"),
        close=Decimal(close),
        volume=1000,
        transactions=None,
    )


def test_manifest_is_idempotent_and_conflicting_content_is_held(tmp_path: Path) -> None:
    engine = _engine()
    root = tmp_path / "minutes"
    first = write_intraday_parquet([_bar()], root=root)
    inserted = publish_intraday_artifact(engine, run_id=1, artifact=first, data_root=root)
    repeated = publish_intraday_artifact(engine, run_id=1, artifact=first, data_root=root)
    conflict = write_intraday_parquet([_bar(close="101.50000000")], root=root)

    with pytest.raises(ManifestConflictError, match="different verified content"):
        publish_intraday_artifact(engine, run_id=1, artifact=conflict, data_root=root)

    assert inserted.status == "inserted"
    assert repeated.status == "reused"
    assert conflict.absolute_path.exists() is True
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM system.intraday_file_manifest")
        ).scalar_one() == 1


def test_new_file_is_retained_as_recoverable_orphan_when_manifest_transaction_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "minutes"
    artifact = write_intraday_parquet([_bar()], root=root)

    def fail_registration(*args, **kwargs):
        raise RuntimeError("database commit failed")

    original_registration = manifest_module.register_intraday_artifact
    monkeypatch.setattr(manifest_module, "register_intraday_artifact", fail_registration)
    with pytest.raises(RuntimeError, match="database commit failed"):
        publish_intraday_artifact(_engine(), run_id=1, artifact=artifact, data_root=root)
    assert artifact.absolute_path.exists() is True

    engine = _engine()
    monkeypatch.setattr(manifest_module, "register_intraday_artifact", original_registration)
    inserted = publish_intraday_artifact(engine, run_id=1, artifact=artifact, data_root=root)
    assert inserted.status == "inserted"


def test_manifest_recovers_same_content_unique_insert_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    root = tmp_path / "minutes"
    artifact = write_intraday_parquet([_bar()], root=root)
    with engine.begin() as connection:
        manifest_module.register_intraday_artifact(
            connection,
            run_id=1,
            artifact=artifact,
            data_root=root,
        )

    def lose_insert_race(*args, **kwargs):
        raise IntegrityError("INSERT", {}, RuntimeError("duplicate key"))

    monkeypatch.setattr(manifest_module, "register_intraday_artifact", lose_insert_race)
    result = publish_intraday_artifact(engine, run_id=1, artifact=artifact, data_root=root)

    assert result.status == "reused"


def test_manifest_rejects_artifact_metadata_not_bound_to_file(tmp_path: Path) -> None:
    engine = _engine()
    root = tmp_path / "minutes"
    artifact = write_intraday_parquet([_bar()], root=root)
    forged = replace(artifact, provider_symbol="MSFT.US")

    with pytest.raises(ValueError, match="provider_symbol changed"):
        publish_intraday_artifact(engine, run_id=1, artifact=forged, data_root=root)


def test_manifest_rejects_artifact_outside_explicit_data_root(tmp_path: Path) -> None:
    engine = _engine()
    actual_root = tmp_path / "actual"
    artifact = write_intraday_parquet([_bar()], root=actual_root)

    with pytest.raises(ValueError, match="does not match storage_path"):
        publish_intraday_artifact(
            engine,
            run_id=1,
            artifact=artifact,
            data_root=tmp_path / "configured",
        )

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM system.intraday_file_manifest")
        ).scalar_one() == 0
