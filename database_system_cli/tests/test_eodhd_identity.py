from datetime import date

from fdp.sources.eodhd.identity import DatedInstrumentIdentityResolver


def _instrument(
    instrument_id: int,
    symbol: str,
    asset_type: str,
) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "provider_symbol": f"{symbol}.US",
        "asset_type": asset_type,
        "currency": "USD",
        "listed_date": None,
        "delisted_date": None,
    }


def _history(
    instrument_row: dict[str, object],
    id_value: str,
    *,
    valid_from: date | None,
    valid_to: date | None,
) -> dict[str, object]:
    return {
        **instrument_row,
        "id_value": id_value,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


def test_dated_history_wins_over_reused_current_provider_symbol() -> None:
    meta = _instrument(1, "META", "stock")
    reused_fb = _instrument(2, "FB", "etf")
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[meta, reused_fb],
        history_rows=[
            _history(meta, "FB.US", valid_from=None, valid_to=date(2022, 6, 8)),
            _history(meta, "META.US", valid_from=date(2022, 6, 9), valid_to=None),
        ],
        asset_types=["stock", "etf"],
    )

    historical = resolver.resolve(
        provider_symbol="FB.US",
        trade_date=date(2014, 8, 18),
        eodhd_type="Common Stock",
    )
    current_reuse = resolver.resolve(
        provider_symbol="FB.US",
        trade_date=date(2023, 1, 3),
        eodhd_type="ETF",
    )

    assert historical.instrument["instrument_id"] == 1
    assert historical.matched_by == "identifier_history"
    assert historical.confidence == "high"
    assert historical.evidence_type == "dated_provider_symbol_history"
    assert current_reuse.instrument["instrument_id"] == 2
    assert current_reuse.matched_by == "current_provider_symbol"
    assert current_reuse.confidence == "medium"
    assert current_reuse.evidence_type == "unique_current_provider_symbol"


def test_future_history_interval_blocks_current_fallback_for_same_asset_type() -> None:
    meta = _instrument(1, "META", "stock")
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[meta],
        history_rows=[
            _history(meta, "META.US", valid_from=date(2022, 6, 9), valid_to=None),
        ],
        asset_types=["stock"],
    )

    result = resolver.resolve(
        provider_symbol="META.US",
        trade_date=date(2014, 8, 18),
        eodhd_type="Common Stock",
    )

    assert result.instrument is None
    assert result.reason == "identifier_not_valid_on_trade_date"


def test_identity_resolution_rejects_type_mismatch_and_ambiguity() -> None:
    first = _instrument(1, "ONE", "stock")
    second = _instrument(2, "TWO", "stock")
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[first],
        history_rows=[
            _history(first, "OLD.US", valid_from=None, valid_to=None),
            _history(second, "OLD.US", valid_from=None, valid_to=None),
        ],
        asset_types=["stock", "etf"],
    )

    mismatch = resolver.resolve(
        provider_symbol="ONE.US",
        trade_date=date(2020, 1, 2),
        eodhd_type="ETF",
    )
    ambiguous = resolver.resolve(
        provider_symbol="OLD.US",
        trade_date=date(2020, 1, 2),
        eodhd_type="Common Stock",
    )

    assert mismatch.reason == "current_provider_symbol_asset_type_mismatch"
    assert mismatch.candidate_instrument_ids == (1,)
    assert ambiguous.reason == "ambiguous_identifier_history"
    assert ambiguous.candidate_instrument_ids == (1, 2)


def test_identity_resolution_allows_unique_exact_symbol_when_bulk_type_is_missing() -> None:
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[_instrument(1, "AAPL", "stock")],
        history_rows=[],
        asset_types=["stock"],
    )

    result = resolver.resolve(
        provider_symbol="AAPL.US",
        trade_date=date(2024, 1, 2),
        eodhd_type=None,
    )

    assert result.instrument["instrument_id"] == 1
    assert result.matched_by == "current_provider_symbol"
    assert result.confidence == "medium"


