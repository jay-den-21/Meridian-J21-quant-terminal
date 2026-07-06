"""Parse EODHD instrument and symbol-change payloads into storage-ready rows."""

from dataclasses import dataclass
from datetime import date
from typing import Any

SUPPORTED_ASSET_TYPES = {
    "common stock": "stock",
    "stock": "stock",
    "etf": "etf",
    "fund": "etf",
}


@dataclass(frozen=True)
class RejectedInstrumentRow:
    """Raw exchange-symbol row that could not be loaded.

    Input: row index, rejection reason, and original EODHD row.
    Output: audit object returned to ingestion callers.
    Flow: raw row -> parser error/filter reason -> rejected row record.
    """

    index: int
    reason: str
    row: dict[str, Any]


@dataclass(frozen=True)
class ParsedInstrumentRows:
    """Batch parse result for EODHD exchange-symbol rows.

    Input: many raw EODHD symbol rows.
    Output: accepted storage rows and rejected audit rows.
    Flow: raw rows -> parse/filter each row -> accepted + rejected lists.
    """

    accepted: list[dict[str, Any]]
    rejected: list[RejectedInstrumentRow]


@dataclass(frozen=True)
class SymbolChange:
    """One EODHD ticker rename event.

    Input: EODHD symbol-change-history row.
    Output: normalized old/new ticker and provider-symbol values.
    Flow: old/new ticker -> old/new provider_symbol -> effective rename event.
    """

    exchange: str
    old_symbol: str
    new_symbol: str
    old_provider_symbol: str
    new_provider_symbol: str
    company_name: str | None
    effective: date


@dataclass(frozen=True)
class RejectedSymbolChangeRow:
    """Raw symbol-change row that could not be parsed."""

    index: int
    reason: str
    row: dict[str, Any]


@dataclass(frozen=True)
class ParsedSymbolChangeRows:
    """Batch parse result for EODHD symbol-change-history rows."""

    accepted: list[SymbolChange]
    rejected: list[RejectedSymbolChangeRow]


def split_provider_symbol(provider_symbol: str) -> tuple[str, str]:
    """Split an EODHD provider symbol into ticker and market suffix.

    Input: provider symbol such as "AAPL.US".
    Output: tuple `(symbol, market)` such as `("AAPL", "US")`.
    Flow: provider_symbol -> right split on "." -> validated parts.
    """
    parts = provider_symbol.rsplit(".", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"invalid EODHD provider_symbol: {provider_symbol!r}")
    return parts[0], parts[1]


def parse_exchange_symbol(
    payload: dict[str, Any],
    *,
    market: str = "US",
    provider: str = "EODHD",
    force_inactive: bool = False,
) -> dict[str, Any] | None:
    """Parse one EODHD exchange-symbol row into an `instrument` row.

    Input: raw EODHD row plus target market/provider.
    Output: storage-ready instrument dict, or `None` for unsupported asset type.
    Flow: raw row -> asset filter -> required fields -> provider symbol -> instrument row.
    """
    asset_type = _normalize_asset_type(_first_present(payload, "Type", "type"))
    if asset_type is None:
        return None

    code = _required_text(payload, "Code", "code")
    name = _required_text(payload, "Name", "name")
    currency = _required_text(payload, "Currency", "currency")
    exchange = _optional_text(payload, "Exchange", "exchange") or market
    provider_symbol = _provider_symbol_from_code(code, market)
    symbol, provider_market = split_provider_symbol(provider_symbol)

    if provider_market != market:
        raise ValueError(
            f"EODHD provider_symbol market {provider_market!r} does not match {market!r}"
        )

    delisted_date = _optional_date(payload, "DelistedDate", "delisted_date")
    return {
        "market": market,
        "symbol": symbol,
        "provider": provider,
        "provider_symbol": provider_symbol,
        "name": name,
        "exchange": exchange,
        "asset_type": asset_type,
        "currency": currency,
        "is_active": False if force_inactive else delisted_date is None,
        "listed_date": _optional_date(payload, "IPODate", "listed_date"),
        "delisted_date": delisted_date,
    }


