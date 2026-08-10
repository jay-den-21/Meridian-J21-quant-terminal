from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import pytest

from fdp.intraday.models import IntradayBar
from fdp.intraday.sessions import classify_us_equity_session
from fdp.intraday.storage import (
    resolve_intraday_data_root,
    validate_intraday_parquet,
    write_intraday_parquet,
)
from fdp.sources.eodhd.intraday import parse_intraday_rows

NEW_YORK = ZoneInfo("America/New_York")


def _bar(timestamp: datetime, *, close: str = "100.50000000") -> IntradayBar:
    return IntradayBar(
        instrument_id=101,
        provider_symbol="AAPL.US",
        timestamp_utc=timestamp,
        trade_date=timestamp.astimezone(NEW_YORK).date(),
        session=classify_us_equity_session(timestamp),
        open=Decimal("100.00000000"),
        high=Decimal("101.00000000"),
        low=Decimal("99.00000000"),
        close=Decimal(close),
        volume=1000,
        transactions=None,
    )


def _raw(timestamp: datetime, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "timestamp": int(timestamp.timestamp()),
        "open": 100,
        "high": 101,
        "low": 99,
        "close": 100.5,
        "volume": 1000,
    }
    row.update(overrides)
    return row


def test_session_classification_uses_new_york_dst_and_extended_hours() -> None:
    assert classify_us_equity_session(datetime(2024, 1, 2, 13, 0, tzinfo=UTC)) == "pre"
    assert classify_us_equity_session(datetime(2024, 1, 2, 14, 30, tzinfo=UTC)) == "core"
    assert classify_us_equity_session(datetime(2024, 1, 2, 21, 0, tzinfo=UTC)) == "after"
    assert classify_us_equity_session(datetime(2024, 7, 1, 13, 30, tzinfo=UTC)) == "core"
    with pytest.raises(ValueError, match="outside"):
        classify_us_equity_session(datetime(2024, 1, 2, 8, 0, tzinfo=UTC))


def test_eodhd_parser_rejects_bad_ohlcv_precision_outside_session_and_duplicates() -> None:
    valid_time = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    parsed = parse_intraday_rows(
        [
            _raw(valid_time),
            _raw(valid_time),
            _raw(valid_time.replace(minute=31), high=99),
            _raw(valid_time.replace(minute=32), close="1.123456789"),
            _raw(valid_time.replace(minute=33, second=1)),
            _raw(datetime(2024, 1, 2, 8, 0, tzinfo=UTC)),
        ],
        instrument_id=101,
        provider_symbol="aapl.us",
    )

    assert len(parsed.accepted) == 1
    assert parsed.accepted[0].provider_symbol == "AAPL.US"
    assert parsed.accepted[0].transactions is None
    assert len(parsed.rejected) == 5
    assert any("duplicate" in row.reason for row in parsed.rejected)
    assert any("8 decimal" in row.reason for row in parsed.rejected)


def test_intraday_root_is_required_absolute_and_outside_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("J21_INTRADAY_DATA_ROOT", raising=False)
    with pytest.raises(ValueError, match="required"):
        resolve_intraday_data_root()
    with pytest.raises(ValueError, match="absolute"):
        resolve_intraday_data_root("relative/minutes")
    repository_path = Path(__file__).parents[1] / "minute-data"
    with pytest.raises(ValueError, match="outside the repository"):
        resolve_intraday_data_root(repository_path)
    symlink = tmp_path / "linked"
    symlink.symlink_to(tmp_path / "target", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        resolve_intraday_data_root(symlink)

    root = tmp_path / "minutes"
    target = tmp_path / "redirected"
    root.mkdir()
    target.mkdir()
    (root / "validation").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink components"):
        write_intraday_parquet(
            [_bar(datetime(2024, 1, 2, 14, 30, tzinfo=UTC))],
            root=root,
        )
    assert list(target.iterdir()) == []


def test_parquet_round_trip_is_sorted_partitioned_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "minutes"
    first = _bar(datetime(2024, 1, 2, 14, 31, tzinfo=UTC))
    second = _bar(datetime(2024, 1, 2, 14, 30, tzinfo=UTC))

    artifact = write_intraday_parquet([first, second], root=root)
    validation = validate_intraday_parquet(
        artifact.absolute_path,
        expected_content_hash=artifact.content_hash,
    )
    repeated = write_intraday_parquet([second, first], root=root)

    assert artifact.created is True
    assert repeated.created is False
    assert repeated.storage_path == artifact.storage_path
    assert validation.row_count == 2
    assert "validation/source=eodhd/asset_type=stock/interval=1m" in artifact.storage_path
    assert "trade_date=2024-01-02/bucket=05" in artifact.storage_path
    table = pq.ParquetFile(artifact.absolute_path).read()
    timestamps = table.column("timestamp_utc").to_pylist()
    assert timestamps == sorted(timestamps)


def test_parquet_rejects_duplicate_natural_keys(tmp_path: Path) -> None:
    bar = _bar(datetime(2024, 1, 2, 14, 30, tzinfo=UTC))
    with pytest.raises(ValueError, match="duplicate"):
        write_intraday_parquet([bar, bar], root=tmp_path / "minutes")


def test_content_hash_uses_arrow_canonical_decimal_scale(tmp_path: Path) -> None:
    bar = replace(
        _bar(datetime(2024, 1, 2, 14, 30, tzinfo=UTC)),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
    )

    artifact = write_intraday_parquet([bar], root=tmp_path / "minutes")
    validation = validate_intraday_parquet(
        artifact.absolute_path,
        expected_content_hash=artifact.content_hash,
    )

    assert validation.row_count == 1
