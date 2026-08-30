"""Static Tushare endpoint inventory and executable core contracts."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from fdp_cn.tushare.errors import TushareCapabilityError, TushareCatalogError
from fdp_cn.tushare.models import (
    AccessSpec,
    CapabilitySpec,
    EndpointSpec,
    FanoutSpec,
    PaginationSpec,
    ParameterSpec,
)


CATALOG_VARIANT_COUNT = 93
CATALOG_TABLE_COUNT = 88
CATALOG_REVIEW_DATE = "2026-08-30"
DEFAULT_ACCOUNT_POINTS_TIER = 10_000
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_REQUEST_PARAMS = {
    "api_name",
    "fields",
    "limit",
    "offset",
    "schema",
    "table",
    "token",
}


_CORE_ALIASES = {
    "trade_cal": ("calendar.trade_cal", "get_tradeCal", "get_trade_cal"),
    "stock_basic": ("stk.stock_basic", "get_stk_basic"),
    "stock_basic_all": ("stk.stock_basic_all", "get_stk_basic_all"),
    "index_classify": ("idx.index_classify", "get_idx_sw_classify"),
    "daily": ("stk.daily", "get_stk_daily"),
    "sw_daily": ("idx.sw_daily", "get_idx_sw_daily"),
    "cyq_chips": ("stk.cyq_chips", "get_stk_cyq_chips"),
    "idx.idx_basic": ("index_basic", "get_idx_basic"),
}

# The preserved base class name is not always the complete request contract.
# These two codelist getters also pass start/end dates to Tushare.
_LEGACY_SCOPE_OVERRIDES = {
    "fin.fin_income": "code_date_range",
    "fut.fut_mapping": "code_date_range",
}


def _column_types(
    *, text: tuple[str, ...], dates: tuple[str, ...], decimals: tuple[str, ...]
):
    return {
        **{name: "text" for name in text},
        **{name: "date" for name in dates},
        **{name: "decimal" for name in decimals},
    }


_STOCK_BASIC_FIELDS = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "cnspell",
    "market",
    "list_date",
    "act_name",
    "act_ent_type",
)
_STOCK_BASIC_ALL_FIELDS = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "market",
    "list_date",
    "fullname",
    "enname",
    "cnspell",
    "exchange",
    "curr_type",
    "list_status",
    "delist_date",
    "is_hs",
)
_DAILY_DECIMALS = (
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)
_SW_DAILY_DECIMALS = (
    "open",
    "low",
    "high",
    "close",
    "change",
    "pct_change",
    "vol",
    "amount",
    "pe",
    "pb",
    "float_mv",
    "total_mv",
)
_INDEX_BASIC_FIELDS = (
    "ts_code",
    "name",
    "market",
    "publisher",
    "category",
    "base_date",
    "base_point",
    "list_date",
    "fullname",
    "index_type",
    "weight_rule",
    "desc",
    "exp_date",
)


_CORE_CONTRACTS: dict[str, dict[str, object]] = {
    "trade_cal": {
        "fields": ("exchange", "cal_date", "is_open", "pretrade_date"),
        "column_types": _column_types(
            text=("exchange", "is_open"),
            dates=("cal_date", "pretrade_date"),
            decimals=(),
        ),
        "nullable_columns": frozenset({"pretrade_date"}),
        "text_min_lengths": {"exchange": 20, "is_open": 1},
        "request_params": {
            "exchange": ParameterSpec("text"),
            "start_date": ParameterSpec("date"),
            "end_date": ParameterSpec("date"),
            "is_open": ParameterSpec("choice", choices=("0", "1")),
        },
        "scope_kind": "date_range",
        "official_url": "https://tushare.pro/document/2?doc_id=26",
    },
    "stock_basic": {
        "fields": _STOCK_BASIC_FIELDS,
        "column_types": _column_types(
            text=tuple(name for name in _STOCK_BASIC_FIELDS if name != "list_date"),
            dates=("list_date",),
            decimals=(),
        ),
        "nullable_columns": frozenset(
            set(_STOCK_BASIC_FIELDS)
            - {"ts_code", "symbol", "name", "market", "list_date"}
        ),
        "text_min_lengths": {
            "ts_code": 20,
            "symbol": 20,
            "name": 50,
            "area": 50,
            "industry": 50,
            "cnspell": 50,
            "market": 20,
            "act_name": 200,
            "act_ent_type": 50,
        },
        "request_params": {
            "ts_code": ParameterSpec("text"),
            "name": ParameterSpec("text"),
            "exchange": ParameterSpec("text"),
            "market": ParameterSpec("text"),
            "is_hs": ParameterSpec("choice", choices=("N", "H", "S")),
        },
        "fixed_params": {"list_status": "L"},
        "scope_kind": "single",
        "official_url": "https://tushare.pro/document/2?doc_id=25",
    },
    "stock_basic_all": {
        "fields": _STOCK_BASIC_ALL_FIELDS,
        "column_types": _column_types(
            text=tuple(name for name in _STOCK_BASIC_ALL_FIELDS if name != "list_date"),
            dates=("list_date",),
            decimals=(),
        ),
        "nullable_columns": frozenset(
            set(_STOCK_BASIC_ALL_FIELDS)
            - {"ts_code", "symbol", "name", "list_date", "list_status"}
        ),
        "text_min_lengths": {
            "ts_code": 20,
            "symbol": 20,
            "name": 50,
            "area": 50,
            "industry": 50,
            "market": 20,
            "fullname": 200,
            "enname": 200,
            "cnspell": 50,
            "exchange": 20,
            "curr_type": 20,
            "list_status": 1,
            "delist_date": 8,
            "is_hs": 1,
        },
        "request_params": {
            "ts_code": ParameterSpec("text"),
            "name": ParameterSpec("text"),
            "exchange": ParameterSpec("text"),
            "market": ParameterSpec("text"),
            "is_hs": ParameterSpec("choice", choices=("N", "H", "S")),
        },
        "fanouts": (FanoutSpec("list_status", ("L", "D", "P")),),
        "scope_kind": "single",
        "official_url": "https://tushare.pro/document/2?doc_id=25",
    },
    "index_classify": {
        "fields": (
            "index_code",
            "industry_name",
            "parent_code",
            "level",
            "industry_code",
            "is_pub",
            "src",
        ),
        "column_types": _column_types(
            text=(
                "index_code",
                "industry_name",
                "parent_code",
                "level",
                "industry_code",
                "is_pub",
                "src",
            ),
            dates=(),
            decimals=(),
        ),
        "nullable_columns": frozenset({"parent_code", "industry_code", "is_pub"}),
        "text_min_lengths": {
            "index_code": 20,
            "industry_name": 20,
            "parent_code": 20,
            "level": 20,
            "industry_code": 20,
            "is_pub": 20,
            "src": 20,
        },
        "request_params": {
            "index_code": ParameterSpec("text"),
            "parent_code": ParameterSpec("text"),
        },
        "fanouts": (
            FanoutSpec("src", ("SW2014", "SW2021")),
            FanoutSpec("level", ("L1", "L2", "L3")),
        ),
        "scope_kind": "single",
        "official_url": "https://tushare.pro/document/2?doc_id=181",
    },
    "idx.idx_basic": {
        "fields": _INDEX_BASIC_FIELDS,
        "column_types": _column_types(
            text=tuple(
                name
                for name in _INDEX_BASIC_FIELDS
                if name not in {"base_date", "base_point", "list_date"}
            ),
            dates=("base_date", "list_date"),
            decimals=("base_point",),
        ),
        "nullable_columns": frozenset(
            {
                "base_date",
                "base_point",
                "list_date",
                "fullname",
                "index_type",
                "weight_rule",
                "desc",
                "exp_date",
            }
        ),
        "text_min_lengths": {
            "ts_code": 20,
            "name": 250,
            "market": 20,
            "publisher": 250,
            "category": 50,
            "fullname": 200,
            "index_type": 50,
            "weight_rule": 100,
            "desc": 200,
            "exp_date": 8,
        },
        "request_params": {
            "ts_code": ParameterSpec("text"),
            "name": ParameterSpec("text"),
            "market": ParameterSpec("text"),
            "publisher": ParameterSpec("text"),
            "category": ParameterSpec("text"),
        },
        "scope_kind": "single",
        "official_url": "https://tushare.pro/document/2?doc_id=94",
    },
    "daily": {
        "fields": ("ts_code", "trade_date", *_DAILY_DECIMALS),
        "column_types": _column_types(
            text=("ts_code",),
            dates=("trade_date",),
            decimals=_DAILY_DECIMALS,
        ),
        "nullable_columns": frozenset({"pre_close", "change", "pct_chg"}),
        "text_min_lengths": {"ts_code": 20},
        "request_params": {
            "ts_code": ParameterSpec("text"),
            "trade_date": ParameterSpec("date"),
            "start_date": ParameterSpec("date"),
            "end_date": ParameterSpec("date"),
        },
        "scope_kind": "date_range",
        "official_url": "https://tushare.pro/document/2?doc_id=27",
    },
    "sw_daily": {
        "fields": ("ts_code", "trade_date", "name", *_SW_DAILY_DECIMALS),
        "column_types": _column_types(
            text=("ts_code", "name"),
            dates=("trade_date",),
            decimals=_SW_DAILY_DECIMALS,
        ),
        # Historic SW rows may have no quote/turnover values for a valid key.
        "nullable_columns": frozenset(_SW_DAILY_DECIMALS),
        "text_min_lengths": {"ts_code": 20, "name": 200},
        "request_params": {
            "ts_code": ParameterSpec("text"),
            "trade_date": ParameterSpec("date"),
            "start_date": ParameterSpec("date"),
            "end_date": ParameterSpec("date"),
        },
        "scope_kind": "date_range",
        "official_url": "https://tushare.pro/document/2?doc_id=327",
    },
    "cyq_chips": {
        "fields": ("ts_code", "trade_date", "price", "percent"),
        "column_types": _column_types(
            text=("ts_code",),
            dates=("trade_date",),
            decimals=("price", "percent"),
        ),
        "nullable_columns": frozenset(),
        "text_min_lengths": {"ts_code": 20},
        "request_params": {
            "ts_code": ParameterSpec("text"),
            "trade_date": ParameterSpec("date"),
            "start_date": ParameterSpec("date"),
            "end_date": ParameterSpec("date"),
        },
        "scope_kind": "code_date_range",
        "prerequisites": ("hq_stk_basic",),
        "official_url": "https://tushare.pro/document/2?doc_id=294",
    },
}


def _load_catalog() -> tuple[EndpointSpec, ...]:
    seed_path = files("fdp_cn.tushare").joinpath("catalog_seed.json")
    try:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TushareCatalogError("Tushare catalog seed could not be loaded") from error
    if not isinstance(seed, dict) or seed.get("schema_version") != 2:
        raise TushareCatalogError(
            "Tushare catalog seed has an unsupported schema version"
        )
    raw_entries = seed.get("entries")
    if not isinstance(raw_entries, list) or len(raw_entries) != CATALOG_VARIANT_COUNT:
        raise TushareCatalogError(
            "Tushare catalog seed must contain exactly 93 variants"
        )
    legacy_leaf_counts = _legacy_leaf_counts(raw_entries)
    result = tuple(
        _endpoint_from_seed(raw, legacy_leaf_counts=legacy_leaf_counts)
        for raw in raw_entries
    )
    _validate_catalog(result)
    return result


def _endpoint_from_seed(
    raw: object, *, legacy_leaf_counts: Mapping[str, int]
) -> EndpointSpec:
    if not isinstance(raw, dict):
        raise TushareCatalogError("Tushare catalog entries must be objects")
    key = _required_text(raw, "key")
    access_value = _required_mapping(raw, "access")
    capability_value = _required_mapping(raw, "capability")
    pagination_value = _required_mapping(raw, "pagination")
    overlay = _CORE_CONTRACTS.get(key, {})
    raw_aliases = _required_string_list(raw, "aliases")
    legacy_id = _required_text(raw, "legacy_id")
    legacy_leaf = _legacy_leaf(legacy_id)
    unique_legacy_alias = (
        (legacy_leaf,) if legacy_leaf_counts[legacy_leaf] == 1 else ()
    )
    aliases = tuple(
        dict.fromkeys(
            (*raw_aliases, *_CORE_ALIASES.get(key, ()), *unique_legacy_alias)
        )
    )
    profile = _required_text(raw, "profile")
    scope_kind = overlay.get(
        "scope_kind",
        _LEGACY_SCOPE_OVERRIDES.get(key, _scope_kind(profile)),
    )
    try:
        access = AccessSpec(
            kind=_required_text(access_value, "kind"),  # type: ignore[arg-type]
            reason=_required_text(access_value, "reason"),
            points_tier=_optional_positive_int(
                access_value.get("points_tier"), field_name="points_tier"
            ),
        )
    except ValueError as error:
        raise TushareCatalogError(
            f"Invalid access contract for {key}: {error}"
        ) from error
    return EndpointSpec(
        key=key,
        legacy_id=legacy_id,
        aliases=aliases,
        category=_required_text(raw, "category"),
        api_name=_required_text(raw, "api_name"),
        target_table=_required_text(raw, "target_table"),
        access=access,
        capability=CapabilitySpec(
            kind=_required_text(capability_value, "kind"),  # type: ignore[arg-type]
            reason=_optional_text(capability_value.get("reason")),
        ),
        pagination=PaginationSpec(
            kind=_required_text(pagination_value, "kind"),  # type: ignore[arg-type]
            page_limit=_optional_positive_int(pagination_value.get("page_limit")),
            source=_required_text(pagination_value, "source"),
        ),
        scope_kind=scope_kind,  # type: ignore[arg-type]
        business_key=_required_string_list(raw, "business_key"),
        fields=overlay.get("fields", ()),  # type: ignore[arg-type]
        column_types=overlay.get("column_types", {}),  # type: ignore[arg-type]
        text_min_lengths=overlay.get("text_min_lengths", {}),  # type: ignore[arg-type]
        nullable_columns=overlay.get("nullable_columns", frozenset()),  # type: ignore[arg-type]
        field_aliases=overlay.get("field_aliases", {}),  # type: ignore[arg-type]
        request_params=overlay.get("request_params", {}),  # type: ignore[arg-type]
        fixed_params=overlay.get("fixed_params", {}),  # type: ignore[arg-type]
        fanouts=overlay.get("fanouts", ()),  # type: ignore[arg-type]
        prerequisites=overlay.get("prerequisites", ()),  # type: ignore[arg-type]
        official_url=overlay.get("official_url"),  # type: ignore[arg-type]
        reviewed_on=CATALOG_REVIEW_DATE,
        description=_required_text(raw, "description"),
        legacy_path=_required_text(raw, "legacy_path"),
        legacy_profile=profile,
        required_inputs=_required_string_list(raw, "required_inputs"),
        frequency=_optional_text(raw.get("freq")),
        source_variant=_optional_text(raw.get("src")),
    )


def _validate_catalog(catalog: tuple[EndpointSpec, ...]) -> None:
    if len({spec.key for spec in catalog}) != CATALOG_VARIANT_COUNT:
        raise TushareCatalogError("Tushare catalog keys must be unique")
    if len({spec.target_table for spec in catalog}) != CATALOG_TABLE_COUNT:
        raise TushareCatalogError(
            "Tushare catalog must expose exactly 88 target tables"
        )
    lookup_names: dict[str, str] = {}
    for spec in catalog:
        for identifier in (spec.target_table, *spec.business_key, *spec.fields):
            if not _IDENTIFIER.fullmatch(identifier):
                raise TushareCatalogError(f"Invalid catalog identifier for {spec.key}")
        for name in (spec.key, *spec.aliases):
            normalized = name.strip().casefold()
            owner = lookup_names.setdefault(normalized, spec.key)
            if owner != spec.key:
                raise TushareCatalogError(
                    f"Catalog alias collision between {owner} and {spec.key}"
                )
        if spec.executable:
            _validate_executable_spec(spec)
        if spec.category == "realtime" and spec.capability.kind != "disabled_realtime":
            raise TushareCatalogError("Realtime variants must remain disabled")


def _validate_executable_spec(spec: EndpointSpec) -> None:
    if spec.api_name == "UNSUPPORTED":
        raise TushareCatalogError(f"Executable endpoint {spec.key} has no API mapping")
    if not spec.fields or len(spec.fields) != len(set(spec.fields)):
        raise TushareCatalogError(
            f"Executable endpoint {spec.key} requires unique fields"
        )
    if not spec.business_key or not set(spec.business_key).issubset(spec.fields):
        raise TushareCatalogError(
            f"Executable endpoint {spec.key} has an invalid business key"
        )
    if set(spec.column_types) != set(spec.fields):
        raise TushareCatalogError(
            f"Executable endpoint {spec.key} must type every field"
        )
    text_fields = {
        name for name, column_type in spec.column_types.items() if column_type == "text"
    }
    if set(spec.text_min_lengths) != text_fields or any(
        name not in spec.fields
        or spec.column_types.get(name) != "text"
        or isinstance(length, bool)
        or not isinstance(length, int)
        or length <= 0
        for name, length in spec.text_min_lengths.items()
    ):
        raise TushareCatalogError(
            f"Executable endpoint {spec.key} has invalid text lengths"
        )
    if not spec.nullable_columns.issubset(spec.fields):
        raise TushareCatalogError(
            f"Executable endpoint {spec.key} has unknown nullable columns"
        )
    if set(spec.business_key) & spec.nullable_columns:
        raise TushareCatalogError(
            f"Executable endpoint {spec.key} cannot have nullable keys"
        )
    if not set(spec.field_aliases.values()).issubset(spec.fields):
        raise TushareCatalogError(
            f"Executable endpoint {spec.key} has an invalid field alias"
        )
    for name in spec.request_params:
        if name.casefold() in _RESERVED_REQUEST_PARAMS:
            raise TushareCatalogError(
                f"Executable endpoint {spec.key} exposes reserved parameter {name}"
            )
    generated = set(spec.fixed_params)
    for fanout in spec.fanouts:
        generated.add(fanout.parameter)
        generated.update(fanout.fixed_params)
    if generated & set(spec.request_params):
        raise TushareCatalogError(
            f"Executable endpoint {spec.key} exposes generated parameters"
        )


def _scope_kind(profile: str) -> str:
    if profile.startswith("realtime"):
        return "realtime"
    if "codelist" in profile and ("date" in profile or "period" in profile):
        return "code_date_range"
    if "codelist" in profile:
        return "code_list"
    if "date" in profile or "period" in profile:
        return "date_range"
    return "single"


def _legacy_leaf_counts(raw_entries: Sequence[object]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise TushareCatalogError("Tushare catalog entries must be objects")
        counts[_legacy_leaf(_required_text(raw, "legacy_id"))] += 1
    return counts


def _legacy_leaf(legacy_id: str) -> str:
    _, separator, leaf = legacy_id.rpartition(".")
    if not separator or not _IDENTIFIER.fullmatch(leaf):
        raise TushareCatalogError(f"Invalid legacy endpoint id: {legacy_id}")
    return leaf


def _required_mapping(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    item = value.get(name)
    if not isinstance(item, dict):
        raise TushareCatalogError(f"Catalog field {name} must be an object")
    return item


def _required_text(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise TushareCatalogError(f"Catalog field {name} must be non-empty text")
    return item


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise TushareCatalogError("Optional catalog text must be null or non-empty")
    return value


def _required_string_list(value: Mapping[str, object], name: str) -> tuple[str, ...]:
    item = value.get(name)
    if not isinstance(item, list) or not all(
        isinstance(part, str) and part for part in item
    ):
        raise TushareCatalogError(f"Catalog field {name} must be a text list")
    return tuple(item)


def _optional_positive_int(
    value: object, *, field_name: str = "page_limit"
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TushareCatalogError(
            f"Catalog {field_name} must be null or a positive integer"
        )
    return value


CATALOG = _load_catalog()
CATALOG_BY_KEY: Mapping[str, EndpointSpec] = MappingProxyType(
    {spec.key: spec for spec in CATALOG}
)
_CATALOG_LOOKUP: Mapping[str, EndpointSpec] = MappingProxyType(
    {
        name.strip().casefold(): spec
        for spec in CATALOG
        for name in (spec.key, *spec.aliases)
    }
)


def get_endpoint_spec(name: str) -> EndpointSpec:
    """Resolve a stable key or an explicit catalog alias."""
    if not isinstance(name, str) or not name.strip():
        raise TushareCatalogError("Tushare endpoint name must not be empty")
    try:
        return _CATALOG_LOOKUP[name.strip().casefold()]
    except KeyError as error:
        raise TushareCatalogError(f"Unknown Tushare endpoint: {name}") from error


def require_executable_endpoint(name: str) -> EndpointSpec:
    spec = get_endpoint_spec(name)
    if not spec.executable:
        reason = spec.capability.reason or "endpoint is disabled"
        raise TushareCapabilityError(
            f"Tushare endpoint {spec.key} is not executable: {reason}"
        )
    return spec


def iter_endpoint_specs(category: str | None = None) -> Iterator[EndpointSpec]:
    """Iterate in reviewed seed order, optionally restricted to one category."""
    normalized = category.strip().casefold() if isinstance(category, str) else None
    for spec in CATALOG:
        if normalized is None or spec.category.casefold() == normalized:
            yield spec


def is_standard_points_eligible(
    spec: EndpointSpec,
    *,
    account_points_tier: int = DEFAULT_ACCOUNT_POINTS_TIER,
) -> bool:
    """Return whether one historical endpoint belongs in a points-tier batch."""
    if (
        isinstance(account_points_tier, bool)
        or not isinstance(account_points_tier, int)
        or account_points_tier <= 0
    ):
        raise ValueError("account_points_tier must be a positive integer")
    return (
        spec.category != "realtime"
        and spec.capability.kind in {"executable", "catalogued_not_implemented"}
        and spec.access.kind == "standard_points"
        and spec.access.points_tier is not None
        and spec.access.points_tier <= account_points_tier
    )


def standard_points_endpoint_specs(
    account_points_tier: int = DEFAULT_ACCOUNT_POINTS_TIER,
) -> tuple[EndpointSpec, ...]:
    """Return direct and compatibility endpoints for one reviewed points tier."""
    return tuple(
        spec
        for spec in CATALOG
        if is_standard_points_eligible(
            spec, account_points_tier=account_points_tier
        )
    )


def default_historical_endpoint_specs() -> tuple[EndpointSpec, ...]:
    """Return the direct Job subset of the 10,000-point inventory."""
    return tuple(spec for spec in standard_points_endpoint_specs() if spec.executable)


def catalog_summary(spec: EndpointSpec) -> dict[str, Any]:
    """Return a JSON-safe projection for CLI/Menu endpoint listing."""
    return {
        "key": spec.key,
        "category": spec.category,
        "api_name": spec.api_name,
        "table": spec.target_table,
        "access": spec.access.kind,
        "access_reason": spec.access.reason,
        "points_tier": spec.access.points_tier,
        "capability": spec.capability.kind,
        "capability_reason": spec.capability.reason,
        "pagination": spec.pagination.kind,
        "page_limit": spec.page_limit,
    }