def parse_exchange_symbol_rows(
    rows: list[dict[str, Any]],
    *,
    market: str = "US",
    provider: str = "EODHD",
    include_inactive: bool = False,
    force_inactive: bool = False,
) -> ParsedInstrumentRows:
    """Parse a batch of exchange-symbol rows with per-row rejection tracking.

    Input: raw EODHD exchange-symbol rows.
    Output: `ParsedInstrumentRows` with accepted rows and rejection reasons.
    Flow: rows -> `parse_exchange_symbol` -> inactive/unsupported filter -> batch result.
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[RejectedInstrumentRow] = []

    for index, row in enumerate(rows):
        try:
            parsed = parse_exchange_symbol(
                row,
                market=market,
                provider=provider,
                force_inactive=force_inactive,
            )
        except ValueError as exc:
            rejected.append(RejectedInstrumentRow(index=index, reason=str(exc), row=row))
            continue

        if parsed is None:
            rejected.append(
                RejectedInstrumentRow(index=index, reason="unsupported_asset_type", row=row)
            )
            continue

        if not include_inactive and not parsed["is_active"]:
            rejected.append(RejectedInstrumentRow(index=index, reason="inactive_instrument", row=row))
            continue

        accepted.append(parsed)

    return ParsedInstrumentRows(accepted=accepted, rejected=rejected)


def parse_symbol_change_history(
    payload: dict[str, Any],
    *,
    market: str = "US",
) -> SymbolChange:
    """Parse one EODHD symbol-change-history row.

    Input: row with `old_symbol`, `new_symbol`, and `effective`.
    Output: `SymbolChange` with both ticker and provider-symbol values.
    Flow: raw rename row -> required fields -> provider symbols -> normalized event.
    """
    old_symbol = _required_text(payload, "old_symbol")
    new_symbol = _required_text(payload, "new_symbol")
    effective = _required_date(payload, "effective")

    return SymbolChange(
        exchange=_optional_text(payload, "exchange") or market,
        old_symbol=old_symbol,
        new_symbol=new_symbol,
        old_provider_symbol=_provider_symbol_from_code(old_symbol, market),
        new_provider_symbol=_provider_symbol_from_code(new_symbol, market),
        company_name=_optional_text(payload, "company_name"),
        effective=effective,
    )


def parse_symbol_change_history_rows(
    rows: list[dict[str, Any]],
    *,
    market: str = "US",
) -> ParsedSymbolChangeRows:
    """Parse a batch of EODHD rename rows with rejection tracking.

    Input: raw symbol-change-history rows.
    Output: accepted `SymbolChange` events and rejected rows.
    Flow: rows -> `parse_symbol_change_history` -> accepted + rejected lists.
    """
    accepted: list[SymbolChange] = []
    rejected: list[RejectedSymbolChangeRow] = []

    for index, row in enumerate(rows):
        try:
            accepted.append(parse_symbol_change_history(row, market=market))
        except ValueError as exc:
            rejected.append(RejectedSymbolChangeRow(index=index, reason=str(exc), row=row))

    return ParsedSymbolChangeRows(accepted=accepted, rejected=rejected)


def _normalize_asset_type(value: Any) -> str | None:
    """Map EODHD asset type text into project asset type values."""
    if value is None:
        return None
    return SUPPORTED_ASSET_TYPES.get(str(value).strip().lower())


def _provider_symbol_from_code(code: str, market: str) -> str:
    """Return an EODHD provider symbol, adding `.market` when needed."""
    if code.endswith(f".{market}"):
        return code

    if "." in code:
        symbol, suffix = code.rsplit(".", 1)
        if symbol and suffix.isalpha() and len(suffix) > 1:
            return code

    return f"{code}.{market}"


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    """Return the first present value among possible EODHD field names."""
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _required_text(payload: dict[str, Any], *keys: str) -> str:
    """Read a required non-empty text field from a raw EODHD row."""
    value = _optional_text(payload, *keys)
    if value is None:
        joined_keys = ", ".join(keys)
        raise ValueError(f"missing required EODHD field: {joined_keys}")
    return value


def _optional_text(payload: dict[str, Any], *keys: str) -> str | None:
    """Read an optional text field and normalize empty strings to `None`."""
    value = _first_present(payload, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_date(payload: dict[str, Any], *keys: str) -> date | None:
    """Read an optional ISO date field from a raw EODHD row."""
    value = _first_present(payload, *keys)
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _required_date(payload: dict[str, Any], *keys: str) -> date:
    """Read a required ISO date field from a raw EODHD row."""
    value = _optional_date(payload, *keys)
    if value is None:
        joined_keys = ", ".join(keys)
        raise ValueError(f"missing required EODHD date field: {joined_keys}")
    return value
