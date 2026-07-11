from datetime import date
from decimal import Decimal

from fdp.migrate.daily_price_asset_types import (
    AssetTypeMismatchGroup,
    AssetTypeReconcilePlan,
    _payload_matches,
)


def _price_payload(**overrides):
    payload = {
        "instrument_id": 7,
        "trade_date": date(2024, 1, 2),
        "symbol": "SPY",
        "provider_symbol": "SPY.US",
        "open": Decimal("100.0"),
        "high": Decimal("102.0"),
        "low": Decimal("99.0"),
        "close": Decimal("101.0"),
        "adjusted_close": Decimal("101.0"),
        "volume": 1_000,
        "currency": "USD",
        "source": "EODHD",
        "source_updated_at": None,
    }
    payload.update(overrides)
    return payload


def test_reconcile_plan_totals_mismatch_groups() -> None:
    plan = AssetTypeReconcilePlan(
        (
            AssetTypeMismatchGroup("stock", "etf", 10, 2),
            AssetTypeMismatchGroup("etf", "fund", 5, 1),
        )
    )

    assert plan.total_rows == 15


def test_payload_match_rejects_conflicting_target_price() -> None:
    source = _price_payload()

    assert _payload_matches(source, dict(source)) is True
    assert _payload_matches(source, _price_payload(close=Decimal("101.5"))) is False
