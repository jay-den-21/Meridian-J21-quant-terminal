"""Parse EODHD historical daily price payloads into storage-ready rows."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class RejectedDailyPriceRow:
    """Raw historical EOD row that failed required-field or OHLCV validation.

    Input: row index, provider symbol, rejection reason, and original EODHD row.
    Output: audit object returned to ingestion callers.
    Flow: raw row -> parse/validation error -> rejected row record.
    """

    index: int
    provider_symbol: str
    reason: str
    row: dict[str, Any]


@dataclass(frozen=True)
class ParsedDailyPriceRows:
    """Batch parse result for EODHD historical EOD rows.

    Input: raw historical EOD rows for one instrument.
    Output: accepted `daily_price` rows and rejected audit rows.
    Flow: raw rows -> required fields -> OHLCV validation -> accepted + rejected.
    """

    accepted: list[dict[str, Any]]
    rejected: list[RejectedDailyPriceRow]


def parse_daily_price_row(
    payload: dict[str, Any],
    *,
    instrument_id: int,
    symbol: str,
    provider_symbol: str,
    currency: str,
    source: str = "EODHD",
) -> dict[str, Any]:
    """Parse one EODHD historical EOD row into a `daily_price` row.

    Input: raw EODHD row plus instrument metadata from `us_share.instrument`.
    Output: storage-ready daily price dict.
    Flow: raw row -> typed date/Decimal/int values -> OHLCV validation -> price row.
    """
    trade_date = _required_date(payload, "date")
    open_price = _required_decimal(payload, "open")
    high = _required_decimal(payload, "high")
    low = _required_decimal(payload, "low")
    close = _required_decimal(payload, "close")
    adjusted_close = _required_decimal(payload, "adjusted_close")
    volume = _required_int(payload, "volume")

    _validate_ohlcv(
        open_price=open_price,
        high=high,
        low=low,
        close=close,
        adjusted_close=adjusted_close,
        volume=volume,
    )

    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "provider_symbol": provider_symbol,
        "trade_date": trade_date,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "adjusted_close": adjusted_close,
        "volume": volume,
        "currency": currency,
        "source": source,
        "source_updated_at": None,
    }


def parse_daily_price_rows(
    rows: list[dict[str, Any]],
    *,
    instrument_id: int,
    symbol: str,
    provider_symbol: str,
    currency: str,
    source: str = "EODHD",
) -> ParsedDailyPriceRows:
    """Parse a batch of historical EOD rows with rejection tracking.

    Input: raw rows for one instrument and the instrument metadata to attach.
    Output: `ParsedDailyPriceRows` with accepted rows and rejection reasons.
    Flow: rows -> `parse_daily_price_row` -> accepted + rejected lists.
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[RejectedDailyPriceRow] = []

    for index, row in enumerate(rows):
        try:
            accepted.append(
                parse_daily_price_row(
                    row,
                    instrument_id=instrument_id,
                    symbol=symbol,
                    provider_symbol=provider_symbol,
                    currency=currency,
                    source=source,
                )
            )
        except ValueError as exc:
            rejected.append(
                RejectedDailyPriceRow(
                    index=index,
                    provider_symbol=provider_symbol,
                    reason=str(exc),
                    row=row,
                )
            )

    return ParsedDailyPriceRows(accepted=accepted, rejected=rejected)


def _required_decimal(payload: dict[str, Any], key: str) -> Decimal:
    value = _required_value(payload, key)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal EODHD field: {key}") from exc
    return parsed


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = _required_value(payload, key)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer EODHD field: {key}") from exc


def _required_date(payload: dict[str, Any], key: str) -> date:
    value = _required_value(payload, key)
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid date EODHD field: {key}") from exc


def _required_value(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value in (None, ""):
        raise ValueError(f"missing required EODHD field: {key}")
    return value


def _validate_ohlcv(
    *,
    open_price: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    adjusted_close: Decimal,
    volume: int,
) -> None:
    if min(open_price, high, low, close, adjusted_close) < 0:
        raise ValueError("invalid_ohlcv: negative price")
    if volume < 0:
        raise ValueError("invalid_ohlcv: negative volume")
    if high < low:
        raise ValueError("invalid_ohlcv: high is lower than low")
    if high < open_price or high < close:
        raise ValueError("invalid_ohlcv: high is lower than open/close")
    if low > open_price or low > close:
        raise ValueError("invalid_ohlcv: low is higher than open/close")
