from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable

from eodhd_codegen_app.client import EodhdExecutionError, EodhdHttpClient
from eodhd_codegen_app.request_model import EXCHANGE_RE, validate_payload
from eodhd_codegen_app.universe_db import DbUniverseRepository


VIRTUAL_EXCHANGES = frozenset({"INDX", "FOREX", "CC", "GBOND", "MONEY", "EUFUND"})


CATALOG_CATEGORIES: tuple[dict[str, Any], ...] = (
    {
        "id": "stock",
        "label": "Stocks",
        "cn": "股票",
        "venue_mode": "select",
        "default_type": "stock",
        "type_options": ("stock", "common_stock", "preferred_stock"),
        "help_text": "Choose a validated stock exchange, then optionally narrow the stock type.",
    },
    {
        "id": "etf",
        "label": "ETFs",
        "cn": "ETF",
        "venue_mode": "select",
        "default_type": "etf",
        "type_options": ("etf",),
        "help_text": "Choose a validated exchange; the request uses type=etf.",
    },
    {
        "id": "fund",
        "label": "Funds",
        "cn": "基金",
        "venue_mode": "fund",
        "fixed_exchange": "EUFUND",
        "default_type": "fund",
        "type_options": ("fund",),
        "help_text": "Use an exchange-listed fund directory or the official EUFUND virtual venue.",
    },
    {
        "id": "index",
        "label": "Indices",
        "cn": "指数",
        "venue_mode": "fixed",
        "fixed_exchange": "INDX",
        "default_type": "all",
        "type_options": ("all",),
        "help_text": "Lists index instruments only. Constituents require another EODHD product.",
    },
    {
        "id": "forex",
        "label": "Forex",
        "cn": "外汇",
        "venue_mode": "fixed",
        "fixed_exchange": "FOREX",
        "default_type": "all",
        "type_options": ("all",),
        "help_text": "Uses the official FOREX virtual venue.",
    },
    {
        "id": "crypto",
        "label": "Crypto",
        "cn": "加密资产",
        "venue_mode": "fixed",
        "fixed_exchange": "CC",
        "default_type": "all",
        "type_options": ("all",),
        "help_text": "Uses the official CC virtual venue.",
    },
    {
        "id": "government_bond",
        "label": "Government Bonds",
        "cn": "政府债券",
        "venue_mode": "fixed",
        "fixed_exchange": "GBOND",
        "default_type": "all",
        "type_options": ("all",),
        "help_text": "Uses the official GBOND virtual venue.",
    },
    {
        "id": "benchmark",
        "label": "Reference Rates / Benchmarks",
        "cn": "基准利率",
        "venue_mode": "fixed",
        "fixed_exchange": "MONEY",
        "default_type": "all",
        "type_options": ("all",),
        "help_text": "Uses the official MONEY virtual venue.",
    },
)


