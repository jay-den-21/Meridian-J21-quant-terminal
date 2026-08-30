"""Direct stdlib HTTPS client for the fixed Tushare Pro data endpoint."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from http.client import IncompleteRead, RemoteDisconnected
from time import perf_counter, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fdp_cn.tushare.errors import (
    TushareAuthenticationError,
    TushareError,
    TushareHttpError,
    TushareNoDataError,
    TusharePermissionError,
    TushareProtocolError,
    TushareProviderError,
    TushareRateLimitError,
    TushareRedirectError,
    TushareResponseTooLargeError,
    TushareTransportError,
    safe_error_message,
)
from fdp_cn.tushare.models import (
    JsonScalar,
    TushareApiEvent,
    TushareRequest,
    TushareResponse,
)


TUSHARE_DATA_API_URL = "https://api.tushare.pro/dataapi"
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_RESPONSE_BYTES = 8_000_000
_INVALID_TOKEN_MARKERS = (
    "invalid token",
    "token不存在",
    "token错误",
    "无效token",
    "无效的token",
    "token失效",
    "token不对",
    "token invalid",
    "token is invalid",
    "token无效",
    "token不正确",
    "token为空",
)

Transport = Callable[..., Any]
Sleeper = Callable[[float], None]
ProgressCallback = Callable[[TushareApiEvent], None]


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


_NO_REDIRECT_OPENER = build_opener(_RejectRedirects())


def _open_without_redirects(request: Request, *, timeout: float):
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


class TushareClient:
    """Fetch and validate one Tushare page without SDK or third-party HTTP code."""

    def __init__(
        self,
        *,
        token: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = 1.0,
        timeout_seconds: float = 30.0,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        transport: Transport = _open_without_redirects,
        sleeper: Sleeper = sleep,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must not be empty")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(max_response_bytes, bool) or max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._token = token.strip()
        self.max_retries = max_retries
        self.retry_delay_seconds = float(retry_delay_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)
        self._transport = transport
        self._sleeper = sleeper
        self._progress_callback = progress_callback

    def fetch_page(self, request: TushareRequest) -> TushareResponse:
        """POST one page, using one initial attempt plus at most ``max_retries``."""
        max_attempts = self.max_retries + 1
        body = self._request_body(request)
        http_request = Request(
            TUSHARE_DATA_API_URL,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "j21-tushare-source/1",
            },
        )

        for attempt in range(1, max_attempts + 1):
            started = perf_counter()
            self._emit(
                TushareApiEvent(
                    kind="request",
                    endpoint=request.endpoint_key,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )
            )
            status_code: int | None = None
            try:
                with self._transport(
                    http_request, timeout=self.timeout_seconds
                ) as response:
                    status_code = _response_status(response)
                    if status_code is not None and 300 <= status_code < 400:
                        raise TushareRedirectError(
                            "Tushare redirect responses are forbidden",
                            status_code=status_code,
                        )
                    if status_code is not None and not 200 <= status_code < 300:
                        raise _http_status_error(status_code)
                    final_url = getattr(
                        response, "geturl", lambda: TUSHARE_DATA_API_URL
                    )()
                    if final_url != TUSHARE_DATA_API_URL:
                        raise TushareRedirectError(
                            "Tushare response URL changed from the fixed endpoint",
                            status_code=status_code,
                        )
                    raw_body = response.read(self.max_response_bytes + 1)
                if len(raw_body) > self.max_response_bytes:
                    raise TushareResponseTooLargeError(
                        "Tushare response exceeded the configured byte limit",
                        status_code=status_code,
                    )
                parsed = self._parse_response(
                    request=request,
                    raw_body=raw_body,
                    attempt=attempt,
                    status_code=status_code,
                )
            except HTTPError as error:
                status_code = error.code
                if 300 <= error.code < 400:
                    failure: TushareError = TushareRedirectError(
                        "Tushare redirect responses are forbidden",
                        status_code=error.code,
                    )
                else:
                    failure = _http_status_error(error.code)
            except (
                URLError,
                TimeoutError,
                IncompleteRead,
                RemoteDisconnected,
                ConnectionError,
            ) as error:
                failure = TushareTransportError(
                    safe_error_message(
                        error.reason if isinstance(error, URLError) else error,
                        token=self._token,
                    ),
                    status_code=status_code,
                )
            except OSError as error:
                failure = TushareTransportError(
                    safe_error_message(error, token=self._token),
                    status_code=status_code,
                )
            except TushareError as error:
                failure = error
            else:
                duration_ms = int((perf_counter() - started) * 1000)
                self._emit(
                    TushareApiEvent(
                        kind="success",
                        endpoint=request.endpoint_key,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        status_code=status_code,
                        rows_returned=parsed.rows_returned,
                        duration_ms=duration_ms,
                    )
                )
                return parsed

            failure.endpoint = request.endpoint_key
            failure.attempts = attempt
            if failure.status_code is None:
                failure.status_code = status_code
            duration_ms = int((perf_counter() - started) * 1000)
            can_retry = failure.retryable and attempt < max_attempts
            self._emit(
                TushareApiEvent(
                    kind="retry" if can_retry else "failed",
                    endpoint=request.endpoint_key,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    status_code=failure.status_code,
                    duration_ms=duration_ms,
                    error_kind=failure.kind,
                    error_message=safe_error_message(failure, token=self._token),
                    retry_delay_seconds=self.retry_delay_seconds if can_retry else None,
                )
            )
            if not can_retry:
                raise failure
            self._sleeper(self.retry_delay_seconds)

        raise AssertionError("bounded Tushare attempt loop did not return or raise")

    def _request_body(self, request: TushareRequest) -> bytes:
        params: dict[str, object] = {}
        for name, value in request.params.items():
            if isinstance(value, Decimal):
                params[name] = format(value, "f")
            else:
                params[name] = value
        envelope = {
            "api_name": request.api_name,
            "token": self._token,
            "params": params,
            "fields": ",".join(request.fields),
        }
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    def _parse_response(
        self,
        *,
        request: TushareRequest,
        raw_body: bytes,
        attempt: int,
        status_code: int | None,
    ) -> TushareResponse:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TushareProtocolError(
                "Tushare response was not valid UTF-8 JSON",
                endpoint=request.endpoint_key,
                attempts=attempt,
                status_code=status_code,
            ) from error
        if not isinstance(payload, dict):
            raise _protocol_error(
                request, attempt, status_code, "response must be a JSON object"
            )
        if not {"code", "msg", "data"}.issubset(payload):
            raise _protocol_error(
                request,
                attempt,
                status_code,
                "response must contain code, msg, and data",
            )
        code = payload["code"]
        message = payload["msg"]
        if isinstance(code, bool) or not isinstance(code, int):
            raise _protocol_error(
                request, attempt, status_code, "response code must be an integer"
            )
        if message is not None and not isinstance(message, str):
            raise _protocol_error(
                request, attempt, status_code, "response msg must be text or null"
            )
        safe_message = safe_error_message(message or "", token=self._token)
        if code != 0:
            raise _provider_error(
                code=code,
                message=safe_message,
                endpoint=request.endpoint_key,
                attempts=attempt,
                status_code=status_code,
            )
        data = payload["data"]
        if not isinstance(data, dict) or not {"fields", "items"}.issubset(data):
            raise _protocol_error(
                request,
                attempt,
                status_code,
                "successful response data must contain fields and items",
            )
        fields_value = data["fields"]
        items_value = data["items"]
        if not isinstance(fields_value, list) or not all(
            isinstance(field, str) and field for field in fields_value
        ):
            raise _protocol_error(
                request, attempt, status_code, "data.fields must be text names"
            )
        if len(fields_value) != len(set(fields_value)):
            raise _protocol_error(
                request, attempt, status_code, "data.fields contains duplicates"
            )
        if not isinstance(items_value, list):
            raise _protocol_error(
                request, attempt, status_code, "data.items must be a list"
            )
        items: list[tuple[JsonScalar, ...]] = []
        for row_number, item in enumerate(items_value):
            if not isinstance(item, list) or len(item) != len(fields_value):
                raise _protocol_error(
                    request,
                    attempt,
                    status_code,
                    f"data.items row {row_number} does not match fields",
                )
            if not all(
                value is None or isinstance(value, (str, int, float, bool))
                for value in item
            ):
                raise _protocol_error(
                    request,
                    attempt,
                    status_code,
                    f"data.items row {row_number} contains a non-scalar value",
                )
            items.append(tuple(item))
        return TushareResponse(
            endpoint_key=request.endpoint_key,
            api_name=request.api_name,
            fields=tuple(fields_value),
            items=tuple(items),
            attempts=attempt,
            status_code=status_code,
            provider_message=safe_message,
        )

    def _emit(self, event: TushareApiEvent) -> None:
        if self._progress_callback is not None:
            self._progress_callback(event)


def _response_status(response: object) -> int | None:
    value = getattr(response, "status", None)
    if value is None:
        getcode = getattr(response, "getcode", None)
        value = getcode() if callable(getcode) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _http_status_error(status_code: int) -> TushareError:
    if status_code == 401:
        return TushareAuthenticationError(
            "Tushare HTTP authentication failed",
            provider_code=status_code,
            status_code=status_code,
        )
    if status_code == 403:
        return TusharePermissionError(
            "Tushare HTTP permission denied",
            provider_code=status_code,
            status_code=status_code,
        )
    if status_code == 429:
        return TushareRateLimitError(
            "Tushare HTTP rate limit exceeded",
            provider_code=status_code,
            status_code=status_code,
        )
    error = TushareHttpError(
        f"Tushare HTTP request failed with status {status_code}",
        status_code=status_code,
    )
    error.retryable = status_code in {408, 500, 502, 503, 504}
    return error


def _protocol_error(
    request: TushareRequest,
    attempt: int,
    status_code: int | None,
    message: str,
) -> TushareProtocolError:
    return TushareProtocolError(
        f"Malformed Tushare response: {message}",
        endpoint=request.endpoint_key,
        attempts=attempt,
        status_code=status_code,
    )


def _provider_error(
    *,
    code: int,
    message: str,
    endpoint: str,
    attempts: int,
    status_code: int | None,
) -> TushareProviderError:
    normalized = message.casefold()
    kwargs = {
        "provider_code": code,
        "endpoint": endpoint,
        "attempts": attempts,
        "status_code": status_code,
    }
    if any(marker in normalized for marker in _INVALID_TOKEN_MARKERS):
        return TushareAuthenticationError(
            message or "Tushare token was rejected", **kwargs
        )
    if any(
        marker in normalized
        for marker in ("频率", "频次", "每分钟", "rate limit", "too many")
    ):
        return TushareRateLimitError(message or "Tushare rate limit exceeded", **kwargs)
    if any(marker in normalized for marker in ("权限", "积分", "permission", "无权")):
        return TusharePermissionError(message or "Tushare permission denied", **kwargs)
    if any(marker in normalized for marker in ("无数据", "no data", "not found")):
        return TushareNoDataError(message or "Tushare returned no data", **kwargs)
    return TushareProviderError(message or f"Tushare provider error {code}", **kwargs)
