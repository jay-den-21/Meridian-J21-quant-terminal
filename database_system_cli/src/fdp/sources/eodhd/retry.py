"""Retry policy and progress events for EODHD API calls."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 30
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

EodhdApiEventKind = Literal["request", "retry", "success", "failed"]
EodhdProgressCallback = Callable[["EodhdApiEvent"], None]


@dataclass(frozen=True)
class EodhdApiEvent:
    """One user-visible EODHD API progress event.

    Input: endpoint, attempt counters, and optional response/error metadata.
    Output: structured event consumed by CLI or tests.
    Flow: request lifecycle -> event -> progress reporter.
    """

    kind: EodhdApiEventKind
    endpoint: str
    attempt: int
    max_attempts: int
    status_code: int | None = None
    rows_returned: int | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    retry_delay_seconds: int | None = None


def is_retryable_status(status_code: int | None) -> bool:
    """Return whether an HTTP status is worth retrying."""
    return status_code in RETRYABLE_STATUS_CODES


def should_retry(*, status_code: int | None, attempt: int, max_retries: int) -> bool:
    """Return whether the current failed attempt should be retried."""
    return attempt < max_retries and (status_code is None or is_retryable_status(status_code))
