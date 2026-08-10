"""Strict EODHD intraday payload normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fdp.intraday.models import IntradayBar
from fdp.intraday.sessions import NEW_YORK, classify_us_equity_session

PRICE_QUANTUM = Decimal("0.00000001")


@dataclass(frozen=True)
class RejectedIntradayRow:
    row_index: int
    reason: str
    payload: object


@dataclass(frozen=True)
class ParsedIntradayRows:
    accepted: tuple[IntradayBar, ...]
    rejected: tuple[RejectedIntradayRow, ...]


def parse_intraday_rows(
    rows: object,
    *,
    instrument_id: int,
    provider_symbol: str,
) -> ParsedIntradayRows:
    """Normalize one EODHD response without guessing or repairing invalid bars."""
    if not isinstance(rows, list):
        raise ValueError("EODHD intraday payload must be a JSON list")
    accepted: list[IntradayBar] = []
    rejected: list[RejectedIntradayRow] = []
    seen: set[tuple[str, int, datetime, str]] = set()
    for index, row in enumerate(rows):
        try:
            bar = parse_intraday_row(
                row,
                instrument_id=instrument_id,
                provider_symbol=provider_symbol,
            )
            if bar.natural_key in seen:
                raise ValueError("duplicate intraday natural key")
            seen.add(bar.natural_key)
            accepted.append(bar)
        except (TypeError, ValueError, InvalidOperation) as exc:
            rejected.append(RejectedIntradayRow(index, str(exc), row))
    accepted.sort(key=lambda bar: bar.natural_key)
    return ParsedIntradayRows(tuple(accepted), tuple(rejected))


def parse_intraday_row(
    row: object,
    *,
    instrument_id: int,
    provider_symbol: str,
) -> IntradayBar:
    """Convert one provider row into the v1 raw 1-minute contract."""
    if not isinstance(row, dict):
        raise TypeError("intraday row must be a JSON object")
    if instrument_id <= 0:
        raise ValueError("instrument_id must be positive")
    normalized_symbol = provider_symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("provider_symbol must not be empty")
    timestamp = _unix_timestamp(row.get("timestamp"))
    session = classify_us_equity_session(timestamp)
    prices = {name: _price(row.get(name), name=name) for name in ("open", "high", "low", "close")}
    if prices["low"] > min(prices["open"], prices["close"]):
        raise ValueError("low exceeds open or close")
    if prices["high"] < max(prices["open"], prices["close"]):
        raise ValueError("high is below open or close")
    if prices["low"] > prices["high"]:
        raise ValueError("low exceeds high")
    volume = _nonnegative_integer(row.get("volume"), name="volume")
    return IntradayBar(
        instrument_id=instrument_id,
        provider_symbol=normalized_symbol,
        timestamp_utc=timestamp,
        trade_date=timestamp.astimezone(NEW_YORK).date(),
        session=session,
        open=prices["open"],
        high=prices["high"],
        low=prices["low"],
        close=prices["close"],
        volume=volume,
        transactions=None,
    )


def _unix_timestamp(value: Any) -> datetime:
    if isinstance(value, bool):
        raise ValueError("timestamp must be Unix seconds")
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp must be Unix seconds") from exc
    if str(seconds) != str(value).strip() and not isinstance(value, int):
        try:
            if float(value) != seconds:
                raise ValueError("timestamp must be an integral Unix second")
        except (TypeError, ValueError) as exc:
            raise ValueError("timestamp must be Unix seconds") from exc
    if seconds < 0 or seconds > 32_503_680_000:
        raise ValueError("timestamp is outside the supported Unix-seconds range")
    if seconds % 60:
        raise ValueError("1m timestamp must align to a whole-minute boundary")
    return datetime.fromtimestamp(seconds, tz=UTC)


def _price(value: Any, *, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    quantized = parsed.quantize(PRICE_QUANTUM)
    if parsed != quantized:
        raise ValueError(f"{name} has more than 8 decimal places")
    return quantized


def _nonnegative_integer(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a non-negative integer")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
        raise ValueError(f"{name} must be a non-negative integer")
    return int(parsed)
