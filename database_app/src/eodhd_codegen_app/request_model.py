from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from eodhd_codegen_app.endpoints import ParamSpec, SUPPORTED_ENDPOINTS, get_endpoint


MAX_HISTORICAL_RANGE_DAYS = 3660
MAX_BULK_RANGE_DAYS = 31
MAX_PREVIEW_LIMIT = 500
ASSET_TYPES = {"equity"}

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")
EXCHANGE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 _-]{0,19}$")
US_CLASS_SUFFIXES = {"A", "B", "C", "K"}
US_LISTING_SUFFIXES = {
    "AMEX",
    "ARCA",
    "BATS",
    "NASDAQ",
    "NYSE",
    "NYSEAMERICAN",
    "NYSEARCA",
    "NYSEMKT",
    "OTC",
    "OTCBB",
    "OTCGREY",
    "OTCMKTS",
    "OTCQB",
    "OTCQX",
    "PINK",
    "PINX",
}


class ValidationError(ValueError):
    """User-facing validation error for API playground requests."""


@dataclass(frozen=True)
class ApiRequest:
    """Validated app request.

    Input: raw JSON payload from the frontend or tests.
    Output: normalized endpoint id, format, preview limit, and endpoint params.
    Flow: raw payload -> registry lookup -> parameter validation -> ApiRequest.
    """

    endpoint: str
    asset: str
    fmt: str
    preview_limit: int
    values: dict[str, Any]

    def value(self, name: str, default: Any = "") -> Any:
        return self.values.get(name, default)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self.values.get("symbols", ()))

    @property
    def exchange(self) -> str:
        return str(self.values.get("exchange", "US"))

    @property
    def date_from(self) -> date | None:
        value = self.values.get("date_from")
        return value if isinstance(value, date) else None

    @property
    def date_to(self) -> date | None:
        value = self.values.get("date_to")
        return value if isinstance(value, date) else None

    @property
    def trade_date(self) -> date | None:
        value = self.values.get("trade_date")
        return value if isinstance(value, date) else None

    @property
    def period(self) -> str:
        return str(self.values.get("period", "d"))

    @property
    def order(self) -> str:
        return str(self.values.get("order", "a"))

    @property
    def type_filter(self) -> str:
        return str(self.values.get("type_filter", "all"))

    @property
    def delisted(self) -> bool:
        return bool(self.values.get("delisted", False))

    @property
    def search_query(self) -> str:
        return str(self.values.get("search_query", ""))

    @property
    def search_limit(self) -> int:
        return int(self.values.get("limit", 15))

    @property
    def allow_full_exchange(self) -> bool:
        return bool(self.values.get("allow_full_exchange", False))

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "asset": self.asset,
            "fmt": self.fmt,
            "preview_limit": self.preview_limit,
            "params": {key: _public_value(value) for key, value in self.values.items()},
        }


def validate_payload(payload: Mapping[str, Any]) -> ApiRequest:
    endpoint = _choice(_text(payload, "endpoint", "historical_eod"), SUPPORTED_ENDPOINTS, "endpoint")
    spec = get_endpoint(endpoint)
    asset = _choice(_text(payload, "asset", "equity"), ASSET_TYPES, "asset")
    raw_fmt = _text(payload, "fmt", spec.default_format)
    if raw_fmt.strip().lower() not in set(spec.formats) and spec.formats == ("json",):
        raise ValidationError(f"{endpoint} only supports fmt=json in this app")
    fmt = _choice(raw_fmt, set(spec.formats), "fmt")
    preview_limit = _int_between(payload, "preview_limit", 50, 1, MAX_PREVIEW_LIMIT)
    raw_params = _merged_params(payload)

    values: dict[str, Any] = {}
    exchange = _exchange(str(raw_params.get("exchange", payload.get("exchange", "US"))))

    for param in spec.params:
        values[param.name] = _validate_param(param, raw_params, exchange=exchange)

    if "exchange" not in values:
        values["exchange"] = exchange

    _validate_endpoint_rules(endpoint, values)
    return ApiRequest(
        endpoint=endpoint,
        asset=asset,
        fmt=fmt,
        preview_limit=preview_limit,
        values=values,
    )


