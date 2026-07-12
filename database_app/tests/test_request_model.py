from __future__ import annotations

import pytest

from eodhd_codegen_app.request_model import ValidationError, validate_payload


def test_historical_request_normalizes_us_symbols() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "symbols": "aapl, MSFT.US, aapl",
            "date_from": "2024-01-01",
            "date_to": "2024-01-31",
        }
    )

    assert request.symbols == ("AAPL.US", "MSFT.US")
    assert request.exchange == "US"
    assert request.period == "d"
    assert request.fmt == "json"


def test_historical_request_rejects_too_many_symbols() -> None:
    with pytest.raises(ValidationError, match="at most 2000 symbols"):
        validate_payload(
            {
                "endpoint": "intraday",
                "symbols": ",".join(f"S{i}.US" for i in range(2001)),
            }
        )

    with pytest.raises(ValidationError, match="at most 2000 symbols"):
        validate_payload(
            {
                "endpoint": "historical_eod",
                "symbols": ",".join(f"S{i}.US" for i in range(2001)),
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
            }
        )


def test_historical_request_accepts_twenty_symbol_clipboard_list() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "symbols": "AAPL, NVDA, MSFT, GOOGL, AMZN, META, TSLA, NFLX, AMD, BRK.B, JPM, WMT, LLY, UNH, V, MA, COST, PFE, XOM, DIS",
            "date_from": "2024-01-01",
            "date_to": "2024-01-31",
        }
    )

    assert len(request.symbols) == 20
    assert request.symbols[:3] == ("AAPL.US", "NVDA.US", "MSFT.US")
    assert "BRK-B.US" in request.symbols


def test_historical_request_normalizes_us_listing_venue_suffixes() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "params": {
                "exchange": "US",
                "symbols": "AA.NYSE,AABB.PINK,AABVF.PINK,AACAF.PINK,AACAY.PINK,BRK.B",
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
            },
        }
    )

    assert request.symbols == (
        "AA.US",
        "AABB.US",
        "AABVF.US",
        "AACAF.US",
        "AACAY.US",
        "BRK-B.US",
    )


def test_bulk_request_accepts_twenty_symbol_clipboard_list() -> None:
    request = validate_payload(
        {
            "endpoint": "bulk_last_day_eod",
            "exchange": "US",
            "symbols": "AAPL, NVDA, MSFT, GOOGL, AMZN, META, TSLA, NFLX, AMD, BRK.B, JPM, WMT, LLY, UNH, V, MA, COST, PFE, XOM, DIS",
        }
    )

    assert len(request.symbols) == 20
    assert request.symbols[:3] == ("AAPL", "NVDA", "MSFT")
    assert "BRK-B" in request.symbols


def test_bulk_request_normalizes_us_listing_venue_suffixes() -> None:
    request = validate_payload(
        {
            "endpoint": "bulk_last_day_eod",
            "params": {
                "exchange": "US",
                "symbols": "AA.NYSE,AABB.PINK,BRK.B",
            },
        }
    )

    assert request.symbols == ("AA", "AABB", "BRK-B")


def test_historical_request_accepts_two_thousand_symbols() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "symbols": ",".join(f"S{i}" for i in range(2000)),
            "date_from": "2024-01-01",
            "date_to": "2024-01-31",
        }
    )

    assert len(request.symbols) == 2000
    assert request.symbols[0] == "S0.US"
    assert request.symbols[-1] == "S1999.US"


def test_live_ohlcv_accepts_two_thousand_symbols_for_codegen() -> None:
    request = validate_payload(
        {
            "endpoint": "live_ohlcv",
            "params": {"symbols": ",".join(f"S{i}" for i in range(2000))},
        }
    )

    assert len(request.symbols) == 2000


def test_bulk_request_requires_symbols_or_explicit_full_exchange() -> None:
    with pytest.raises(ValidationError, match="requires symbols"):
        validate_payload({"endpoint": "bulk_last_day_eod", "exchange": "US"})

    request = validate_payload(
        {
            "endpoint": "bulk_last_day_eod",
            "exchange": "US",
            "symbols": "AAPL.US,MSFT",
        }
    )
    assert request.symbols == ("AAPL", "MSFT")


def test_search_rejects_csv_format() -> None:
    with pytest.raises(ValidationError, match="only supports fmt=json"):
        validate_payload(
            {
                "endpoint": "instrument_search",
                "search_query": "AAPL",
                "fmt": "csv",
            }
        )


def test_historical_request_rejects_reversed_and_oversized_date_ranges() -> None:
    with pytest.raises(ValidationError, match="date_from must be earlier"):
        validate_payload(
            {
                "endpoint": "historical_eod",
                "symbols": "AAPL.US",
                "date_from": "2024-02-01",
                "date_to": "2024-01-01",
            }
        )

    with pytest.raises(ValidationError, match="date range is capped"):
        validate_payload(
            {
                "endpoint": "historical_eod",
                "symbols": "AAPL.US",
                "date_from": "2010-01-01",
                "date_to": "2024-01-01",
            }
        )


