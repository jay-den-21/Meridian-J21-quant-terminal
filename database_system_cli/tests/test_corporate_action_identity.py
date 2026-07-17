from datetime import date

from fdp.sources.eodhd.corporate_action_identity import CorporateActionIdentityResolver


def _instrument(instrument_id: int, symbol: str, asset_type: str = "stock"):
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "provider_symbol": f"{symbol}.US",
        "asset_type": asset_type,
        "currency": "USD",
        "listed_date": None,
        "delisted_date": None,
    }


def test_corporate_action_identity_uses_old_owner_then_current_owner() -> None:
    current = _instrument(1, "BAM")
    old = {**_instrument(2, "BN"), "id_value": "BAM.US"}
    resolver = CorporateActionIdentityResolver(
        current_rows=[current, _instrument(2, "BN")],
        history_rows=[{**old, "valid_from": None, "valid_to": date(2022, 12, 11)}],
    )

    historical = resolver.resolve(
        provider_symbol="BAM.US",
        action_date=date(2020, 4, 2),
    )
    current_result = resolver.resolve(
        provider_symbol="BAM.US",
        action_date=date(2023, 4, 2),
    )

    assert historical.instrument["instrument_id"] == 2
    assert historical.matched_by == "dated_provider_symbol_history"
    assert current_result.instrument["instrument_id"] == 1
    assert current_result.matched_by == "current_after_historical_owner"


def test_corporate_action_identity_refuses_ambiguous_current_owner() -> None:
    resolver = CorporateActionIdentityResolver(
        current_rows=[_instrument(1, "NEW"), _instrument(2, "NEW")],
        history_rows=[
            {
                **_instrument(3, "OLD"),
                "id_value": "NEW.US",
                "valid_from": date(2025, 1, 1),
                "valid_to": None,
            }
        ],
    )

    gap = resolver.resolve(
        provider_symbol="NEW.US",
        action_date=date(2024, 1, 1),
    )

    assert gap.instrument is None
    assert gap.reason == "ambiguous_current_provider_symbol_owner"
    assert gap.candidate_instrument_ids == (1, 2)


def test_corporate_action_identity_uses_unique_current_owner_across_history_gap() -> None:
    current = _instrument(1, "NEW")
    old = {
        **_instrument(2, "OLD"),
        "id_value": "NEW.US",
        "valid_from": date(2020, 1, 1),
        "valid_to": date(2021, 1, 1),
    }
    resolver = CorporateActionIdentityResolver(
        current_rows=[current, _instrument(2, "OLD")],
        history_rows=[old],
    )

    result = resolver.resolve(
        provider_symbol="NEW.US",
        action_date=date(2018, 1, 1),
    )

    assert result.instrument["instrument_id"] == 1
    assert result.matched_by == "current_provider_symbol_fallback"
