from datetime import date

import pytest

from fdp.sources.eodhd import (
    parse_exchange_symbol,
    parse_exchange_symbol_rows,
    parse_symbol_change_history,
    parse_symbol_change_history_rows,
    split_provider_symbol,
)


def test_split_provider_symbol_keeps_eodhd_symbol_and_market() -> None:
    assert split_provider_symbol("AAPL.US") == ("AAPL", "US")


def test_parse_exchange_symbol_normalizes_active_stock() -> None:
    row = parse_exchange_symbol(
        {
            "Code": "AAPL",
            "Name": "Apple Inc.",
            "Exchange": "NASDAQ",
            "Type": "Common Stock",
            "Currency": "USD",
            "IPODate": "1980-12-12",
        }
    )

    assert row == {
        "market": "US",
        "symbol": "AAPL",
        "provider": "EODHD",
        "provider_symbol": "AAPL.US",
        "name": "Apple Inc.",
        "exchange": "NASDAQ",
        "asset_type": "stock",
        "currency": "USD",
        "is_active": True,
        "listed_date": date(1980, 12, 12),
        "delisted_date": None,
    }


def test_parse_exchange_symbol_filters_unsupported_asset_types() -> None:
    assert parse_exchange_symbol({"Code": "ABC", "Type": "Bond"}) is None


def test_parse_exchange_symbol_rejects_market_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        parse_exchange_symbol(
            {
                "Code": "AAPL.US",
                "Name": "Apple Inc.",
                "Exchange": "NASDAQ",
                "Type": "Common Stock",
                "Currency": "USD",
            },
            market="LSE",
        )


def test_parse_exchange_symbol_rows_rejects_unsupported_malformed_and_inactive_rows() -> None:
    parsed = parse_exchange_symbol_rows(
        [
            {
                "Code": "AAPL",
                "Name": "Apple Inc.",
                "Exchange": "NASDAQ",
                "Type": "Common Stock",
                "Currency": "USD",
            },
            {"Code": "ABC", "Type": "Bond"},
            {"Code": "BAD", "Type": "ETF", "Currency": "USD"},
            {
                "Code": "OLD",
                "Name": "Old Inc.",
                "Exchange": "NYSE",
                "Type": "Common Stock",
                "Currency": "USD",
                "DelistedDate": "2020-01-01",
            },
        ]
    )

    assert [row["symbol"] for row in parsed.accepted] == ["AAPL"]
    assert [row.reason for row in parsed.rejected] == [
        "unsupported_asset_type",
        "missing required EODHD field: Name, name",
        "inactive_instrument",
    ]


def test_parse_exchange_symbol_rows_can_force_and_include_inactive_rows() -> None:
    parsed = parse_exchange_symbol_rows(
        [
            {
                "Code": "OLD",
                "Name": "Old Inc.",
                "Exchange": "NYSE",
                "Type": "Common Stock",
                "Currency": "USD",
                "DelistedDate": "2024-05-20",
            }
        ],
        include_inactive=True,
        force_inactive=True,
    )

    assert len(parsed.accepted) == 1
    assert parsed.accepted[0]["symbol"] == "OLD"
    assert parsed.accepted[0]["is_active"] is False
    assert parsed.accepted[0]["delisted_date"] == date(2024, 5, 20)
    assert parsed.rejected == []


def test_parse_symbol_change_history_maps_old_and_new_provider_symbols() -> None:
    symbol_change = parse_symbol_change_history(
        {
            "exchange": "US",
            "old_symbol": "FB",
            "new_symbol": "META",
            "company_name": "Meta Platforms Inc.",
            "effective": "2022-06-09",
        }
    )

    assert symbol_change.old_symbol == "FB"
    assert symbol_change.new_symbol == "META"
    assert symbol_change.old_provider_symbol == "FB.US"
    assert symbol_change.new_provider_symbol == "META.US"
    assert symbol_change.company_name == "Meta Platforms Inc."
    assert symbol_change.effective == date(2022, 6, 9)


def test_parse_symbol_change_history_rows_rejects_missing_required_fields() -> None:
    parsed = parse_symbol_change_history_rows(
        [
            {"old_symbol": "FB", "new_symbol": "META", "effective": "2022-06-09"},
            {"old_symbol": "TWTR", "new_symbol": "X"},
        ]
    )

    assert [row.new_symbol for row in parsed.accepted] == ["META"]
    assert [row.reason for row in parsed.rejected] == [
        "missing required EODHD date field: effective"
    ]
