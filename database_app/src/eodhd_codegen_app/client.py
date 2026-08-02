from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from io import StringIO
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from eodhd_codegen_app.codegen import build_urls
from eodhd_codegen_app.request_model import ApiRequest


Transport = Callable[..., Any]
MAX_EXECUTION_HTTP_REQUESTS = 50
MAX_EXPORT_ROWS = 250_000
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
SINGLE_SYMBOL_RESPONSE_ENDPOINTS = {"historical_eod", "intraday", "dividends", "splits", "technical"}


class EodhdExecutionError(RuntimeError):
    """Raised when an upstream EODHD request fails."""


@dataclass(frozen=True)
class ExecutionResult:
    """Normalized result returned to the browser.

    Input: one or more EODHD HTTP responses.
    Output: token-safe full rows plus bounded preview and request metadata.
    Flow: HTTP body -> bounded JSON/CSV parse -> full export rows + preview.
    """

    rows: list[dict[str, Any]]
    preview_rows: list[dict[str, Any]]
    source_row_count: int
    returned_row_count: int
    truncated: bool
    requests_made: int
    status_codes: list[int]

    def as_dict(self, *, export_id: str = "") -> dict[str, Any]:
        return {
            "rows": self.preview_rows,
            "preview_rows": self.preview_rows,
            "source_row_count": self.source_row_count,
            "returned_row_count": self.returned_row_count,
            "export_row_count": len(self.rows),
            "export_id": export_id,
            "truncated": self.truncated,
            "requests_made": self.requests_made,
            "status_codes": self.status_codes,
        }


class EodhdHttpClient:
    """Minimal EODHD HTTP client for the code generator app.

    Input: validated request plus API key from `EODHD_API_KEY`.
    Output: parsed preview/export rows; never returns the actual token or tokenized URL.
    Flow: build real URLs -> urllib GET -> parse JSON/CSV -> cap browser payload.
    """

    def __init__(self, *, timeout_seconds: int = 30, transport: Transport = urlopen) -> None:
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def execute(self, request: ApiRequest, *, api_key: str) -> ExecutionResult:
        if not api_key:
            raise EodhdExecutionError("EODHD_API_KEY is not set")

        rows: list[dict[str, Any]] = []
        source_row_count = 0
        response_bytes = 0
        status_codes: list[int] = []
        urls = build_urls(request, api_token=api_key)
        if len(urls) > MAX_EXECUTION_HTTP_REQUESTS:
            raise EodhdExecutionError(
                f"Execute API is capped at {MAX_EXECUTION_HTTP_REQUESTS} HTTP requests. "
                "Use generated code for larger research lists."
            )

        for index, url in enumerate(urls):
            status_code, body = self._get(url, api_key=api_key, fmt=request.fmt)
            status_codes.append(status_code)
            response_bytes += len(body.encode("utf-8"))
            if response_bytes > MAX_RESPONSE_BYTES:
                raise EodhdExecutionError(
                    f"EODHD execution exceeds the {MAX_RESPONSE_BYTES // (1024 * 1024)} MiB safety cap"
                )
            try:
                parsed_rows = _redact_rows(_parse_body(body, fmt=request.fmt), api_key)
            except EodhdExecutionError as exc:
                raise EodhdExecutionError(_redact(str(exc), api_key)) from exc
            if source_row_count + len(parsed_rows) > MAX_EXPORT_ROWS:
                raise EodhdExecutionError(
                    f"EODHD response exceeds the full-export safety cap of {MAX_EXPORT_ROWS} rows"
                )
            source_row_count += len(parsed_rows)
            rows.extend(_annotate_rows(parsed_rows, request=request, request_index=index))

        preview_rows = rows[: request.preview_limit]
        return ExecutionResult(
            rows=rows,
            preview_rows=preview_rows,
            source_row_count=source_row_count,
            returned_row_count=len(preview_rows),
            truncated=len(rows) > len(preview_rows),
            requests_made=len(urls),
            status_codes=status_codes,
        )

    def _get(self, url: str, *, api_key: str, fmt: str) -> tuple[int, str]:
        accept = "text/csv" if fmt == "csv" else "application/json"
        try:
            request = Request(url, headers={"Accept": accept})
            with self.transport(request, timeout=self.timeout_seconds) as response:
                status_code = _status_code(response)
                body_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            body = _read_error_body(exc)
            raise EodhdExecutionError(_redact(f"HTTP {exc.code}: {body}", api_key)) from exc
        except (URLError, TimeoutError) as exc:
            raise EodhdExecutionError(_redact(str(exc), api_key)) from exc

        if len(body_bytes) > MAX_RESPONSE_BYTES:
            raise EodhdExecutionError(
                f"EODHD response exceeds the {MAX_RESPONSE_BYTES // (1024 * 1024)} MiB safety cap"
            )
        try:
            body = body_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EodhdExecutionError("EODHD response is not valid UTF-8") from exc

        if not 200 <= status_code < 300:
            raise EodhdExecutionError(_redact(f"HTTP {status_code}: {body[:1000]}", api_key))
        return status_code, body


def _parse_body(body: str, *, fmt: str) -> list[dict[str, Any]]:
    if fmt == "csv":
        reader = csv.DictReader(StringIO(body.lstrip("\ufeff\r\n\t ")))
        return [_coerce_row(dict(row)) for row in reader]

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise EodhdExecutionError(f"invalid JSON response: {exc}") from exc

    if isinstance(payload, list):
        return [_coerce_json_row(row) for row in payload]
    if isinstance(payload, dict):
        error_message = payload.get("error") or payload.get("errors")
        if error_message:
            raise EodhdExecutionError(f"EODHD error response: {_coerce_cell(error_message)}")
        data = payload.get("data")
        if isinstance(data, list):
            return [_coerce_json_row(row) for row in data]
        return [_coerce_row(payload)]
    return [{"value": payload}]


def _annotate_rows(
    rows: list[dict[str, Any]],
    *,
    request: ApiRequest,
    request_index: int,
) -> list[dict[str, Any]]:
    if request.endpoint not in SINGLE_SYMBOL_RESPONSE_ENDPOINTS or request_index >= len(request.symbols):
        return rows
    provider_symbol = request.symbols[request_index]
    return [{**row, "_provider_symbol": provider_symbol} for row in rows]


def _status_code(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is not None:
        return int(status)
    return int(response.getcode())


def _read_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8")[:1000]
    except Exception:
        return str(exc)


def _redact(text: str, api_key: str) -> str:
    if not api_key:
        return text
    redacted = text.replace(api_key, "[REDACTED]")
    encoded_api_key = quote_plus(api_key)
    if encoded_api_key != api_key:
        redacted = redacted.replace(encoded_api_key, "[REDACTED]")
    return redacted


def _redact_rows(rows: list[dict[str, Any]], api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        return rows
    return [
        {
            _redact(str(key), api_key): _redact(value, api_key) if isinstance(value, str) else value
            for key, value in row.items()
        }
        for row in rows
    ]


def _coerce_json_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return _coerce_row(row)
    return {"value": row}


def _coerce_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _coerce_cell(value) for key, value in row.items()}


def _coerce_cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, sort_keys=True)
