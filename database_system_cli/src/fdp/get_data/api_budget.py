"""Shared redacted EODHD account-budget parsing for guarded jobs."""

from __future__ import annotations

from fdp.sources.eodhd.client import EodhdApiResponse, EodhdClient


def remote_api_capacity_metrics(
    response: EodhdApiResponse,
    *,
    required_units: int,
) -> dict[str, int | str]:
    """Validate one `/user` response and return only non-sensitive counters."""
    if not response.success or not response.payload:
        raise ValueError(
            "EODHD User API budget preflight failed: "
            f"{response.error_message or response.status_code}"
        )
    payload = response.payload[0]
    try:
        used = int(payload["apiRequests"])
        daily_limit = int(payload["dailyRateLimit"])
        extra_remaining = int(payload.get("extraLimit") or 0)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("EODHD User API returned incomplete budget counters") from exc
    remote_remaining = max(daily_limit - used, 0) + max(extra_remaining, 0)
    if remote_remaining < required_units:
        raise ValueError(
            "EODHD remote API budget is insufficient: "
            f"remaining={remote_remaining} required={required_units}"
        )
    return {
        "remote_api_requests_used": used,
        "remote_daily_rate_limit": daily_limit,
        "remote_extra_units_remaining": extra_remaining,
        "remote_api_units_remaining": remote_remaining,
        "remote_api_requests_date": str(payload.get("apiRequestsDate") or "unknown"),
        "remote_preflight_api_units": response.retry_count + 1,
    }


def check_remote_api_capacity(
    client: EodhdClient,
    *,
    required_units: int,
) -> dict[str, int | str]:
    """Fetch `/user` and validate that the requested hard budget is available."""
    return remote_api_capacity_metrics(client.get_user(), required_units=required_units)
