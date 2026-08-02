from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from eodhd_codegen_app.client import EodhdExecutionError, EodhdHttpClient
from eodhd_codegen_app.request_model import validate_payload


class FakeResponse:
    def __init__(self, body: str, *, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        body = self.body.encode("utf-8")
        return body if size < 0 else body[:size]


def test_client_executes_json_request_without_returning_token() -> None:
    requested_urls: list[str] = []

    def fake_transport(request, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)
        return FakeResponse(
            json.dumps(
                [
                    {
                        "date": "2024-01-02",
                        "open": 100,
                        "high": 101,
                        "low": 99,
                        "close": 100.5,
                        "adjusted_close": 100.5,
                        "volume": 1000,
                    }
                ]
            )
        )

    api_request = validate_payload(
        {
            "endpoint": "historical_eod",
            "symbols": "AAPL.US",
            "date_from": "2024-01-01",
            "date_to": "2024-01-31",
        }
    )
    result = EodhdHttpClient(transport=fake_transport).execute(
        api_request,
        api_key="secret-token",
    )

    parsed_url = urlparse(requested_urls[0])
    query = parse_qs(parsed_url.query)

    assert query["api_token"] == ["secret-token"]
    assert result.rows[0]["_provider_symbol"] == "AAPL.US"
    assert "secret-token" not in json.dumps(result.as_dict())


def test_client_parses_csv_response_for_bulk_request() -> None:
    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse("code,date,close\nAAPL,2024-01-02,185.64\n")

    api_request = validate_payload(
        {
            "endpoint": "bulk_last_day_eod",
            "symbols": "AAPL",
            "fmt": "csv",
        }
    )
    result = EodhdHttpClient(transport=fake_transport).execute(
        api_request,
        api_key="secret-token",
    )

    assert result.rows == [{"code": "AAPL", "date": "2024-01-02", "close": "185.64"}]
    assert result.preview_rows == result.rows


def test_client_parses_csv_response_for_historical_request() -> None:
    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse(
            "date,open,high,low,close,adjusted_close,volume\n"
            "2024-01-02,184.22,185.64,183.50,185.64,185.64,1000\n"
        )

    api_request = validate_payload(
        {
            "endpoint": "historical_eod",
            "symbols": "AAPL.US",
            "date_from": "2024-01-01",
            "date_to": "2024-01-31",
            "fmt": "csv",
        }
    )
    result = EodhdHttpClient(transport=fake_transport).execute(
        api_request,
        api_key="secret-token",
    )

    assert result.rows == [
        {
            "_provider_symbol": "AAPL.US",
            "date": "2024-01-02",
            "open": "184.22",
            "high": "185.64",
            "low": "183.50",
            "close": "185.64",
            "adjusted_close": "185.64",
            "volume": "1000",
        }
    ]
    assert result.preview_rows == result.rows


def test_intraday_rows_include_provider_symbol_for_multi_symbol_preview() -> None:
    requested_urls: list[str] = []

    def fake_transport(request, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)
        return FakeResponse(
            json.dumps(
                [
                    {
                        "_provider_symbol": "UPSTREAM.VALUE",
                        "datetime": "2024-01-02 09:35:00",
                        "open": 100,
                        "close": 101,
                    }
                ]
            )
        )

    api_request = validate_payload(
        {
            "endpoint": "intraday",
            "symbols": "AAPL.US,NVDA.US",
            "interval": "5m",
            "from_timestamp": 1704191400,
            "to_timestamp": 1704192000,
        }
    )
    result = EodhdHttpClient(transport=fake_transport).execute(
        api_request,
        api_key="secret-token",
    )

    assert len(requested_urls) == 2
    assert result.rows[0]["_provider_symbol"] == "AAPL.US"
    assert result.rows[1]["_provider_symbol"] == "NVDA.US"


def test_client_redacts_token_from_http_errors() -> None:
    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse("bad token secret-token", status=403)

    api_request = validate_payload(
        {
            "endpoint": "instrument_search",
            "search_query": "AAPL",
        }
    )

    with pytest.raises(EodhdExecutionError) as exc_info:
        EodhdHttpClient(transport=fake_transport).execute(
            api_request,
            api_key="secret-token",
        )

    assert "secret-token" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_client_preview_extracts_data_lists_and_serializes_nested_values() -> None:
    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse(
            json.dumps(
                {
                    "data": [
                        {
                            "symbol": "AAPL.US",
                            "identifiers": {"isin": "US0378331005"},
                        }
                    ],
                    "links": {"next": None},
                }
            )
        )

    api_request = validate_payload(
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
    result = EodhdHttpClient(transport=fake_transport).execute(
        api_request,
        api_key="secret-token",
    )

    assert result.rows == [
        {
            "symbol": "AAPL.US",
            "identifiers": '{"isin": "US0378331005"}',
        }
    ]


def test_client_treats_empty_data_as_empty_rows() -> None:
    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse(json.dumps({"data": []}))

    api_request = validate_payload(
        {
            "endpoint": "id_mapping",
            "params": {
                "filter_name": "symbol",
                "filter_value": "AAPL.US",
            },
        }
    )
    result = EodhdHttpClient(transport=fake_transport).execute(
        api_request,
        api_key="secret-token",
    )

    assert result.rows == []
    assert result.preview_rows == []


def test_client_rejects_json_error_payloads() -> None:
    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse(json.dumps({"error": "bad token secret-token"}))

    api_request = validate_payload(
        {
            "endpoint": "instrument_search",
            "search_query": "AAPL",
        }
    )

    with pytest.raises(EodhdExecutionError, match="EODHD error response") as exc_info:
        EodhdHttpClient(transport=fake_transport).execute(
            api_request,
            api_key="secret-token",
        )

    assert "secret-token" not in str(exc_info.value)


def test_client_rejects_large_per_symbol_execution_before_http() -> None:
    requested_urls: list[str] = []

    def fake_transport(request, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)
        return FakeResponse("[]")

    api_request = validate_payload(
        {
            "endpoint": "historical_eod",
            "params": {
                "symbols": ",".join(f"S{i}.US" for i in range(51)),
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
            },
        }
    )

    with pytest.raises(EodhdExecutionError, match="capped at 50 HTTP requests"):
        EodhdHttpClient(transport=fake_transport).execute(
            api_request,
            api_key="secret-token",
        )

    assert requested_urls == []


def test_client_keeps_full_rows_but_serializes_preview_only() -> None:
    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse(json.dumps([{"code": f"S{i}"} for i in range(5)]))

    api_request = validate_payload(
        {
            "asset": "instrument",
            "endpoint": "exchange_symbol_list",
            "preview_limit": 2,
            "params": {
                "catalog_asset": "stock",
                "exchange": "NASDAQ",
                "type_filter": "stock",
            },
        }
    )
    result = EodhdHttpClient(transport=fake_transport).execute(api_request, api_key="secret-token")
    public = result.as_dict(export_id="safe-export-id-value-123")

    assert len(result.rows) == 5
    assert result.preview_rows == [{"code": "S0"}, {"code": "S1"}]
    assert public["rows"] == result.preview_rows
    assert public["export_row_count"] == 5
    assert public["truncated"] is True


def test_client_rejects_full_export_row_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    import eodhd_codegen_app.client as client_module

    monkeypatch.setattr(client_module, "MAX_EXPORT_ROWS", 2)

    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse(json.dumps([{"code": "A"}, {"code": "B"}, {"code": "C"}]))

    api_request = validate_payload(
        {
            "asset": "instrument",
            "endpoint": "exchange_symbol_list",
            "params": {
                "catalog_asset": "index",
                "exchange": "INDX",
                "type_filter": "all",
            },
        }
    )

    with pytest.raises(EodhdExecutionError, match="full-export safety cap"):
        EodhdHttpClient(transport=fake_transport).execute(api_request, api_key="secret-token")


def test_client_rejects_oversized_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    import eodhd_codegen_app.client as client_module

    monkeypatch.setattr(client_module, "MAX_RESPONSE_BYTES", 5)

    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse("[]      ")

    api_request = validate_payload({"endpoint": "exchanges_list"})

    with pytest.raises(EodhdExecutionError, match="MiB safety cap"):
        EodhdHttpClient(transport=fake_transport).execute(api_request, api_key="secret-token")


def test_client_rejects_aggregate_response_body_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    import eodhd_codegen_app.client as client_module

    monkeypatch.setattr(client_module, "MAX_RESPONSE_BYTES", 15)

    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse('[{"v":1}]')

    api_request = validate_payload(
        {
            "endpoint": "historical_eod",
            "preview_limit": 2,
            "params": {
                "symbols": "AAPL.US,MSFT.US",
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
            },
        }
    )

    with pytest.raises(EodhdExecutionError, match="execution exceeds"):
        EodhdHttpClient(transport=fake_transport).execute(api_request, api_key="secret-token")


def test_client_redacts_token_echoes_from_success_rows() -> None:
    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse('[{"echo":"secret-token","secret-token":"value"}]')

    result = EodhdHttpClient(transport=fake_transport).execute(
        validate_payload({"endpoint": "exchanges_list"}),
        api_key="secret-token",
    )

    assert "secret-token" not in repr(result.rows)
    assert result.rows == [{"echo": "[REDACTED]", "[REDACTED]": "value"}]


def test_client_redacts_url_encoded_token_echoes() -> None:
    def fake_transport(request, timeout: int) -> FakeResponse:
        return FakeResponse('[{"echo":"secret%2Btoken"}]')

    result = EodhdHttpClient(transport=fake_transport).execute(
        validate_payload({"endpoint": "exchanges_list"}),
        api_key="secret+token",
    )

    assert "secret%2Btoken" not in repr(result.rows)
    assert result.rows == [{"echo": "[REDACTED]"}]