def _validate_param(param: ParamSpec, raw_params: Mapping[str, Any], *, exchange: str) -> Any:
    if param.required and param.kind != "exchange" and param.name not in raw_params:
        raw = ""
    elif param.kind == "bulk_symbol_list" and param.name not in raw_params:
        raw = ""
    else:
        raw = raw_params.get(param.name, param.default)

    if param.kind == "symbol_list":
        symbols = _normalize_provider_symbols(raw, exchange, param.max_items)
        if param.required and not symbols:
            raise ValidationError(f"{param.name} is required")
        return symbols

    if param.kind == "bulk_symbol_list":
        symbols = _normalize_bulk_symbols(raw, exchange, param.max_items)
        if param.required and not symbols:
            raise ValidationError(f"{param.name} is required")
        return symbols

    if param.kind == "exchange":
        return _exchange(_text_from_raw(raw, param.name, str(param.default)))

    if param.kind == "date":
        parsed = _optional_date(raw, param.name)
        if param.required and parsed is None:
            raise ValidationError(f"{param.name} is required")
        return parsed

    if param.kind == "number":
        return _optional_int(raw, param.name, param.min_value, param.max_value, param.required)

    if param.kind == "checkbox":
        return _bool(raw, param.name)

    if param.kind == "select":
        allowed = {choice.value for choice in param.choices}
        return _choice(_text_from_raw(raw, param.name, str(param.default)), allowed, param.name)

    if param.kind in {"text", "textarea"}:
        text = _text_from_raw(raw, param.name, str(param.default)).strip()
        if param.required and not text:
            raise ValidationError(f"{param.name} is required")
        if param.max_length is not None and len(text) > param.max_length:
            raise ValidationError(f"{param.name} is capped at {param.max_length} characters")
        if text and _has_control_characters(text):
            raise ValidationError(f"{param.name} contains unsupported characters")
        return text

    raise ValidationError(f"unsupported parameter kind: {param.kind}")


def _validate_endpoint_rules(endpoint: str, values: dict[str, Any]) -> None:
    if endpoint == "historical_eod":
        _require_date_range(values, max_days=MAX_HISTORICAL_RANGE_DAYS, endpoint=endpoint)

    elif endpoint == "bulk_last_day_eod":
        symbols = tuple(values.get("symbols", ()))
        if not symbols and not values.get("allow_full_exchange", False):
            raise ValidationError(
                "bulk_last_day_eod requires symbols unless allow_full_exchange is explicitly enabled"
            )
        trade_date = values.get("trade_date")
        date_from = values.get("date_from")
        date_to = values.get("date_to")
        if trade_date is not None and (date_from is not None or date_to is not None):
            raise ValidationError("bulk_last_day_eod accepts either trade_date or date_from/date_to, not both")
        if (date_from is None) ^ (date_to is None):
            raise ValidationError("bulk_last_day_eod date range requires both date_from and date_to")
        if date_from is not None and date_to is not None:
            if date_from > date_to:
                raise ValidationError("date_from must be earlier than or equal to date_to")
            if (date_to - date_from).days > MAX_BULK_RANGE_DAYS:
                raise ValidationError(f"bulk_last_day_eod date range is capped at {MAX_BULK_RANGE_DAYS} days")

    elif endpoint == "intraday":
        from_ts = values.get("from_timestamp")
        to_ts = values.get("to_timestamp")
        if from_ts is not None and to_ts is not None:
            if from_ts > to_ts:
                raise ValidationError("from_timestamp must be earlier than or equal to to_timestamp")
            max_days = {"1m": 120, "5m": 600, "1h": 7200}[str(values.get("interval", "5m"))]
            max_seconds = max_days * 24 * 60 * 60
            if to_ts - from_ts > max_seconds:
                raise ValidationError(f"intraday {values['interval']} range is capped at {max_days} days")

    elif endpoint == "technical":
        _require_date_range(values, max_days=MAX_HISTORICAL_RANGE_DAYS, endpoint=endpoint)

    elif endpoint == "screener":
        filters = values.get("filters", "")
        if filters:
            try:
                parsed = json.loads(filters)
            except json.JSONDecodeError as exc:
                raise ValidationError("filters must be valid JSON") from exc
            if not isinstance(parsed, list):
                raise ValidationError("filters must be a JSON array")

    elif endpoint == "symbol_change_history":
        date_from = values.get("date_from")
        date_to = values.get("date_to")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValidationError("date_from must be earlier than or equal to date_to")


def _require_date_range(values: dict[str, Any], *, max_days: int, endpoint: str) -> None:
    date_from = values.get("date_from")
    date_to = values.get("date_to")
    if date_from is None or date_to is None:
        raise ValidationError(f"{endpoint} requires date_from and date_to")
    if date_from > date_to:
        raise ValidationError("date_from must be earlier than or equal to date_to")
    if (date_to - date_from).days > max_days:
        raise ValidationError(f"{endpoint} date range is capped at {max_days} days")