class ExchangeDirectoryCache:
    """Process-local, single-flight cache for the EODHD exchange directory."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._rows: tuple[dict[str, Any], ...] = ()
        self._loaded_at = ""

    def snapshot(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        with self._lock:
            rows = [dict(row) for row in self._rows]
            loaded_at = self._loaded_at
        return rows, {
            "loaded": bool(loaded_at),
            "loaded_at": loaded_at,
            "row_count": len(rows),
        }

    def get_or_load(self, loader: Callable[[], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], bool]:
        with self._lock:
            if self._loaded_at:
                return [dict(row) for row in self._rows], True
            rows = loader()
            self._rows = tuple(dict(row) for row in rows)
            self._loaded_at = datetime.now(timezone.utc).isoformat()
            return [dict(row) for row in self._rows], False


def catalog_menu_payload(
    *,
    repository: Any | None = None,
    cache: ExchangeDirectoryCache | None = None,
) -> dict[str, Any]:
    repo = repository or DbUniverseRepository.from_environment()
    exchange_cache = cache or ExchangeDirectoryCache()
    status = repo.status()
    facets = repo.menu_facets() if status.available else {"exchanges": [], "asset_types": []}
    eodhd_rows, cache_status = exchange_cache.snapshot()
    local_rows = _local_exchange_rows(facets.get("exchanges", []))
    asset_counts = {
        str(row.get("id", "")).lower(): int(row.get("count", 0))
        for row in facets.get("asset_types", [])
    }
    categories = []
    for category in CATALOG_CATEGORIES:
        public = dict(category)
        public["type_options"] = list(public["type_options"])
        public["local_count"] = asset_counts.get(str(public["id"]), 0)
        categories.append(public)

    return {
        "db": status.as_dict(),
        "categories": categories,
        "exchanges": merge_exchange_rows(local_rows, eodhd_rows),
        "eodhd_cache": cache_status,
        "index_constituents": {
            "enabled": False,
            "reason": "Index constituents require EODHD Fundamentals or a separate constituents product.",
        },
    }


def load_eodhd_exchange_directory(
    *,
    api_key: str,
    client: EodhdHttpClient,
    repository: Any | None = None,
    cache: ExchangeDirectoryCache,
) -> dict[str, Any]:
    if not api_key:
        raise EodhdExecutionError("No EODHD API token is configured. Use Login / Config first.")

    calls_made = 0

    def loader() -> list[dict[str, Any]]:
        nonlocal calls_made
        request = validate_payload(
            {
                "asset": "instrument",
                "endpoint": "exchanges_list",
                "preview_limit": 500,
            }
        )
        result = client.execute(request, api_key=api_key)
        calls_made = result.requests_made
        rows = normalize_eodhd_exchange_rows(result.rows)
        if not rows:
            raise EodhdExecutionError("EODHD exchange directory returned no valid exchange rows")
        return rows

    _, cache_hit = cache.get_or_load(loader)
    payload = catalog_menu_payload(repository=repository, cache=cache)
    payload["api_calls"] = 0 if cache_hit else calls_made
    payload["cache_hit"] = cache_hit
    return payload


def normalize_eodhd_exchange_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = _row_value(row, "Code", "code").upper()
        if not EXCHANGE_RE.fullmatch(code):
            continue
        name = _row_value(row, "Name", "name") or code
        normalized[code] = {
            "code": code,
            "label": name,
            "name": name,
            "country": _row_value(row, "Country", "country"),
            "currency": _row_value(row, "Currency", "currency"),
            "operating_mic": _row_value(row, "OperatingMIC", "operating_mic"),
            "local_count": 0,
            "sources": ["eodhd"],
        }
    return [normalized[code] for code in sorted(normalized)]


def merge_exchange_rows(
    local_rows: list[dict[str, Any]],
    eodhd_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in [*local_rows, *eodhd_rows]:
        code = str(row.get("code", "")).strip().upper()
        if not EXCHANGE_RE.fullmatch(code) or code in VIRTUAL_EXCHANGES:
            continue
        existing = merged.setdefault(
            code,
            {
                "code": code,
                "label": str(row.get("label") or row.get("name") or code),
                "name": str(row.get("name") or row.get("label") or code),
                "country": "",
                "currency": "",
                "operating_mic": "",
                "local_count": 0,
                "sources": [],
            },
        )
        for key in ("label", "name", "country", "currency", "operating_mic"):
            value = str(row.get(key, "")).strip()
            if value and (not existing[key] or key in {"label", "name"} and "eodhd" in row.get("sources", [])):
                existing[key] = value
        existing["local_count"] = max(int(existing["local_count"]), int(row.get("local_count", 0)))
        for source in row.get("sources", []):
            if source not in existing["sources"]:
                existing["sources"].append(source)
    return [merged[code] for code in sorted(merged)]


def _local_exchange_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "code": str(row.get("code", "")).strip().upper(),
            "label": str(row.get("label") or row.get("code") or "").strip(),
            "name": str(row.get("label") or row.get("code") or "").strip(),
            "country": "",
            "currency": "",
            "operating_mic": "",
            "local_count": int(row.get("count", 0)),
            "sources": ["local_db"],
        }
        for row in rows
    ]


def _row_value(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""
