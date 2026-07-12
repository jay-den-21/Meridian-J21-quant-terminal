from __future__ import annotations

from eodhd_codegen_app.codegen import build_urls, generate_snippets
from eodhd_codegen_app.request_model import validate_payload


def test_builds_historical_urls_for_multiple_symbols() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "symbols": "AAPL.US MSFT.US",
            "date_from": "2024-01-01",
            "date_to": "2024-01-31",
            "period": "d",
            "order": "a",
        }
    )

    urls = build_urls(request)

    assert len(urls) == 2
    assert urls[0].startswith("https://eodhd.com/api/eod/AAPL.US?")
    assert "api_token=YOUR_EODHD_API_KEY" in urls[0]
    assert "from=2024-01-01" in urls[0]


def test_builds_historical_urls_with_canonical_us_provider_suffix() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "params": {
                "exchange": "US",
                "symbols": "AA.NYSE,AABB.PINK,BRK.B",
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
            },
        }
    )

    urls = build_urls(request)

    assert urls[0].startswith("https://eodhd.com/api/eod/AA.US?")
    assert urls[1].startswith("https://eodhd.com/api/eod/AABB.US?")
    assert urls[2].startswith("https://eodhd.com/api/eod/BRK-B.US?")
    assert "AA.NYSE" not in "\n".join(urls)


def test_generated_code_uses_environment_placeholders_not_real_tokens() -> None:
    request = validate_payload(
        {
            "endpoint": "bulk_last_day_eod",
            "exchange": "US",
            "symbols": "AAPL,MSFT",
        }
    )

    snippets = generate_snippets(request)
    combined = "\n".join(
        [
            "\n".join(snippets["direct_urls"]),
            snippets["python_requests"],
            snippets["python_symbol_loop"],
            snippets["curl"],
            snippets["javascript_fetch"],
            snippets["javascript_symbol_loop"],
            snippets["local_proxy_python"],
        ]
    )

    assert "EODHD_API_KEY" in combined
    assert "YOUR_EODHD_API_KEY" in combined
    assert "test-token" not in combined
    assert "api_token=${EODHD_API_KEY}" in snippets["curl"]


def test_generated_code_includes_direct_urls_and_symbol_loop_modes() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "symbols": "AAPL,MSFT,NVDA",
            "date_from": "2024-01-01",
            "date_to": "2024-01-31",
        }
    )

    snippets = generate_snippets(request, app_base_url="http://127.0.0.1:54321")

    assert len(snippets["direct_urls"]) == 3
    assert "symbols = [" in snippets["python_symbol_loop"]
    assert '"AAPL.US"' in snippets["python_symbol_loop"]
    assert "for symbol in symbols:" in snippets["python_symbol_loop"]
    assert "const symbols = [" in snippets["javascript_symbol_loop"]
    assert "for (const symbol of symbols)" in snippets["javascript_symbol_loop"]
    assert "http://127.0.0.1:54321" in snippets["local_proxy_python"]
    assert "/api/execute" in snippets["local_proxy_python"]
    assert "YOUR_EODHD_API_KEY" not in snippets["local_proxy_python"]


def test_generated_csv_code_does_not_parse_response_as_json() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "symbols": "AAPL.US",
            "date_from": "2024-01-01",
            "date_to": "2024-01-31",
            "fmt": "csv",
        }
    )

    snippets = generate_snippets(request)

    assert "csv.DictReader" in snippets["python_requests"]
    assert "response.json()" not in snippets["python_requests"]
    assert "await response.text()" in snippets["javascript_fetch"]
    assert "await response.json()" not in snippets["javascript_fetch"]


def test_builds_intraday_and_technical_urls() -> None:
    intraday = validate_payload(
        {
            "endpoint": "intraday",
            "fmt": "json",
            "params": {
                "symbols": "AAPL.US",
                "interval": "5m",
                "from_timestamp": 1714555800,
                "to_timestamp": 1714563000,
            },
        }
    )
    intraday_url = build_urls(intraday)[0]

    assert intraday_url.startswith("https://eodhd.com/api/intraday/AAPL.US?")
    assert "interval=5m" in intraday_url
    assert "from=1714555800" in intraday_url

    technical = validate_payload(
        {
            "endpoint": "technical",
            "params": {
                "symbols": "AAPL.US",
                "date_from": "2024-01-01",
                "date_to": "2024-03-01",
                "function": "rsi",
                "indicator_period": 14,
            },
        }
    )
    technical_url = build_urls(technical)[0]

    assert technical_url.startswith("https://eodhd.com/api/technical/AAPL.US?")
    assert "function=rsi" in technical_url
    assert "period=14" in technical_url