def _merged_params(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_params = payload.get("params", {})
    if raw_params is None:
        params: dict[str, Any] = {}
    elif isinstance(raw_params, Mapping):
        params = dict(raw_params)
    else:
        raise ValidationError("params must be a JSON object")

    for key, value in payload.items():
        if key not in {"params", "endpoint", "asset", "fmt", "preview_limit"} and key not in params:
            params[key] = value

    if "search_limit" in payload and "limit" not in params:
        params["limit"] = payload["search_limit"]

    return params


def _normalize_provider_symbols(raw: Any, exchange: str, max_items: int | None) -> tuple[str, ...]:
    symbols = []
    seen = set()
    for token in _split_symbols(raw):
        symbol = token.upper()
        if exchange == "US":
            if symbol.endswith(".US"):
                symbol = f"{_normalize_us_symbol_body(symbol[:-3])}.US"
            elif "." not in symbol:
                symbol = f"{_normalize_us_symbol_body(symbol)}.US"
            elif _is_us_class_symbol_body(symbol):
                symbol = f"{_normalize_us_symbol_body(symbol)}.US"
            elif _is_us_listing_venue_symbol(symbol):
                symbol = f"{_normalize_us_symbol_body(symbol.rsplit('.', 1)[0])}.US"
        elif "." not in symbol:
            symbol = f"{symbol}.{exchange}"
        _validate_symbol(symbol, "symbol")
        if symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    if max_items is not None and len(symbols) > max_items:
        raise ValidationError(f"symbols supports at most {max_items} symbols")
    return tuple(symbols)


def _normalize_bulk_symbols(raw: Any, exchange: str, max_items: int | None) -> tuple[str, ...]:
    symbols = []
    seen = set()
    for token in _split_symbols(raw):
        symbol = token.upper()
        if exchange == "US":
            if symbol.endswith(".US"):
                symbol = symbol[:-3]
            symbol = _normalize_us_symbol_body(symbol)
        if exchange != "US" and "." not in symbol:
            raise ValidationError("non-US bulk symbols must include an EODHD exchange suffix")
        _validate_symbol(symbol, "symbol")
        if symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    if max_items is not None and len(symbols) > max_items:
        raise ValidationError(f"symbols supports at most {max_items} symbols")
    return tuple(symbols)


def _normalize_us_symbol_body(symbol: str) -> str:
    if "." not in symbol:
        return symbol
    base, suffix = symbol.rsplit(".", 1)
    if base and suffix in US_CLASS_SUFFIXES:
        return f"{base}-{suffix}"
    if base and suffix in US_LISTING_SUFFIXES:
        return base
    return symbol


def _is_us_class_symbol_body(symbol: str) -> bool:
    if "." not in symbol:
        return False
    base, suffix = symbol.rsplit(".", 1)
    return bool(base) and suffix in US_CLASS_SUFFIXES


def _is_us_listing_venue_symbol(symbol: str) -> bool:
    if "." not in symbol:
        return False
    base, suffix = symbol.rsplit(".", 1)
    return bool(base) and suffix in US_LISTING_SUFFIXES


def _split_symbols(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        text = ",".join(str(item) for item in raw)
    else:
        text = str(raw)
    return [part.strip() for part in re.split(r"[\s,]+", text) if part.strip()]


def _validate_symbol(symbol: str, field_name: str) -> None:
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValidationError(f"{field_name} contains unsupported characters: {symbol}")


def _exchange(raw: str) -> str:
    exchange = raw.strip().upper() or "US"
    if not EXCHANGE_RE.fullmatch(exchange):
        raise ValidationError(f"exchange contains unsupported characters: {raw}")
    return exchange


def _choice(value: str, allowed: Mapping[str, Any] | set[str], field_name: str) -> str:
    normalized = value.strip()
    if field_name in {"endpoint", "asset", "fmt", "period", "order", "adjustment", "interval", "function"}:
        normalized = normalized.lower()
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValidationError(f"{field_name} must be one of: {allowed_text}")
    return normalized


def _optional_date(raw: Any, key: str) -> date | None:
    value = _text_from_raw(raw, key, "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{key} must use YYYY-MM-DD") from exc


def _optional_int(
    raw: Any,
    key: str,
    minimum: int | None,
    maximum: int | None,
    required: bool,
) -> int | None:
    text = _text_from_raw(raw, key, "").strip()
    if text == "":
        if required:
            raise ValidationError(f"{key} is required")
        return None
    try:
        value = int(text)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{key} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise ValidationError(f"{key} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{key} must be at most {maximum}")
    return value


def _int_between(
    payload: Mapping[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = payload.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{key} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValidationError(f"{key} must be between {minimum} and {maximum}")
    return value


def _bool(raw: Any, field_name: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw in (None, ""):
        return False
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValidationError(f"{field_name} must be boolean")


def _text(payload: Mapping[str, Any], key: str, default: str) -> str:
    return _text_from_raw(payload.get(key, default), key, default)


def _text_from_raw(value: Any, key: str, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    raise ValidationError(f"{key} must be text")


def _public_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return value


def _has_control_characters(text: str) -> bool:
    return any(ord(char) < 32 and char not in "\n\r\t" for char in text)
