"""Deterministic, verified Parquet publication for one-minute bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Iterable

import pyarrow as pa
import pyarrow.parquet as pq

from fdp.config import intraday_data_root_from_env
from fdp.intraday.models import IntradayBar
from fdp.intraday.schema import INTRADAY_BAR_SCHEMA, INTRADAY_SCHEMA_VERSION
from fdp.intraday.sessions import NEW_YORK, classify_us_equity_session

BUCKET_COUNT = 32
SUPPORTED_SOURCE = "eodhd"
SUPPORTED_ASSET_TYPE = "stock"
SUPPORTED_INTERVAL = "1m"


@dataclass(frozen=True)
class ParquetValidation:
    row_count: int
    content_hash: str
    timestamp_min_utc: datetime
    timestamp_max_utc: datetime
    instrument_id: int
    provider_symbol: str
    trade_date: date


@dataclass(frozen=True)
class IntradayFileArtifact:
    absolute_path: Path
    storage_path: str
    content_hash: str
    file_sha256: str
    row_count: int
    file_size_bytes: int
    timestamp_min_utc: datetime
    timestamp_max_utc: datetime
    instrument_id: int
    provider_symbol: str
    trade_date: date
    bucket: int
    source: str
    asset_type: str
    interval: str
    schema_version: int
    created: bool


def resolve_intraday_data_root(
    root: str | Path | None = None,
    *,
    create: bool = False,
) -> Path:
    """Validate the explicit repo-external root and optionally create it."""
    candidate = Path(root).expanduser() if root is not None else intraday_data_root_from_env()
    if not candidate.is_absolute():
        raise ValueError("J21_INTRADAY_DATA_ROOT must be an absolute path")
    if candidate.is_symlink():
        raise ValueError("J21_INTRADAY_DATA_ROOT must not be a symlink")
    resolved = candidate.resolve(strict=False)
    project_root = Path(__file__).resolve().parents[3]
    unsafe_exact = {Path("/"), Path.home().resolve(), project_root}
    if resolved in unsafe_exact or project_root in resolved.parents:
        raise ValueError(
            "J21_INTRADAY_DATA_ROOT must be a dedicated directory outside the repository"
        )
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("J21_INTRADAY_DATA_ROOT must identify a directory")
    if create:
        resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def write_intraday_parquet(
    bars: Iterable[IntradayBar],
    *,
    root: str | Path | None = None,
) -> IntradayFileArtifact:
    """Write one instrument/day partition and return verified file metadata."""
    normalized = sorted(bars, key=lambda bar: bar.natural_key)
    identity = _validate_bar_batch(normalized)
    data_root = resolve_intraday_data_root(root, create=True)
    table = pa.Table.from_pylist(
        [_bar_record(bar) for bar in normalized],
        schema=INTRADAY_BAR_SCHEMA,
    )
    content_hash = _content_hash_from_records(table.to_pylist())
    instrument_id, provider_symbol, trade_date_value = identity
    bucket = instrument_id % BUCKET_COUNT
    directory = (
        data_root
        / "validation"
        / f"source={SUPPORTED_SOURCE}"
        / f"asset_type={SUPPORTED_ASSET_TYPE}"
        / f"interval={SUPPORTED_INTERVAL}"
        / f"trade_date={trade_date_value.isoformat()}"
        / f"bucket={bucket:02d}"
    )
    _validate_storage_path(data_root, directory)
    directory.mkdir(parents=True, exist_ok=True)
    _validate_storage_path(data_root, directory)
    final_path = directory / f"part-{content_hash}.parquet"
    _validate_storage_path(data_root, final_path)
    if final_path.exists():
        validation = validate_intraday_parquet(final_path, expected_content_hash=content_hash)
        return _artifact(
            root=data_root,
            path=final_path,
            validation=validation,
            bucket=bucket,
            created=False,
        )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".j21-intraday-",
            suffix=".parquet.tmp",
            dir=directory,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        pq.write_table(
            table,
            temporary_path,
            compression="zstd",
            use_dictionary=["provider_symbol", "session", "source", "interval"],
        )
        _fsync_file(temporary_path)
        validate_intraday_parquet(temporary_path, expected_content_hash=content_hash)
        created = _publish_without_overwrite(temporary_path, final_path)
        temporary_path.unlink(missing_ok=True)
        temporary_path = None
        _fsync_directory(directory)
        validation = validate_intraday_parquet(final_path, expected_content_hash=content_hash)
        return _artifact(
            root=data_root,
            path=final_path,
            validation=validation,
            bucket=bucket,
            created=created,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def validate_intraday_parquet(
    path: str | Path,
    *,
    expected_content_hash: str | None = None,
) -> ParquetValidation:
    """Read a single file and enforce schema, identity, ordering, and bar invariants."""
    file_path = Path(path)
    table = pq.ParquetFile(file_path).read()
    if not table.schema.equals(INTRADAY_BAR_SCHEMA, check_metadata=False):
        raise ValueError(f"intraday Parquet schema mismatch: {table.schema}")
    rows = table.to_pylist()
    if not rows:
        raise ValueError("intraday Parquet file must contain at least one row")
    keys = [
        (row["source"], row["instrument_id"], row["timestamp_utc"], row["interval"])
        for row in rows
    ]
    if keys != sorted(keys):
        raise ValueError("intraday Parquet rows are not sorted by natural key")
    if len(keys) != len(set(keys)):
        raise ValueError("intraday Parquet contains duplicate natural keys")
    for row in rows:
        _validate_record(row)
    identities = {
        (int(row["instrument_id"]), str(row["provider_symbol"]), row["trade_date"])
        for row in rows
    }
    if len(identities) != 1:
        raise ValueError("one intraday Parquet file must contain one instrument/trade_date")
    content_hash = _content_hash_from_records(rows)
    if expected_content_hash is not None and content_hash != expected_content_hash:
        raise ValueError(
            "intraday Parquet content hash mismatch: "
            f"expected={expected_content_hash} actual={content_hash}"
        )
    instrument_id, provider_symbol, trade_date_value = next(iter(identities))
    timestamps = [row["timestamp_utc"] for row in rows]
    return ParquetValidation(
        row_count=len(rows),
        content_hash=content_hash,
        timestamp_min_utc=min(timestamps),
        timestamp_max_utc=max(timestamps),
        instrument_id=instrument_id,
        provider_symbol=provider_symbol,
        trade_date=trade_date_value,
    )


def validate_intraday_artifact_path(
    absolute_path: str | Path,
    storage_path: str,
    *,
    root: str | Path,
) -> None:
    """Verify that an artifact path matches its configured root and relative path."""
    path = Path(absolute_path)
    relative = Path(*PurePosixPath(storage_path).parts)
    if not path.is_absolute() or not relative.parts:
        raise ValueError("intraday artifact path must be absolute with a relative storage path")
    validated_root = resolve_intraday_data_root(root, create=False)
    if path != validated_root / relative:
        raise ValueError("intraday artifact path does not match storage_path")
    _validate_storage_path(validated_root, path)


def _validate_bar_batch(bars: list[IntradayBar]) -> tuple[int, str, date]:
    if not bars:
        raise ValueError("bars must not be empty")
    keys = [bar.natural_key for bar in bars]
    if len(keys) != len(set(keys)):
        raise ValueError("intraday bars contain duplicate natural keys")
    identities = {(bar.instrument_id, bar.provider_symbol, bar.trade_date) for bar in bars}
    if len(identities) != 1:
        raise ValueError("one intraday Parquet file must contain one instrument/trade_date")
    for bar in bars:
        _validate_record(_bar_record(bar))
    return next(iter(identities))


def _validate_record(row: dict[str, object]) -> None:
    if row["source"] != SUPPORTED_SOURCE or row["interval"] != SUPPORTED_INTERVAL:
        raise ValueError("intraday validation accepts only raw EODHD 1m bars")
    timestamp = row["timestamp_utc"]
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
        raise ValueError("timestamp_utc must be timezone-aware")
    timestamp_utc = timestamp.astimezone(UTC)
    expected_session = classify_us_equity_session(timestamp_utc)
    if row["session"] != expected_session:
        raise ValueError("session does not match America/New_York timestamp")
    if row["trade_date"] != timestamp_utc.astimezone(NEW_YORK).date():
        raise ValueError("trade_date does not match America/New_York timestamp")
    open_price = Decimal(row["open"])
    high = Decimal(row["high"])
    low = Decimal(row["low"])
    close = Decimal(row["close"])
    if min(open_price, high, low, close) < 0:
        raise ValueError("OHLC prices must be non-negative")
    if low > min(open_price, close) or high < max(open_price, close) or low > high:
        raise ValueError("invalid OHLC price bounds")
    if int(row["volume"]) < 0:
        raise ValueError("volume must be non-negative")
    transactions = row.get("transactions")
    if transactions is not None and int(transactions) < 0:
        raise ValueError("transactions must be non-negative")


def _bar_record(bar: IntradayBar) -> dict[str, object]:
    return {
        "instrument_id": bar.instrument_id,
        "provider_symbol": bar.provider_symbol,
        "timestamp_utc": bar.timestamp_utc.astimezone(UTC),
        "trade_date": bar.trade_date,
        "session": bar.session,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "transactions": bar.transactions,
        "source": bar.source,
        "interval": bar.interval,
    }


def _content_hash_from_records(rows: list[dict[str, object]]) -> str:
    normalized: list[dict[str, object]] = []
    for row in rows:
        normalized.append(
            {
                key: _json_value(row[key])
                for key in INTRADAY_BAR_SCHEMA.names
            }
        )
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _artifact(
    *,
    root: Path,
    path: Path,
    validation: ParquetValidation,
    bucket: int,
    created: bool,
) -> IntradayFileArtifact:
    return IntradayFileArtifact(
        absolute_path=path,
        storage_path=path.relative_to(root).as_posix(),
        content_hash=validation.content_hash,
        file_sha256=_sha256_file(path),
        row_count=validation.row_count,
        file_size_bytes=path.stat().st_size,
        timestamp_min_utc=validation.timestamp_min_utc,
        timestamp_max_utc=validation.timestamp_max_utc,
        instrument_id=validation.instrument_id,
        provider_symbol=validation.provider_symbol,
        trade_date=validation.trade_date,
        bucket=bucket,
        source=SUPPORTED_SOURCE,
        asset_type=SUPPORTED_ASSET_TYPE,
        interval=SUPPORTED_INTERVAL,
        schema_version=INTRADAY_SCHEMA_VERSION,
        created=created,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as file:
        os.fsync(file.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_without_overwrite(temporary_path: Path, final_path: Path) -> bool:
    """Atomically publish one immutable file without replacing a concurrent writer."""
    try:
        os.link(temporary_path, final_path)
    except FileExistsError:
        return False
    return True


def _validate_storage_path(root: Path, path: Path) -> None:
    """Reject lexical escapes and every existing symlink below the data root."""
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("intraday storage path escapes J21_INTRADAY_DATA_ROOT") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("intraday storage path must not contain symlink components")
    resolved = path.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ValueError("intraday storage path escapes J21_INTRADAY_DATA_ROOT")
