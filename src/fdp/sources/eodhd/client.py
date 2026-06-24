from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

Transport = Callable[..., Any]


@dataclass(frozen=True)
class EodhdApiResponse:
    """Normalized result from one EODHD API call.

    Input: raw HTTP status/body collected by `EodhdClient`.
    Output: parsed JSON rows plus retry, duration, and error metadata.
    Flow: HTTP response -> JSON list validation -> `EodhdApiResponse`.
    """

    endpoint: str
    status_code: int | None
    success: bool
    retry_count: int
    rows_returned: int
    duration_ms: int
    payload: list[dict[str, Any]]
    error_message: str | None = None


class EodhdClient:
    """Small EODHD HTTP client used by ingestion services.

    Input: API key, endpoint parameters, and an optional test transport.
    Output: `EodhdApiResponse` objects; callers never receive raw HTTP bodies.
    Flow: build URL -> request with retries -> parse JSON list -> response summary.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://eodhd.com/api",
        max_retries: int = 3,
        timeout_seconds: int = 30,
        transport: Transport = urlopen,
    ) -> None:
        """Store EODHD connection settings.

        Input: API key, base URL, retry/timeout settings, and HTTP transport.
        Output: initialized client instance ready for endpoint calls.
        Flow: validate api_key -> normalize base_url -> keep settings.
        """
        if not api_key:
            raise ValueError("api_key must not be empty")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def get_exchange_symbols(self, market: str) -> EodhdApiResponse:
        """Fetch the active EODHD exchange symbol list for one market.

        Input: market code such as "US".
        Output: active symbol rows from `/exchange-symbol-list/{market}`.
        Flow: market -> URL with `delisted=0` -> retrying GET -> parsed rows.
        """
        endpoint = f"/exchange-symbol-list/{market}"
        query = urlencode(
            {
                "api_token": self.api_key,
                "fmt": "json",
                "delisted": "0",
            }
        )
        url = f"{self.base_url}{endpoint}?{query}"

        started = perf_counter()
        retry_count = 0
        last_status_code: int | None = None
        last_error: str | None = None

        for attempt in range(self.max_retries + 1):
            retry_count = attempt
            try:
                request = Request(url, headers={"Accept": "application/json"})
                with self.transport(request, timeout=self.timeout_seconds) as response:
                    status_code = _response_status_code(response)
                    last_status_code = status_code
                    body = response.read().decode("utf-8")

                payload = json.loads(body)
                if not isinstance(payload, list):
                    raise ValueError("EODHD exchange symbol response must be a JSON list")

                rows = [_require_object_row(row) for row in payload]
                return EodhdApiResponse(
                    endpoint=endpoint,
                    status_code=status_code,
                    success=200 <= status_code < 300,
                    retry_count=retry_count,
                    rows_returned=len(rows),
                    duration_ms=_duration_ms(started),
                    payload=rows if 200 <= status_code < 300 else [],
                    error_message=None if 200 <= status_code < 300 else body[:1000],
                )
            except HTTPError as exc:
                last_status_code = exc.code
                last_error = str(exc)
                if exc.code < 500 or attempt >= self.max_retries:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                if attempt >= self.max_retries:
                    break

        return EodhdApiResponse(
            endpoint=endpoint,
            status_code=last_status_code,
            success=False,
            retry_count=retry_count,
            rows_returned=0,
            duration_ms=_duration_ms(started),
            payload=[],
            error_message=last_error,
        )

    def get_symbol_change_history(self, from_date: date | str) -> EodhdApiResponse:
        """Fetch EODHD US ticker rename events from a start date.

        Input: `from_date` as `date` or YYYY-MM-DD string.
        Output: rows with old symbol, new symbol, company name, and effective date.
        Flow: from_date -> `/symbol-change-history` URL -> retrying GET -> parsed rows.
        """
        endpoint = "/symbol-change-history"
        query = urlencode(
            {
                "from": from_date.isoformat() if isinstance(from_date, date) else from_date,
                "api_token": self.api_key,
                "fmt": "json",
            }
        )
        url = f"{self.base_url}{endpoint}?{query}"

        started = perf_counter()
        retry_count = 0
        last_status_code: int | None = None
        last_error: str | None = None

        for attempt in range(self.max_retries + 1):
            retry_count = attempt
            try:
                request = Request(url, headers={"Accept": "application/json"})
                with self.transport(request, timeout=self.timeout_seconds) as response:
                    status_code = _response_status_code(response)
                    last_status_code = status_code
                    body = response.read().decode("utf-8")

                payload = json.loads(body)
                if not isinstance(payload, list):
                    raise ValueError("EODHD symbol change response must be a JSON list")

                rows = [_require_object_row(row) for row in payload]
                return EodhdApiResponse(
                    endpoint=endpoint,
                    status_code=status_code,
                    success=200 <= status_code < 300,
                    retry_count=retry_count,
                    rows_returned=len(rows),
                    duration_ms=_duration_ms(started),
                    payload=rows if 200 <= status_code < 300 else [],
                    error_message=None if 200 <= status_code < 300 else body[:1000],
                )
            except HTTPError as exc:
                last_status_code = exc.code
                last_error = str(exc)
                if exc.code < 500 or attempt >= self.max_retries:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                if attempt >= self.max_retries:
                    break

        return EodhdApiResponse(
            endpoint=endpoint,
            status_code=last_status_code,
            success=False,
            retry_count=retry_count,
            rows_returned=0,
            duration_ms=_duration_ms(started),
            payload=[],
            error_message=last_error,
        )

    def get_historical_eod(
        self,
        provider_symbol: str,
        *,
        date_from: date,
        date_to: date,
    ) -> EodhdApiResponse:
        """Fetch daily historical EOD OHLCV rows for one provider symbol.

        Input: EODHD provider symbol, inclusive start date, and inclusive end date.
        Output: daily rows from `/eod/{provider_symbol}`.
        Flow: provider_symbol + date range -> EOD URL -> retrying GET -> parsed rows.
        """
        endpoint = f"/eod/{provider_symbol}"
        query = urlencode(
            {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "period": "d",
                "api_token": self.api_key,
                "fmt": "json",
            }
        )
        url = f"{self.base_url}{endpoint}?{query}"

        started = perf_counter()
        retry_count = 0
        last_status_code: int | None = None
        last_error: str | None = None

        for attempt in range(self.max_retries + 1):
            retry_count = attempt
            try:
                request = Request(url, headers={"Accept": "application/json"})
                with self.transport(request, timeout=self.timeout_seconds) as response:
                    status_code = _response_status_code(response)
                    last_status_code = status_code
                    body = response.read().decode("utf-8")

                payload = json.loads(body)
                if not isinstance(payload, list):
                    raise ValueError("EODHD historical EOD response must be a JSON list")

                rows = [_require_object_row(row) for row in payload]
                return EodhdApiResponse(
                    endpoint=endpoint,
                    status_code=status_code,
                    success=200 <= status_code < 300,
                    retry_count=retry_count,
                    rows_returned=len(rows),
                    duration_ms=_duration_ms(started),
                    payload=rows if 200 <= status_code < 300 else [],
                    error_message=None if 200 <= status_code < 300 else body[:1000],
                )
            except HTTPError as exc:
                last_status_code = exc.code
                last_error = str(exc)
                if exc.code < 500 or attempt >= self.max_retries:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                if attempt >= self.max_retries:
                    break

        return EodhdApiResponse(
            endpoint=endpoint,
            status_code=last_status_code,
            success=False,
            retry_count=retry_count,
            rows_returned=0,
            duration_ms=_duration_ms(started),
            payload=[],
            error_message=last_error,
        )

    def get_exchange_details(
        self,
        market: str,
        *,
        date_from: date,
        date_to: date,
    ) -> EodhdApiResponse:
        """Fetch legacy exchange details with multi-year holiday filters.

        Input: exchange code and inclusive holiday date range.
        Output: one exchange-details payload from `/exchange-details/{market}`.
        Flow: market + date range -> legacy exchange-details URL -> parsed object row.
        """
        endpoint = f"/exchange-details/{market}"
        query = urlencode(
            {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "api_token": self.api_key,
                "fmt": "json",
            }
        )
        url = f"{self.base_url}{endpoint}?{query}"

        return self._get_json_object(endpoint=endpoint, url=url, object_name="exchange details")

    def _get_json_object(
        self,
        *,
        endpoint: str,
        url: str,
        object_name: str,
    ) -> EodhdApiResponse:
        """Fetch one JSON object endpoint and wrap it as a one-row response."""
        started = perf_counter()
        retry_count = 0
        last_status_code: int | None = None
        last_error: str | None = None

        for attempt in range(self.max_retries + 1):
            retry_count = attempt
            try:
                request = Request(url, headers={"Accept": "application/json"})
                with self.transport(request, timeout=self.timeout_seconds) as response:
                    status_code = _response_status_code(response)
                    last_status_code = status_code
                    body = response.read().decode("utf-8")

                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError(f"EODHD {object_name} response must be a JSON object")

                return EodhdApiResponse(
                    endpoint=endpoint,
                    status_code=status_code,
                    success=200 <= status_code < 300,
                    retry_count=retry_count,
                    rows_returned=1 if 200 <= status_code < 300 else 0,
                    duration_ms=_duration_ms(started),
                    payload=[payload] if 200 <= status_code < 300 else [],
                    error_message=None if 200 <= status_code < 300 else body[:1000],
                )
            except HTTPError as exc:
                last_status_code = exc.code
                last_error = str(exc)
                if exc.code < 500 or attempt >= self.max_retries:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                if attempt >= self.max_retries:
                    break

        return EodhdApiResponse(
            endpoint=endpoint,
            status_code=last_status_code,
            success=False,
            retry_count=retry_count,
            rows_returned=0,
            duration_ms=_duration_ms(started),
            payload=[],
            error_message=last_error,
        )


def _response_status_code(response: Any) -> int:
    """Read a status code from urllib-like response objects."""
    status_code = getattr(response, "status", None)
    if status_code is not None:
        return int(status_code)
    return int(response.getcode())


def _require_object_row(row: Any) -> dict[str, Any]:
    """Validate that one decoded JSON row is an object."""
    if not isinstance(row, dict):
        raise ValueError("EODHD exchange symbol rows must be JSON objects")
    return row


def _duration_ms(started: float) -> int:
    """Return elapsed wall-clock time in milliseconds."""
    return round((perf_counter() - started) * 1000)