def test_identity_resolution_uses_dated_history_when_bulk_type_is_missing() -> None:
    meta = _instrument(1, "META", "stock")
    reused_fb = _instrument(2, "FB", "etf")
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[meta, reused_fb],
        history_rows=[
            _history(meta, "FB.US", valid_from=None, valid_to=date(2022, 6, 8)),
        ],
        asset_types=["stock", "etf"],
    )

    result = resolver.resolve(
        provider_symbol="FB.US",
        trade_date=date(2014, 8, 18),
        eodhd_type=None,
    )

    assert result.instrument["instrument_id"] == 1
    assert result.matched_by == "identifier_history"


def test_missing_bulk_type_does_not_bypass_future_dated_history() -> None:
    meta = _instrument(1, "META", "stock")
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[meta],
        history_rows=[
            _history(meta, "META.US", valid_from=date(2022, 6, 9), valid_to=None),
        ],
        asset_types=["stock"],
    )

    result = resolver.resolve(
        provider_symbol="META.US",
        trade_date=date(2014, 8, 18),
        eodhd_type=None,
    )

    assert result.instrument is None
    assert result.reason == "identifier_not_valid_on_trade_date"


def test_undated_history_is_not_treated_as_point_in_time_evidence() -> None:
    old = _instrument(1, "OLD", "stock")
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[],
        history_rows=[
            _history(old, "OLD.US", valid_from=None, valid_to=None),
        ],
        asset_types=["stock"],
    )

    result = resolver.resolve(
        provider_symbol="OLD.US",
        trade_date=date(2014, 8, 18),
        eodhd_type="Common Stock",
    )

    assert result.instrument is None
    assert result.reason == "undated_identifier_history_not_authoritative"
    assert result.candidate_instrument_ids == (1,)


def test_resolved_identity_builds_aggregate_audit_row() -> None:
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[_instrument(1, "AAPL", "stock")],
        history_rows=[],
        asset_types=["stock"],
    )
    result = resolver.resolve(
        provider_symbol="AAPL.US",
        trade_date=date(2024, 1, 2),
        eodhd_type="Common Stock",
    )

    audit = result.audit_row(
        provider_symbol="aapl.us",
        trade_date=date(2024, 1, 2),
        run_id=71,
        market="us",
    )

    assert audit["instrument_id"] == 1
    assert audit["provider_symbol"] == "AAPL.US"
    assert audit["confidence"] == "medium"
    assert audit["observed_from"] == date(2024, 1, 2)
    assert audit["observed_to"] == date(2024, 1, 2)
    assert audit["first_run_id"] == 71
    assert audit["last_run_id"] == 71


def test_missing_bulk_type_does_not_cross_reused_identifier_owners() -> None:
    old_owner = _instrument(1, "OLD", "stock")
    current_owner = _instrument(2, "OLD", "etf")
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[current_owner],
        history_rows=[
            _history(old_owner, "OLD.US", valid_from=None, valid_to=date(2020, 1, 1)),
        ],
        asset_types=["stock", "etf"],
    )

    result = resolver.resolve(
        provider_symbol="OLD.US",
        trade_date=date(2024, 1, 2),
        eodhd_type=None,
    )

    assert result.instrument is None
    assert result.reason == "identifier_not_valid_on_trade_date"
    assert result.candidate_instrument_ids == (1, 2)


def test_identity_resolution_rejects_present_but_unsupported_type() -> None:
    resolver = DatedInstrumentIdentityResolver(
        current_rows=[_instrument(1, "AAPL", "stock")],
        history_rows=[],
        asset_types=["stock"],
    )

    result = resolver.resolve(
        provider_symbol="AAPL.US",
        trade_date=date(2024, 1, 2),
        eodhd_type="Bond",
    )

    assert result.instrument is None
    assert result.reason == "unsupported_eodhd_type"
