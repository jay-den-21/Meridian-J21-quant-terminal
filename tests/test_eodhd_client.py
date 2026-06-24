import json
from datetime import date
from urllib.parse import parse_qs, urlparse

from fdp.sources.eodhd.client import EodhdClient


class FakeResponse:
    status = 200

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_eodhd_client_fetches_active_exchange_symbols() -> None:
    requested_urls: list[str] = []

    def fake_transport(request, timeout: int) -> FakeResponse:
        assert timeout == 30
        requested_urls.append(request.full_url)
        return FakeResponse([{"Code": "AAPL", "Type": "Common Stock"}])

    client = EodhdClient(api_key="test-token", transport=fake_transport)
    response = client.get_exchange_symbols("US")

    parsed_url = urlparse(requested_urls[0])
    query = parse_qs(parsed_url.query)

    assert parsed_url.path == "/api/exchange-symbol-list/US"
    assert query["api_token"] == ["test-token"]
    assert query["fmt"] == ["json"]
    assert query["delisted"] == ["0"]
    assert response.success is True
    assert response.endpoint == "/exchange-symbol-list/US"
    assert response.rows_returned == 1
    assert response.payload == [{"Code": "AAPL", "Type": "Common Stock"}]


def test_eodhd_client_fetches_symbol_change_history() -> None:
    requested_urls: list[str] = []

    def fake_transport(request, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)
        return FakeResponse(
            [
                {
                    "exchange": "US",
                    "old_symbol": "FB",
                    "new_symbol": "META",
                    "company_name": "Meta Platforms Inc.",
                    "effective": "2022-06-09",
                }
            ]
        )

    client = EodhdClient(api_key="test-token", transport=fake_transport)
    response = client.get_symbol_change_history(date(2022, 7, 22))

    parsed_url = urlparse(requested_urls[0])
    query = parse_qs(parsed_url.query)

    assert parsed_url.path == "/api/symbol-change-history"
    assert query["from"] == ["2022-07-22"]
    assert query["api_token"] == ["test-token"]
    assert query["fmt"] == ["json"]
    assert response.success is True
    assert response.endpoint == "/symbol-change-history"
    assert response.rows_returned == 1


def test_eodhd_client_fetches_historical_eod_prices() -> None:
    requested_urls: list[str] = []

    def fake_transport(request, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)
        return FakeResponse(
            [
                {
                    "date": "2023-01-03",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "adjusted_close": 100.5,
                    "volume": 1000,
                }
            ]
        )

    client = EodhdClient(api_key="test-token", transport=fake_transport)
    response = client.get_historical_eod(
        "AAPL.US",
        date_from=date(2023, 1, 1),
        date_to=date(2024, 1, 1),
    )

    parsed_url = urlparse(requested_urls[0])
    query = parse_qs(parsed_url.query)

    assert parsed_url.path == "/api/eod/AAPL.US"
    assert query["from"] == ["2023-01-01"]
    assert query["to"] == ["2024-01-01"]
    assert query["period"] == ["d"]
    assert query["api_token"] == ["test-token"]
    assert query["fmt"] == ["json"]
    assert response.success is True
    assert response.endpoint == "/eod/AAPL.US"
    assert response.rows_returned == 1


def test_eodhd_client_fetches_legacy_exchange_details() -> None:
    requested_urls: list[str] = []

    def fake_transport(request, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)
        return FakeResponse(
            {
                "Code": "US",
                "TradingHours": {"WorkingDays": "Mon,Tue,Wed,Thu,Fri"},
                "ExchangeHolidays": {},
            }
        )

    client = EodhdClient(api_key="test-token", transport=fake_transport)
    response = client.get_exchange_details(
        "US",
        date_from=date(2023, 1, 1),
        date_to=date(2025, 12, 31),
    )

    parsed_url = urlparse(requested_urls[0])
    query = parse_qs(parsed_url.query)

    assert parsed_url.path == "/api/exchange-details/US"
    assert query["from"] == ["2023-01-01"]
    assert query["to"] == ["2025-12-31"]
    assert query["api_token"] == ["test-token"]
    assert query["fmt"] == ["json"]
    assert response.success is True
    assert response.endpoint == "/exchange-details/US"
    assert response.rows_returned == 1
    assert response.payload[0]["Code"] == "US"
