"""Shared formatting for EODHD request lifecycle events."""

from fdp.sources.eodhd.retry import EodhdApiEvent


def format_eodhd_event(event: EodhdApiEvent) -> str:
    """Format one request event without exposing API keys or request URLs."""
    budget = ""
    if event.api_units_consumed is not None:
        budget = (
            f" api_units={event.api_units_consumed}/{event.api_units_limit}"
            f" remaining={event.api_units_remaining}"
        )
    if event.kind == "request":
        return (
            f"EODHD request endpoint={event.endpoint} attempt={event.attempt}/{event.max_attempts}"
            f"{budget}"
        )
    if event.kind == "retry":
        return (
            "EODHD retrying "
            f"endpoint={event.endpoint} attempt={event.attempt}/{event.max_attempts} "
            f"status={event.status_code} error={event.error_message}. "
            f"请稍等1分钟，马上重试～ (≧∇≦) wait={event.retry_delay_seconds}s{budget}"
        )
    if event.kind == "success":
        return (
            "EODHD success "
            f"endpoint={event.endpoint} status={event.status_code} "
            f"rows={event.rows_returned} duration_ms={event.duration_ms}{budget}"
        )
    return (
        "EODHD failed "
        f"endpoint={event.endpoint} status={event.status_code} "
        f"error={event.error_message}{budget}"
    )
