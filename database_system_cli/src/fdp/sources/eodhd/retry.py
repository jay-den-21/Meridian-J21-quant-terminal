"""Retry policy and progress events for EODHD API calls."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Literal

DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_DELAY_SECONDS = 61
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


class EodhdRequestRateLimiter:
    """Thread-safe fixed-interval limiter for EODHD HTTP requests.

    Input: allowed requests per minute plus injectable clock/sleeper for tests.
    Output: `wait()` blocks enough to keep request starts under the configured rate.
    Flow: request start -> lock -> sleep until interval boundary -> update timestamp.
    """

    def __init__(
        self,
        max_requests_per_minute: int,
        *,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_requests_per_minute <= 0:
            raise ValueError("max_requests_per_minute must be positive")
        self._min_interval_seconds = 60.0 / max_requests_per_minute
        self._sleeper = sleeper
        self._clock = clock or monotonic
        self._lock = Lock()
        self._next_allowed_at: float | None = None

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._next_allowed_at is not None and now < self._next_allowed_at:
                sleep_seconds = self._next_allowed_at - now
                if self._sleeper is not None:
                    self._sleeper(sleep_seconds)
                else:
                    from time import sleep

                    sleep(sleep_seconds)
                now = self._clock()
            self._next_allowed_at = now + self._min_interval_seconds
