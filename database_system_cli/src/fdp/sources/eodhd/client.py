from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from time import perf_counter, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fdp.sources.eodhd.retry import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY_SECONDS,
    EodhdApiEvent,
    EodhdProgressCallback,
    EodhdRequestRateLimiter,
    should_retry,
)

Transport = Callable[..., Any]
Sleeper = Callable[[float], None]


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
    payload: Any
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
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS,
        timeout_seconds: int = 30,
        transport: Transport = urlopen,
        sleeper: Sleeper = sleep,
        rate_limiter: EodhdRequestRateLimiter | None = None,
        progress_callback: EodhdProgressCallback | None = None,
    ) -> None:
        """Store EODHD connection settings.

        Input: API key, base URL, retry/timeout settings, transport, and progress callback.
        Output: initialized client instance ready for endpoint calls.
        Flow: validate api_key -> normalize base_url -> keep settings.
        """
        if not api_key:
            raise ValueError("api_key must not be empty")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.sleeper = sleeper
        self.rate_limiter = rate_limiter
        self.progress_callback = progress_callback

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

        return self._get_json_list(
            endpoint=endpoint,
            url=url,
            object_name="exchange symbol",
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

        return self._get_json_list(
            endpoint=endpoint,
            url=url,
            object_name="symbol change",
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

        return self._get_json_list(
            endpoint=endpoint,
            url=url,
            object_name="historical EOD",
        )

    def get_bulk_eod(
        self,
        exchange: str,
        *,
        trade_date: date | None = None,
        symbols: list[str] | None = None,
        filter_extended: bool = False,
    ) -> EodhdApiResponse:
        """Fetch one-day bulk EOD OHLCV rows for an exchange.

        Input: EODHD exchange code, optional date, optional symbols, and extended flag.
        Output: JSON rows from `/eod-bulk-last-day/{exchange}`.
        Flow: exchange/date/symbols -> bulk EOD URL -> retrying GET -> parsed rows.
        """
        normalized_exchange = exchange.strip().upper()
        endpoint = f"/eod-bulk-last-day/{normalized_exchange}"
        query_params = {
            "api_token": self.api_key,
            "fmt": "json",
        }
        if trade_date is not None:
            query_params["date"] = trade_date.isoformat()
        if symbols:
            normalized_symbols = _normalize_symbol_list(symbols)
            if normalized_symbols:
                query_params["symbols"] = ",".join(normalized_symbols)
        if filter_extended:
            query_params["filter"] = "extended"
        query = urlencode(query_params)
        url = f"{self.base_url}{endpoint}?{query}"

        return self._get_json_list(
            endpoint=endpoint,
            url=url,
            object_name="bulk EOD",
        )

    def _get_json_list(
        self,
        *,
        endpoint: str,
        url: str,
        object_name: str,
    ) -> EodhdApiResponse:
        """Fetch one JSON-list endpoint with the shared retry policy.

        Input: endpoint display name, full URL, and endpoint object label.
        Output: normalized `EodhdApiResponse`.
        Flow: request attempts -> retry wait on transient failure -> parsed list response.
        """
        response = self._request_json(endpoint=endpoint, url=url, object_name=object_name)
        if not response.success:
            return response

        payload = response.payload
        if not isinstance(payload, list):
            return self._failed_response(
                endpoint=endpoint,
                status_code=response.status_code,
                retry_count=response.retry_count,
                started=None,
                error_message=f"EODHD {object_name} response must be a JSON list",
            )

        rows = [_require_object_row(row, object_name=object_name) for row in payload]
        return EodhdApiResponse(
            endpoint=endpoint,
            status_code=response.status_code,
            success=True,
            retry_count=response.retry_count,
            rows_returned=len(rows),
            duration_ms=response.duration_ms,
            payload=rows,
            error_message=None,
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
        response = self._request_json(endpoint=endpoint, url=url, object_name=object_name)
        if not response.success:
            return response

        payload = response.payload
        if not isinstance(payload, dict):
            return self._failed_response(
                endpoint=endpoint,
                status_code=response.status_code,
                retry_count=response.retry_count,
                started=None,
                error_message=f"EODHD {object_name} response must be a JSON object",
            )

        return EodhdApiResponse(
            endpoint=endpoint,
            status_code=response.status_code,
            success=True,
            retry_count=response.retry_count,
            rows_returned=1,
            duration_ms=response.duration_ms,
            payload=[payload],
            error_message=None,
        )

    def _request_json(
        self,
        *,
        endpoint: str,
        url: str,
        object_name: str,
    ) -> EodhdApiResponse:
        """Run one EODHD request with retries and return decoded JSON payload."""
        started = perf_counter()
        retry_count = 0
        last_status_code: int | None = None
        last_error: str | None = None
        max_attempts = self.max_retries + 1

        for attempt in range(max_attempts):
            retry_count = attempt
            if self.rate_limiter is not None:
                self.rate_limiter.wait()
            self._emit_progress(
                EodhdApiEvent(
                    kind="request",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                )
            )
            try:
                request = Request(url, headers={"Accept": "application/json"})
                with self.transport(request, timeout=self.timeout_seconds) as response:
                    status_code = _response_status_code(response)
                    last_status_code = status_code
                    body = response.read().decode("utf-8")

                if not 200 <= status_code < 300:
                    last_error = _http_error_message(status_code=status_code, body=body)
                    if should_retry(
                        status_code=status_code,
                        attempt=attempt,
                        max_retries=self.max_retries,
                    ):
                        self._retry_after(endpoint, attempt, max_attempts, status_code, last_error)
                        continue
                    break

                payload = json.loads(body)
                duration_ms = _duration_ms(started)
                rows_returned = len(payload) if isinstance(payload, list) else 1
                self._emit_progress(
                    EodhdApiEvent(
                        kind="success",
                        endpoint=endpoint,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        status_code=status_code,
                        rows_returned=rows_returned,
                        duration_ms=duration_ms,
                    )
                )

                return EodhdApiResponse(
                    endpoint=endpoint,
                    status_code=status_code,
                    success=True,
                    retry_count=retry_count,
                    rows_returned=rows_returned,
                    duration_ms=duration_ms,
                    payload=payload,
                    error_message=None,
                )
            except HTTPError as exc:
                last_status_code = exc.code
                last_error = _http_error_message(
                    status_code=exc.code,
                    body=_read_http_error_body(exc),
                )
                retry_status_code = last_status_code
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = str(exc)
                retry_status_code = None
            except ValueError as exc:
                last_error = str(exc)
                retry_status_code = last_status_code

            if should_retry(
                status_code=retry_status_code,
                attempt=attempt,
                max_retries=self.max_retries,
            ):
                self._retry_after(endpoint, attempt, max_attempts, retry_status_code, last_error)
                continue
            break

        duration_ms = _duration_ms(started)
        self._emit_progress(
            EodhdApiEvent(
                kind="failed",
                endpoint=endpoint,
                attempt=retry_count + 1,
                max_attempts=max_attempts,
                status_code=last_status_code,
                duration_ms=duration_ms,
                error_message=last_error,
            )
        )
        return self._failed_response(
            endpoint=endpoint,
            status_code=last_status_code,
            retry_count=retry_count,
            started=started,
            error_message=last_error,
        )

    def _retry_after(
        self,
        endpoint: str,
        attempt: int,
        max_attempts: int,
        status_code: int | None,
        error_message: str | None,
    ) -> None:
        """Emit a retry event and wait before the next attempt."""
        self._emit_progress(
            EodhdApiEvent(
                kind="retry",
                endpoint=endpoint,
                attempt=attempt + 2,
                max_attempts=max_attempts,
                status_code=status_code,
                error_message=error_message,
                retry_delay_seconds=self.retry_delay_seconds,
            )
        )
        self.sleeper(self.retry_delay_seconds)

    def _emit_progress(self, event: EodhdApiEvent) -> None:
        """Send an EODHD progress event to the optional reporter."""
        if self.progress_callback is not None:
            self.progress_callback(event)

    def _failed_response(
        self,
        *,
        endpoint: str,
        status_code: int | None,
        retry_count: int,
        started: float | None,
        error_message: str | None,
    ) -> EodhdApiResponse:
        """Build a failed EODHD response."""
        return EodhdApiResponse(
            endpoint=endpoint,
            status_code=status_code,
            success=False,
            retry_count=retry_count,
            rows_returned=0,
            duration_ms=0 if started is None else _duration_ms(started),
            payload=[],
            error_message=error_message,
        )


def _response_status_code(response: Any) -> int:
    """Read a status code from urllib-like response objects."""
    status_code = getattr(response, "status", None)
    if status_code is not None:
        return int(status_code)
    return int(response.getcode())


def _require_object_row(row: Any, *, object_name: str) -> dict[str, Any]:
    """Validate that one decoded JSON row is an object."""
    if not isinstance(row, dict):
        raise ValueError(f"EODHD {object_name} rows must be JSON objects")
    return row


def _normalize_symbol_list(symbols: list[str]) -> list[str]:
    """Normalize endpoint symbol parameters while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        normalized_symbol = symbol.strip().upper()
        if normalized_symbol and normalized_symbol not in seen:
            normalized.append(normalized_symbol)
            seen.add(normalized_symbol)
    return normalized


def _duration_ms(started: float) -> int:
    """Return elapsed wall-clock time in milliseconds."""
    return round((perf_counter() - started) * 1000)


def _read_http_error_body(exc: HTTPError) -> str:
    """Read a short HTTP error body when urllib raises `HTTPError`."""
    try:
        return exc.read().decode("utf-8")[:1000]
    except Exception:
        return str(exc)


def _http_error_message(*, status_code: int, body: str) -> str:
    """Format an HTTP status/body pair for CLI and task logs."""
    return f"HTTP {status_code}: {body[:1000]}"
