"""Canonical asset-type contracts shared across FDP layers."""

from typing import Final, Literal

AssetType = Literal["stock", "etf", "fund", "index", "forex", "crypto"]

CANONICAL_ASSET_TYPES: Final[tuple[AssetType, ...]] = (
    "stock",
    "etf",
    "fund",
    "index",
    "forex",
    "crypto",
)
DAILY_PRICE_TABLE_NAMES: Final[dict[AssetType, str]] = {
    asset_type: f"{asset_type}_daily_price" for asset_type in CANONICAL_ASSET_TYPES
}
US_BULK_EOD_ASSET_TYPES: Final[tuple[AssetType, ...]] = ("stock", "etf", "fund")
HISTORICAL_EOD_ASSET_TYPES: Final[tuple[AssetType, ...]] = (
    "stock",
    "etf",
    "fund",
    "index",
)


def require_canonical_asset_type(value: str) -> AssetType:
    """Normalize and validate one canonical asset type.

    Input: user or internal asset-type text.
    Output: lower-case canonical asset type.
    Flow: text -> normalize -> membership validation -> canonical value.
    """
    normalized = value.strip().lower()
    if normalized not in CANONICAL_ASSET_TYPES:
        expected = ", ".join(CANONICAL_ASSET_TYPES)
        raise ValueError(f"unsupported asset type {value!r}; expected one of {expected}")
    return normalized  # type: ignore[return-value]
