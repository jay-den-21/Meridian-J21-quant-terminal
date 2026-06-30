from __future__ import annotations

import re
from typing import Any

from eodhd_codegen_app.universe_db import (
    DEFAULT_MARKET,
    MAJOR_US_EXCHANGES,
    MAX_UNIVERSE_ROWS,
    DatabaseStatus,
    DbUniverseRepository,
    PoolQuery,
)


SYMBOL_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
US_CLASS_SUFFIXES = {"A", "B", "C", "K"}

PRESET_POOLS = {
    "us_major_common": {
        "label": "US major venues common stocks",
        "source_label": "Database preset",
        "asset_types": ("stock",),
        "exchanges": MAJOR_US_EXCHANGES,
        "exclude_otc": True,
        "description": "Active US stock instruments on NYSE/NASDAQ/AMEX/ARCA/BATS.",
    },
    "us_active_stocks": {
        "label": "US active stocks",
        "source_label": "Database preset",
        "asset_types": ("stock",),
        "exchanges": (),
        "exclude_otc": False,
        "description": "All active US stock instruments currently stored in the database.",
    },
    "us_etfs": {
        "label": "US ETFs",
        "source_label": "Database preset",
        "asset_types": ("etf",),
        "exchanges": (),
        "exclude_otc": False,
        "description": "Active US ETF instruments currently stored in the database.",
    },
}

DEFAULT_DB_UNAVAILABLE = DatabaseStatus(
    configured=False,
    available=False,
    source="none",
    message="Database pool source is not configured.",
)


def menu_payload(*, repository: Any | None = None) -> dict[str, object]:
    repo = repository or DbUniverseRepository.from_environment()
    status = repo.status()
    facets = repo.menu_facets() if status.available else {"exchanges": [], "asset_types": []}
    db_enabled = bool(status.available)
    db_disabled_reason = "" if db_enabled else status.message
    return {
        "db": status.as_dict(),
        "categories": [
            {
                "id": "preset",
                "label": "Preset Pools",
                "cn": "预设池",
                "enabled": db_enabled,
                "source": "Database instrument",
                "disabled_reason": db_disabled_reason,
            },
            {
                "id": "exchange",
                "label": "Exchange",
                "cn": "交易所",
                "enabled": db_enabled,
                "source": "Database instrument",
                "disabled_reason": db_disabled_reason,
            },
            {
                "id": "asset_type",
                "label": "Asset Type",
                "cn": "资产类型",
                "enabled": db_enabled,
                "source": "Database instrument",
                "disabled_reason": db_disabled_reason,
            },
            {
                "id": "index_assets",
                "label": "Index Assets",
                "cn": "指数资产",
                "enabled": db_enabled,
                "source": "Database instrument",
                "disabled_reason": db_disabled_reason,
                "help_text": "These are index instruments, not index constituent memberships.",
            },
            {
                "id": "sectors",
                "label": "Sectors",
                "cn": "行业",
                "enabled": False,
                "source": "Not configured",
                "disabled_reason": "No sector/industry taxonomy table exists in the current database schema.",
            },
        ],
        "preset_pools": [
            {"id": key, **value}
            for key, value in PRESET_POOLS.items()
        ],
        "exchanges": facets["exchanges"],
        "asset_types": facets["asset_types"],
        "unsupported": [
            {
                "id": "index_constituents",
                "label": "Official index constituents",
                "reason": "Current DB has index assets but no index constituent membership table.",
            },
            {
                "id": "sector_members",
                "label": "Sector/industry members",
                "reason": "Current DB has no sector/industry taxonomy table.",
            },
        ],
    }


def load_universe(payload: dict[str, Any], *, repository: Any | None = None) -> dict[str, object]:
    repo = repository or DbUniverseRepository.from_environment()
    status = repo.status()
    if not status.available:
        return {
            "source": str(payload.get("source", "preset")),
            "label": "Database pool unavailable",
            "db": status.as_dict(),
            "unavailable": True,
            "rows": [],
        }
    query = build_pool_query(payload)
    try:
        rows = repo.load_rows(query)
    except Exception:
        failed_status = DatabaseStatus(
            configured=status.configured,
            available=False,
            source=status.source,
            message="Database pool query failed. Check us_share.instrument availability and filters.",
        )
        return {
            "source": query.source,
            "label": "Database pool unavailable",
            "db": failed_status.as_dict(),
            "unavailable": True,
            "rows": [],
        }
    return {
        "source": query.source,
        "label": query.label,
        "db": status.as_dict(),
        "unavailable": False,
        "rows": rows,
    }


