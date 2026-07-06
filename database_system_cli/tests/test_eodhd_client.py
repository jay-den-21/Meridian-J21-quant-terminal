import json
from datetime import date
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from fdp.sources.eodhd.client import EodhdClient
from fdp.sources.eodhd.retry import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY_SECONDS,
    EodhdRequestRateLimiter,
)


class FakeResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status

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


def test_eodhd_client_fetches_bulk_eod_prices() -> None:
    requested_urls: list[str] = []

    def fake_transport(request, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)
        return FakeResponse(
            [
                {
                    "code": "AAPL",
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
    response = client.get_bulk_eod(
        "US",
        trade_date=date(2023, 1, 3),
        symbols=["msft", "AAPL", "MSFT"],
    )

    parsed_url = urlparse(requested_urls[0])
    query = parse_qs(parsed_url.query)

    assert parsed_url.path == "/api/eod-bulk-last-day/US"
    assert query["date"] == ["2023-01-03"]
    assert query["symbols"] == ["MSFT,AAPL"]
    assert query["api_token"] == ["test-token"]
    assert query["fmt"] == ["json"]
    assert response.success is True
    assert response.endpoint == "/eod-bulk-last-day/US"
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


def test_eodhd_client_retries_transient_failures_with_progress() -> None:
    events = []
    sleeps = []
    calls = 0

    def fake_transport(request, timeout: int) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError("temporary disconnect")
        return FakeResponse([{"Code": "AAPL", "Type": "Common Stock"}])

    client = EodhdClient(
        api_key="test-token",
        max_retries=1,
        retry_delay_seconds=0,
        transport=fake_transport,
        sleeper=sleeps.append,
        progress_callback=events.append,
    )
    response = client.get_exchange_symbols("US")

    assert response.success is True
    assert response.retry_count == 1
    assert calls == 2
    assert sleeps == [0]
    assert [event.kind for event in events] == ["request", "retry", "request", "success"]
    assert events[1].endpoint == "/exchange-symbol-list/US"
    assert "temporary disconnect" in events[1].error_message


def test_eodhd_client_default_retry_policy_matches_runtime_default() -> None:
    client = EodhdClient(api_key="test-token", transport=lambda request, timeout: None)

    assert client.max_retries == DEFAULT_MAX_RETRIES == 5
    assert client.retry_delay_seconds == DEFAULT_RETRY_DELAY_SECONDS == 61


def test_request_rate_limiter_spaces_request_starts() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = EodhdRequestRateLimiter(
        600,
        sleeper=sleeper,
        clock=lambda: now[0],
    )

    limiter.wait()
    limiter.wait()

    assert sleeps == [0.1]


def test_eodhd_client_waits_on_rate_limiter_before_request() -> None:
    events: list[str] = []

    class FakeLimiter:
        def wait(self) -> None:
            events.append("wait")

    def fake_transport(request, timeout: int) -> FakeResponse:
        events.append("request")
        return FakeResponse([{"Code": "AAPL", "Type": "Common Stock"}])

    client = EodhdClient(
        api_key="test-token",
        transport=fake_transport,
        rate_limiter=FakeLimiter(),
    )

    response = client.get_exchange_symbols("US")

    assert response.success is True
    assert events == ["wait", "request"]
