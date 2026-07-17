"""Parse EODHD dividend and split payloads into canonical event rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable


@dataclass(frozen=True)
class RejectedCorporateActionRow:
    """One provider row rejected before canonical storage."""

    index: int
    provider_symbol: str
    action_type: str
    reason: str
    row: dict[str, Any]


@dataclass(frozen=True)
class ParsedCorporateActionRows:
    """Accepted canonical rows and their rejected provider evidence."""

    accepted: list[dict[str, Any]]
    rejected: list[RejectedCorporateActionRow]


def parse_dividend_rows(
    rows: list[dict[str, Any]],
    *,
    instrument_id: int,
    symbol: str,
    provider_symbol: str,
    source: str = "EODHD",
) -> ParsedCorporateActionRows:
    """Parse dividend rows and reject conflicting events on one ex-date."""
    return _parse_action_rows(
        rows,
        instrument_id=instrument_id,
        symbol=symbol,
        provider_symbol=provider_symbol,
        action_type="dividend",
        parser=parse_dividend_row,
        source=source,
    )


def parse_split_rows(
    rows: list[dict[str, Any]],
    *,
    instrument_id: int,
    symbol: str,
    provider_symbol: str,
    source: str = "EODHD",
) -> ParsedCorporateActionRows:
    """Parse split rows and reject conflicting events on one effective date."""
    return _parse_action_rows(
        rows,
        instrument_id=instrument_id,
        symbol=symbol,
        provider_symbol=provider_symbol,
        action_type="split",
        parser=parse_split_row,
        source=source,
    )


def parse_dividend_row(
    payload: dict[str, Any],
    *,
    instrument_id: int,
    symbol: str,
    provider_symbol: str,
    source: str = "EODHD",
) -> dict[str, Any]:
    """Map one EODHD dividend row; `action_date` is the ex-dividend date."""
    cash_amount = _required_decimal(payload, "value")
    if cash_amount <= 0:
        raise ValueError("invalid EODHD dividend value: must be positive")
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "provider_symbol": provider_symbol,
        "action_type": "dividend",
        "action_date": _required_date(payload, "date"),
        "declaration_date": _optional_date(
            payload,
            "declarationDate",
            "declaration_date",
        ),
        "record_date": _optional_date(payload, "recordDate", "record_date"),
        "payment_date": _optional_date(payload, "paymentDate", "payment_date"),
        "period": _optional_text(payload, "period"),
        "cash_amount": cash_amount,
        "unadjusted_cash_amount": _optional_decimal(
            payload,
            "unadjustedValue",
            "unadjusted_value",
        ),
        "currency": _optional_text(payload, "currency"),
        "split_ratio": None,
        "split_numerator": None,
        "split_denominator": None,
        "source": source,
    }


def parse_split_row(
    payload: dict[str, Any],
    *,
    instrument_id: int,
    symbol: str,
    provider_symbol: str,
    source: str = "EODHD",
) -> dict[str, Any]:
    """Map one EODHD split row and preserve its provider ratio string."""
    ratio = _required_text(payload, "split")
    numerator, denominator = _split_ratio(ratio)
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "provider_symbol": provider_symbol,
        "action_type": "split",
        "action_date": _required_date(payload, "date"),
        "declaration_date": None,
        "record_date": None,
        "payment_date": None,
        "period": None,
        "cash_amount": None,
        "unadjusted_cash_amount": None,
        "currency": None,
        "split_ratio": ratio,
        "split_numerator": numerator,
        "split_denominator": denominator,
        "source": source,
    }


Parser = Callable[..., dict[str, Any]]


def _parse_action_rows(
    rows: list[dict[str, Any]],
    *,
    instrument_id: int,
    symbol: str,
    provider_symbol: str,
    action_type: str,
    parser: Parser,
    source: str,
) -> ParsedCorporateActionRows:
    parsed_groups: dict[date, list[tuple[int, dict[str, Any], dict[str, Any]]]] = {}
    rejected: list[RejectedCorporateActionRow] = []

    for index, row in enumerate(rows):
        try:
            parsed = parser(
                row,
                instrument_id=instrument_id,
                symbol=symbol,
                provider_symbol=provider_symbol,
                source=source,
            )
        except ValueError as exc:
            rejected.append(
                RejectedCorporateActionRow(
                    index=index,
                    provider_symbol=provider_symbol,
                    action_type=action_type,
                    reason=str(exc),
                    row=row,
                )
            )
            continue
        parsed_groups.setdefault(parsed["action_date"], []).append((index, row, parsed))

    accepted: list[dict[str, Any]] = []
    for action_date, group in parsed_groups.items():
        first = group[0][2]
        if all(entry[2] == first for entry in group[1:]):
            accepted.append(first)
            continue
        reason = f"conflicting EODHD {action_type} rows for {action_date.isoformat()}"
        rejected.extend(
            RejectedCorporateActionRow(
                index=index,
                provider_symbol=provider_symbol,
                action_type=action_type,
                reason=reason,
                row=row,
            )
            for index, row, _ in group
        )

    accepted.sort(key=lambda row: row["action_date"])
    rejected.sort(key=lambda row: row.index)
    return ParsedCorporateActionRows(accepted=accepted, rejected=rejected)


def _split_ratio(value: str) -> tuple[Decimal, Decimal]:
    parts = value.split("/")
    if len(parts) != 2:
        raise ValueError("invalid EODHD split ratio")
    numerator = _decimal(parts[0], "split_numerator")
    denominator = _decimal(parts[1], "split_denominator")
    if numerator <= 0 or denominator <= 0:
        raise ValueError("invalid EODHD split ratio: non-positive component")
    return numerator, denominator


def _required_text(payload: dict[str, Any], *keys: str) -> str:
    value = _optional_text(payload, *keys)
    if value is None:
        raise ValueError(f"missing required EODHD field: {', '.join(keys)}")
    return value


def _optional_text(payload: dict[str, Any], *keys: str) -> str | None:
    value = _first_present(payload, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_decimal(payload: dict[str, Any], *keys: str) -> Decimal:
    value = _first_present(payload, *keys)
    if value in (None, ""):
        raise ValueError(f"missing required EODHD field: {', '.join(keys)}")
    return _decimal(value, keys[0])


def _optional_decimal(payload: dict[str, Any], *keys: str) -> Decimal | None:
    value = _first_present(payload, *keys)
    if value in (None, ""):
        return None
    return _decimal(value, keys[0])


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal EODHD field: {field_name}") from exc
    if not parsed.is_finite():
        raise ValueError(f"invalid decimal EODHD field: {field_name}")
    return parsed


def _required_date(payload: dict[str, Any], *keys: str) -> date:
    value = _optional_date(payload, *keys)
    if value is None:
        raise ValueError(f"missing required EODHD date field: {', '.join(keys)}")
    return value


def _optional_date(payload: dict[str, Any], *keys: str) -> date | None:
    value = _first_present(payload, *keys)
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid date EODHD field: {keys[0]}") from exc


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None