def resolve_universe_symbols(payload: dict[str, Any], *, repository: Any | None = None) -> dict[str, object]:
    repo = repository or DbUniverseRepository.from_environment()
    status = repo.status()
    raw_tokens = payload.get("tokens", [])
    if not isinstance(raw_tokens, list):
        raise ValueError("tokens must be a list")

    original_tokens = [_clean_text(token) for token in raw_tokens if _clean_text(token)][:MAX_UNIVERSE_ROWS]
    invalid = [token.upper() for token in original_tokens if not SYMBOL_TOKEN_RE.fullmatch(token)]
    valid_tokens = [token for token in original_tokens if SYMBOL_TOKEN_RE.fullmatch(token)]
    query_tokens = sorted({variant for token in valid_tokens for variant in _symbol_match_variants(token)})

    if not status.available:
        return {
            "db": status.as_dict(),
            "unavailable": True,
            "resolved": [],
            "unmatched": [token.upper() for token in valid_tokens],
            "invalid": invalid,
        }
    try:
        rows = repo.resolve_symbols(tuple(query_tokens), market=DEFAULT_MARKET)
    except Exception:
        failed_status = DatabaseStatus(
            configured=status.configured,
            available=False,
            source=status.source,
            message="Database symbol resolve failed. Check us_share.instrument availability.",
        )
        return {
            "db": failed_status.as_dict(),
            "unavailable": True,
            "resolved": [],
            "unmatched": [token.upper() for token in valid_tokens],
            "invalid": invalid,
        }

    row_by_key: dict[str, dict[str, str]] = {}
    for row in rows:
        for key in (row.get("symbol", ""), row.get("provider_symbol", "")):
            clean_key = _clean_text(key).lower()
            if clean_key and clean_key not in row_by_key:
                row_by_key[clean_key] = row

    resolved: list[dict[str, object]] = []
    unmatched: list[str] = []
    for token in valid_tokens:
        row = next((row_by_key.get(variant.lower()) for variant in _symbol_match_variants(token) if row_by_key.get(variant.lower())), None)
        if row is None:
            unmatched.append(token.upper())
        else:
            resolved.append({"input": token.upper(), "row": row})

    return {
        "db": status.as_dict(),
        "unavailable": False,
        "resolved": resolved,
        "unmatched": unmatched,
        "invalid": invalid,
    }


def build_pool_query(payload: dict[str, Any]) -> PoolQuery:
    source = _clean_text(payload.get("source") or "preset").lower()
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    active_only = _bool(filters.get("active_only"), default=True)
    exclude_otc = _bool(filters.get("exclude_otc"), default=False)
    text_search = _clean_text(filters.get("text_search"))[:80]
    override_exchange = _clean_text(filters.get("exchange")).upper()
    override_asset_type = _clean_text(filters.get("asset_type")).lower()

    if source == "preset":
        preset_id = _clean_text(payload.get("preset") or "us_major_common").lower()
        preset = PRESET_POOLS.get(preset_id)
        if preset is None:
            raise ValueError("unknown preset pool")
        exchanges = tuple(preset["exchanges"])
        asset_types = tuple(preset["asset_types"])
        exclude_otc = _bool(filters.get("exclude_otc"), default=bool(preset["exclude_otc"]))
        label = str(preset["label"])
        query_source = "db_preset"
    elif source == "exchange":
        exchange = _required_code(payload.get("exchange"), "exchange")
        exchanges = (exchange,)
        asset_types = (_clean_text(payload.get("asset_type") or "stock").lower(),)
        label = f"{exchange} {asset_types[0]}"
        query_source = "db_exchange"
    elif source == "asset_type":
        asset_type = _required_code(payload.get("asset_type"), "asset_type").lower()
        exchanges = ()
        asset_types = (asset_type,)
        label = f"{asset_type} instruments"
        query_source = "db_asset_type"
    elif source == "index_assets":
        exchanges = ()
        asset_types = ("index",)
        label = "Index assets"
        query_source = "db_index_assets"
    elif source == "sectors":
        raise ValueError("sector/industry pools are not configured")
    else:
        raise ValueError("source must be preset, exchange, asset_type, index_assets, or sectors")

    if source != "index_assets":
        if override_exchange:
            exchanges = (override_exchange,)
        if override_asset_type:
            asset_types = (override_asset_type,)

    return PoolQuery(
        source=query_source,
        label=label,
        market=DEFAULT_MARKET,
        active_only=active_only,
        exchanges=exchanges,
        asset_types=asset_types,
        exclude_otc=exclude_otc,
        text_search=text_search,
        limit=MAX_UNIVERSE_ROWS,
    )


def _required_code(value: Any, name: str) -> str:
    text = _clean_text(value).upper()
    if not text or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-" for char in text):
        raise ValueError(f"{name} is required")
    return text


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _symbol_match_variants(token: str) -> tuple[str, ...]:
    text = token.strip().upper()
    variants = [text]
    if "." in text:
        base, suffix = text.rsplit(".", 1)
        if base and suffix in US_CLASS_SUFFIXES:
            variants.extend([f"{base}-{suffix}", f"{base}-{suffix}.US"])
    return tuple(dict.fromkeys(variants))
