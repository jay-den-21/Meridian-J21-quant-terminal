"""Typed parsing and validation for EODHD ID Mapping responses."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any


ID_MAPPING_SOURCE = "EODHD_ID_MAPPING"
IDENTIFIER_TYPES = ("isin", "figi", "lei", "cusip", "cik")
_PROVIDER_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._/@+-]*\.[A-Z0-9]+$")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_FIGI = re.compile(r"^[B-DF-HJ-NP-TV-Z]{2}G[0-9B-DF-HJ-NP-TV-Z]{8}[0-9]$")
_LEI = re.compile(r"^[A-Z0-9]{20}$")
_CUSIP = re.compile(r"^[A-Z0-9*@#]{9}$")
_CIK = re.compile(r"^[0-9]{1,10}$")


@dataclass(frozen=True)
class IdentifierMappingRecord:
    """One normalized provider mapping row with field-level validation evidence."""

    provider_symbol: str | None
    source_values: dict[str, str | None]
    identifiers: dict[str, str]
    invalid_fields: tuple[str, ...]
    raw_payload: str
    fingerprint: str
    row_error: str | None = None


@dataclass(frozen=True)
class IdentifierMappingEnvelope:
    """Validated pagination envelope returned by EODHD ID Mapping."""

    total: int
    limit: int
    offset: int
    rows: list[IdentifierMappingRecord]
    has_next: bool


def parse_identifier_mapping_envelope(payload: Any) -> IdentifierMappingEnvelope:
    """Validate an ID Mapping envelope and normalize each source row."""
    if not isinstance(payload, dict):
        raise ValueError("EODHD ID mapping payload must be an object")
    meta = payload.get("meta")
    rows = payload.get("data")
    links = payload.get("links")
    if not isinstance(meta, dict) or not isinstance(rows, list):
        raise ValueError("EODHD ID mapping payload requires meta and data")
    try:
        total = int(meta["total"])
        limit = int(meta["limit"])
        offset = int(meta["offset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("EODHD ID mapping pagination metadata is invalid") from exc
    if total < 0 or not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("EODHD ID mapping pagination metadata is out of range")
    if offset > total and rows:
        raise ValueError("EODHD ID mapping returned rows beyond its declared total")
    next_link = links.get("next") if isinstance(links, dict) else None
    return IdentifierMappingEnvelope(
        total=total,
        limit=limit,
        offset=offset,
        rows=[parse_identifier_mapping_row(row) for row in rows],
        has_next=bool(next_link) or offset + len(rows) < total,
    )


def parse_identifier_mapping_row(row: Any) -> IdentifierMappingRecord:
    """Normalize one mapping row while retaining malformed field evidence."""
    raw_payload = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    if not isinstance(row, dict):
        source_values = {"symbol": None, **dict.fromkeys(IDENTIFIER_TYPES)}
        return IdentifierMappingRecord(
            provider_symbol=None,
            source_values=source_values,
            identifiers={},
            invalid_fields=(),
            raw_payload=raw_payload,
            fingerprint=_raw_payload_fingerprint(raw_payload),
            row_error="mapping_row_not_object",
        )

    source_symbol = row.get("symbol")
    provider_symbol = _normalized_text(source_symbol)
    invalid_source_type = source_symbol is not None and provider_symbol is None
    source_values: dict[str, str | None] = {"symbol": provider_symbol}
    identifiers: dict[str, str] = {}
    invalid_fields: list[str] = []
    has_blank_optional_field = False
    for id_type in IDENTIFIER_TYPES:
        source_value = row.get(id_type)
        raw_value = _normalized_text(source_value)
        source_values[id_type] = raw_value
        if raw_value is None:
            if isinstance(source_value, str) and not source_value.strip():
                # Preserve the old raw fingerprint so repair runs can close
                # observations created when blank fields counted as invalid.
                has_blank_optional_field = True
            elif source_value is not None:
                invalid_fields.append(id_type)
            continue
        normalized_value = _normalize_identifier(id_type, raw_value)
        if normalized_value is None:
            invalid_fields.append(id_type)
            continue
        identifiers[id_type] = normalized_value
        source_values[id_type] = normalized_value

    row_error = None
    if (
        provider_symbol is None
        or len(provider_symbol) > 128
        or not _PROVIDER_SYMBOL.fullmatch(provider_symbol)
    ):
        row_error = "invalid_provider_symbol"
    elif not any(source_values.get(id_type) for id_type in IDENTIFIER_TYPES):
        row_error = "no_identifiers"

    return IdentifierMappingRecord(
        provider_symbol=provider_symbol,
        source_values=source_values,
        identifiers=identifiers,
        invalid_fields=tuple(invalid_fields),
        raw_payload=raw_payload,
        fingerprint=(
            _raw_payload_fingerprint(raw_payload)
            if invalid_source_type or invalid_fields or has_blank_optional_field
            else _mapping_fingerprint(source_values)
        ),
        row_error=row_error,
    )


def _normalized_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def _normalize_identifier(id_type: str, value: str) -> str | None:
    if id_type == "isin":
        return value if _ISIN.fullmatch(value) and _luhn_alphanumeric_valid(value) else None
    if id_type == "figi":
        return value if _FIGI.fullmatch(value) and _figi_valid(value) else None
    if id_type == "lei":
        return value if _LEI.fullmatch(value) and _mod97_alphanumeric_valid(value) else None
    if id_type == "cusip":
        return value if _CUSIP.fullmatch(value) and _cusip_valid(value) else None
    if id_type == "cik":
        return value.zfill(10) if _CIK.fullmatch(value) else None
    raise ValueError(f"unsupported identifier type: {id_type}")


def _mapping_fingerprint(source_values: dict[str, str | None]) -> str:
    encoded = json.dumps(source_values, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _raw_payload_fingerprint(raw_payload: str) -> str:
    return sha256(raw_payload.encode()).hexdigest()


def _luhn_alphanumeric_valid(value: str) -> bool:
    digits = "".join(str(ord(char) - 55) if char.isalpha() else char for char in value)
    total = 0
    for index, digit in enumerate(reversed(digits)):
        number = int(digit)
        if index % 2 == 1:
            number *= 2
        total += number // 10 + number % 10
    return total % 10 == 0


def _mod97_alphanumeric_valid(value: str) -> bool:
    digits = "".join(str(ord(char) - 55) if char.isalpha() else char for char in value)
    remainder = 0
    for digit in digits:
        remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def _cusip_valid(value: str) -> bool:
    special = {"*": 36, "@": 37, "#": 38}
    total = 0
    for index, char in enumerate(value[:8]):
        number = int(char) if char.isdigit() else special.get(char, ord(char) - 55)
        if index % 2 == 1:
            number *= 2
        total += number // 10 + number % 10
    return value[-1].isdigit() and (10 - total % 10) % 10 == int(value[-1])


def _figi_valid(value: str) -> bool:
    total = 0
    for index, char in enumerate(value[:11]):
        number = int(char) if char.isdigit() else ord(char) - 55
        if index % 2 == 1:
            number *= 2
        total += number // 10 + number % 10
    return (10 - total % 10) % 10 == int(value[-1])
