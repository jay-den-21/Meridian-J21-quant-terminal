"""Recoverable MySQL manifest publication for verified intraday files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from pathlib import PurePosixPath
from time import sleep
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from fdp.intraday.schema import INTRADAY_SCHEMA_VERSION
from fdp.intraday.storage import (
    IntradayFileArtifact,
    ParquetValidation,
    validate_intraday_artifact_path,
    validate_intraday_parquet,
)
from fdp.storage.tables import intraday_file_manifest


class ManifestConflictError(RuntimeError):
    """Raised when one instrument/day already points to different content."""


@dataclass(frozen=True)
class ManifestPublishResult:
    manifest_id: int
    status: str


def register_intraday_artifact(
    connection: Connection,
    *,
    run_id: int,
    artifact: IntradayFileArtifact,
    data_root: str | Path,
) -> ManifestPublishResult:
    """Verify one file and insert or reuse its unique manifest identity."""
    validation = validate_intraday_parquet(
        artifact.absolute_path,
        expected_content_hash=artifact.content_hash,
    )
    _validate_artifact_contract(artifact, validation, data_root=data_root)

    identity = (
        intraday_file_manifest.c.dataset_kind == "validation",
        intraday_file_manifest.c.source == artifact.source,
        intraday_file_manifest.c.instrument_id == artifact.instrument_id,
        intraday_file_manifest.c.interval == artifact.interval,
        intraday_file_manifest.c.trade_date == artifact.trade_date,
    )
    existing = connection.execute(
        select(intraday_file_manifest).where(*identity).with_for_update()
    ).mappings().first()
    if existing is not None:
        return _reuse_existing(existing, artifact)

    result = connection.execute(
        intraday_file_manifest.insert().values(
            run_id=run_id,
            dataset_kind="validation",
            source="eodhd",
            market="US",
            asset_type="stock",
            interval="1m",
            instrument_id=validation.instrument_id,
            provider_symbol=validation.provider_symbol,
            trade_date=validation.trade_date,
            bucket=validation.instrument_id % 32,
            storage_path=artifact.storage_path,
            content_hash=validation.content_hash,
            file_sha256=artifact.file_sha256,
            row_count=validation.row_count,
            file_size_bytes=artifact.absolute_path.stat().st_size,
            timestamp_min_utc=validation.timestamp_min_utc.astimezone(UTC).replace(tzinfo=None),
            timestamp_max_utc=validation.timestamp_max_utc.astimezone(UTC).replace(tzinfo=None),
            schema_version=INTRADAY_SCHEMA_VERSION,
            status="published",
        )
    )
    return ManifestPublishResult(int(result.inserted_primary_key[0]), "inserted")


def publish_intraday_artifact(
    engine: Engine,
    *,
    run_id: int,
    artifact: IntradayFileArtifact,
    data_root: str | Path,
) -> ManifestPublishResult:
    """Register one immutable artifact, recovering a concurrent same-content insert."""
    for attempt in range(3):
        try:
            with engine.begin() as connection:
                return register_intraday_artifact(
                    connection,
                    run_id=run_id,
                    artifact=artifact,
                    data_root=data_root,
                )
        except (IntegrityError, OperationalError) as exc:
            recovered = _recover_concurrent_publish(engine, artifact, exc)
            if recovered is not None:
                return recovered
            if not _is_database_write_race(exc) or attempt == 2:
                raise
            sleep(0.05 * (attempt + 1))
    raise RuntimeError("intraday manifest retry loop exited unexpectedly")


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_artifact_contract(
    artifact: IntradayFileArtifact,
    validation: ParquetValidation,
    *,
    data_root: str | Path,
) -> None:
    relative_path = PurePosixPath(artifact.storage_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("intraday manifest storage_path must be a safe relative path")
    validate_intraday_artifact_path(
        artifact.absolute_path,
        artifact.storage_path,
        root=data_root,
    )
    if (artifact.source, artifact.asset_type, artifact.interval) != (
        "eodhd",
        "stock",
        "1m",
    ):
        raise ValueError("intraday artifact metadata is outside the validation contract")
    if artifact.schema_version != INTRADAY_SCHEMA_VERSION:
        raise ValueError("intraday artifact schema_version is outside the validation contract")
    expected_path = PurePosixPath(
        "validation",
        f"source={artifact.source}",
        f"asset_type={artifact.asset_type}",
        f"interval={artifact.interval}",
        f"trade_date={artifact.trade_date.isoformat()}",
        f"bucket={artifact.bucket:02d}",
        f"part-{artifact.content_hash}.parquet",
    )
    if relative_path != expected_path:
        raise ValueError("intraday artifact storage_path does not match its metadata")
    comparisons = {
        "row_count": (validation.row_count, artifact.row_count),
        "instrument_id": (validation.instrument_id, artifact.instrument_id),
        "provider_symbol": (validation.provider_symbol, artifact.provider_symbol),
        "trade_date": (validation.trade_date, artifact.trade_date),
        "timestamp_min_utc": (
            validation.timestamp_min_utc.astimezone(UTC),
            artifact.timestamp_min_utc.astimezone(UTC),
        ),
        "timestamp_max_utc": (
            validation.timestamp_max_utc.astimezone(UTC),
            artifact.timestamp_max_utc.astimezone(UTC),
        ),
        "bucket": (artifact.instrument_id % 32, artifact.bucket),
        "file_size_bytes": (artifact.absolute_path.stat().st_size, artifact.file_size_bytes),
    }
    for field, (actual, expected) in comparisons.items():
        if actual != expected:
            raise ValueError(f"intraday artifact {field} changed before manifest registration")
    if _sha256(artifact.absolute_path) != artifact.file_sha256:
        raise ValueError("intraday artifact file checksum changed before manifest registration")


def _reuse_existing(
    existing: Mapping[str, Any],
    artifact: IntradayFileArtifact,
) -> ManifestPublishResult:
    expected = {
        "dataset_kind": "validation",
        "source": artifact.source,
        "market": "US",
        "asset_type": artifact.asset_type,
        "interval": artifact.interval,
        "instrument_id": artifact.instrument_id,
        "provider_symbol": artifact.provider_symbol,
        "trade_date": artifact.trade_date,
        "bucket": artifact.bucket,
        "storage_path": artifact.storage_path,
        "content_hash": artifact.content_hash,
        "file_sha256": artifact.file_sha256,
        "row_count": artifact.row_count,
        "file_size_bytes": artifact.file_size_bytes,
        "timestamp_min_utc": artifact.timestamp_min_utc.astimezone(UTC).replace(tzinfo=None),
        "timestamp_max_utc": artifact.timestamp_max_utc.astimezone(UTC).replace(tzinfo=None),
        "schema_version": artifact.schema_version,
        "status": "published",
    }
    mismatched = [
        field
        for field, expected_value in expected.items()
        if _manifest_value(existing[field]) != expected_value
    ]
    if mismatched:
        raise ManifestConflictError(
            "intraday manifest identity already contains different verified content: "
            f"instrument_id={artifact.instrument_id} trade_date={artifact.trade_date} "
            f"fields={','.join(mismatched)}"
        )
    return ManifestPublishResult(int(existing["manifest_id"]), "reused")


def _manifest_value(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _recover_concurrent_publish(
    engine: Engine,
    artifact: IntradayFileArtifact,
    error: IntegrityError | OperationalError,
) -> ManifestPublishResult | None:
    with engine.connect() as connection:
        existing = connection.execute(
            select(intraday_file_manifest).where(
                intraday_file_manifest.c.dataset_kind == "validation",
                intraday_file_manifest.c.source == artifact.source,
                intraday_file_manifest.c.instrument_id == artifact.instrument_id,
                intraday_file_manifest.c.interval == artifact.interval,
                intraday_file_manifest.c.trade_date == artifact.trade_date,
            )
        ).mappings().first()
        if existing is not None:
            return _reuse_existing(existing, artifact)
        path_owner = connection.execute(
            select(intraday_file_manifest.c.manifest_id).where(
                intraday_file_manifest.c.storage_path == artifact.storage_path
            )
        ).scalar_one_or_none()
        if path_owner is not None:
            raise ManifestConflictError(
                "intraday storage path is already registered to a different identity: "
                f"storage_path={artifact.storage_path}"
            ) from error
    return None


def _is_database_write_race(error: IntegrityError | OperationalError) -> bool:
    arguments = getattr(error.orig, "args", ())
    if isinstance(error, IntegrityError) and not arguments:
        return False
    return bool(arguments and arguments[0] in {1062, 1205, 1213})