def test_required_params_are_not_silently_filled_from_ui_defaults() -> None:
    with pytest.raises(ValidationError, match="symbols is required"):
        validate_payload({"endpoint": "historical_eod"})

    with pytest.raises(ValidationError, match="filter_value is required"):
        validate_payload(
            {
                "endpoint": "id_mapping",
                "params": {"filter_name": "symbol"},
            }
        )


def test_intraday_rejects_oversized_interval_range() -> None:
    with pytest.raises(ValidationError, match="intraday 1m range is capped"):
        validate_payload(
            {
                "endpoint": "intraday",
                "params": {
                    "symbols": "AAPL.US",
                    "interval": "1m",
                    "from_timestamp": 1704067200,
                    "to_timestamp": 1719792000,
                },
            }
        )


def test_screener_requires_filters_to_be_json_array() -> None:
    with pytest.raises(ValidationError, match="filters must be valid JSON"):
        validate_payload(
            {
                "endpoint": "screener",
                "params": {"filters": "not-json"},
            }
        )

    with pytest.raises(ValidationError, match="filters must be a JSON array"):
        validate_payload(
            {
                "endpoint": "screener",
                "params": {"filters": '{"exchange":"us"}'},
            }
        )


def test_screener_accepts_pretty_json_filters() -> None:
    request = validate_payload(
        {
            "endpoint": "screener",
            "params": {
                "filters": '[\n  ["exchange", "=", "us"]\n]',
            },
        }
    )

    assert request.value("filters").startswith("[\n")


def test_bulk_date_range_boundaries() -> None:
    with pytest.raises(ValidationError, match="either trade_date or date_from/date_to"):
        validate_payload(
            {
                "endpoint": "bulk_last_day_eod",
                "params": {
                    "exchange": "US",
                    "symbols": "AAPL",
                    "trade_date": "2024-01-05",
                    "date_from": "2024-01-01",
                    "date_to": "2024-01-05",
                },
            }
        )

    with pytest.raises(ValidationError, match="date range is capped"):
        validate_payload(
            {
                "endpoint": "bulk_last_day_eod",
                "params": {
                    "exchange": "US",
                    "symbols": "AAPL",
                    "date_from": "2024-01-01",
                    "date_to": "2024-03-01",
                },
            }
        )


@pytest.mark.parametrize(
    ("catalog_asset", "exchange", "type_filter"),
    [
        ("stock", "NASDAQ", "common_stock"),
        ("etf", "NYSE", "etf"),
        ("fund", "LSE", "fund"),
        ("fund", "EUFUND", "all"),
        ("index", "INDX", "all"),
        ("forex", "FOREX", "all"),
        ("crypto", "CC", "all"),
        ("government_bond", "GBOND", "all"),
        ("benchmark", "MONEY", "all"),
    ],
)
def test_instrument_catalog_accepts_official_asset_mappings(
    catalog_asset: str,
    exchange: str,
    type_filter: str,
) -> None:
    request = validate_payload(
        {
            "asset": "instrument",
            "endpoint": "exchange_symbol_list",
            "params": {
                "catalog_asset": catalog_asset,
                "exchange": exchange,
                "type_filter": type_filter,
                "delisted": False,
            },
        }
    )

    assert request.asset == "instrument"
    assert request.value("catalog_asset") == catalog_asset
    assert request.exchange == exchange


def test_instrument_catalog_rejects_inconsistent_mappings() -> None:
    with pytest.raises(ValidationError, match="index requires exchange=INDX"):
        validate_payload(
            {
                "asset": "instrument",
                "endpoint": "exchange_symbol_list",
                "params": {
                    "catalog_asset": "index",
                    "exchange": "NASDAQ",
                    "type_filter": "all",
                },
            }
        )

    with pytest.raises(ValidationError, match="etf requires type_filter=etf"):
        validate_payload(
            {
                "asset": "instrument",
                "endpoint": "exchange_symbol_list",
                "params": {
                    "catalog_asset": "etf",
                    "exchange": "NASDAQ",
                    "type_filter": "all",
                },
            }
        )

    with pytest.raises(ValidationError, match="stock type_filter"):
        validate_payload(
            {
                "asset": "instrument",
                "endpoint": "exchange_symbol_list",
                "params": {
                    "catalog_asset": "stock",
                    "exchange": "NASDAQ",
                    "type_filter": "all",
                },
            }
        )

    with pytest.raises(ValidationError, match="requires asset=instrument"):
        validate_payload(
            {
                "asset": "equity",
                "endpoint": "exchange_symbol_list",
                "params": {
                    "catalog_asset": "stock",
                    "exchange": "NASDAQ",
                    "type_filter": "stock",
                },
            }
        )