def test_builds_screener_and_id_mapping_urls() -> None:
    screener = validate_payload(
        {
            "endpoint": "screener",
            "params": {
                "filters": '[["exchange","=","us"]]',
                "sort": "market_capitalization.desc",
                "limit": 10,
                "offset": 0,
            },
        }
    )
    screener_url = build_urls(screener)[0]

    assert screener_url.startswith("https://eodhd.com/api/screener?")
    assert "filters=[[%22exchange%22,%22=%22,%22us%22]]" in screener_url
    assert "limit=10" in screener_url

    mapping = validate_payload(
        {
            "endpoint": "id_mapping",
            "params": {
                "filter_name": "symbol",
                "filter_value": "AAPL.US",
                "limit": 100,
                "offset": 0,
            },
        }
    )
    mapping_url = build_urls(mapping)[0]

    assert mapping_url.startswith("https://eodhd.com/api/id-mapping?")
    assert "filter[symbol]=AAPL.US" in mapping_url
    assert "page[limit]=100" in mapping_url


def test_curl_screener_snippet_is_shell_copyable() -> None:
    request = validate_payload(
        {
            "endpoint": "screener",
            "params": {
                "filters": '[["exchange","=","us"]]',
                "sort": "market_capitalization.desc",
            },
        }
    )

    curl = generate_snippets(request)["curl"]

    assert 'filters=[["exchange"' not in curl
    assert "filters=[[%22exchange%22,%22=%22,%22us%22]]" in curl
    assert 'api_token=${EODHD_API_KEY}' in curl


def test_bulk_date_range_builds_one_url_per_date() -> None:
    request = validate_payload(
        {
            "endpoint": "bulk_last_day_eod",
            "params": {
                "exchange": "US",
                "symbols": "AAPL,MSFT",
                "date_from": "2024-01-02",
                "date_to": "2024-01-04",
            },
        }
    )

    urls = build_urls(request)

    assert len(urls) == 3
    assert "date=2024-01-02" in urls[0]
    assert "date=2024-01-04" in urls[2]


def test_bulk_loop_snippet_does_not_repeat_bulk_request_per_symbol() -> None:
    request = validate_payload(
        {
            "endpoint": "bulk_last_day_eod",
            "params": {
                "exchange": "US",
                "symbols": "AAPL,MSFT",
                "date_from": "2024-01-02",
                "date_to": "2024-01-04",
            },
        }
    )

    snippets = generate_snippets(request)

    assert "for symbol in symbols:" not in snippets["python_symbol_loop"]
    assert "for trade_date in dates:" in snippets["python_symbol_loop"]
    assert '"AAPL"' in snippets["python_symbol_loop"]
    assert "for (const tradeDate of dates)" in snippets["javascript_symbol_loop"]


def test_live_ohlcv_urls_are_chunked_at_twenty_symbols() -> None:
    request = validate_payload(
        {
            "endpoint": "live_ohlcv",
            "params": {"symbols": ",".join(f"S{i}" for i in range(21))},
        }
    )

    urls = build_urls(request)
    snippets = generate_snippets(request)

    assert len(urls) == 2
    assert "s=S1.US" in urls[0]
    assert urls[1].startswith("https://eodhd.com/api/real-time/S20.US?")
    assert "chunk_size = 20" in snippets["python_symbol_loop"]


def test_instrument_catalog_codegen_uses_selected_format_and_delisted_mode() -> None:
    active_request = validate_payload(
        {
            "asset": "instrument",
            "endpoint": "exchange_symbol_list",
            "fmt": "csv",
            "params": {
                "catalog_asset": "stock",
                "exchange": "NASDAQ",
                "type_filter": "common_stock",
                "delisted": False,
            },
        }
    )
    active_url = build_urls(active_request)[0]

    assert active_url.startswith("https://eodhd.com/api/exchange-symbol-list/NASDAQ?")
    assert "fmt=csv" in active_url
    assert "type=common_stock" in active_url
    assert "delisted=" not in active_url
    assert "csv.DictReader" in generate_snippets(active_request)["python_requests"]

    delisted_request = validate_payload(
        {
            "asset": "instrument",
            "endpoint": "exchange_symbol_list",
            "params": {
                "catalog_asset": "index",
                "exchange": "INDX",
                "type_filter": "all",
                "delisted": True,
            },
        }
    )

    assert "delisted=1" in build_urls(delisted_request)[0]

    snippets = generate_snippets(delisted_request)
    compile(snippets["local_proxy_python"], "<local_proxy_python>", "exec")
    assert '"delisted": false' not in snippets["local_proxy_python"]
    assert "'delisted': True" in snippets["local_proxy_python"]


def test_all_instrument_catalog_categories_generate_code() -> None:
    mappings = (
        ("stock", "NASDAQ", "stock"),
        ("etf", "NYSE", "etf"),
        ("fund", "EUFUND", "all"),
        ("index", "INDX", "all"),
        ("forex", "FOREX", "all"),
        ("crypto", "CC", "all"),
        ("government_bond", "GBOND", "all"),
        ("benchmark", "MONEY", "all"),
    )

    for catalog_asset, exchange, type_filter in mappings:
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
        snippets = generate_snippets(request)

        assert f"/exchange-symbol-list/{exchange}?" in snippets["direct_urls"][0]
        assert "requests.get" in snippets["python_requests"]
        assert "curl --fail" in snippets["curl"]
        assert "await fetch" in snippets["javascript_fetch"]
        compile(snippets["local_proxy_python"], "<local_proxy_python>", "exec")
