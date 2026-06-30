from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from eodhd_codegen_app.request_model import ApiRequest

CONFIRMATION_CALL_THRESHOLD = 50


@dataclass(frozen=True)
class ApiCostEstimate:
    estimated_api_calls: int
    requires_confirmation: bool
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "estimated_api_calls": self.estimated_api_calls,
            "requires_confirmation": self.requires_confirmation,
            "message": self.message,
        }


def estimate_api_cost(request: ApiRequest) -> ApiCostEstimate:
    symbol_count = max(len(request.symbols), 1)

    if request.endpoint == "bulk_last_day_eod":
        date_count = _bulk_date_count(request)
        calls_per_date = 100 + len(request.symbols) if request.symbols else 100
        calls = calls_per_date * date_count
        return ApiCostEstimate(
            estimated_api_calls=calls,
            requires_confirmation=True,
            message="Bulk EOD consumes 100 API calls per exchange/date plus one extra call per symbol.",
        )

    if request.endpoint in {"intraday", "technical", "screener", "exchange_details", "symbol_change_history"}:
        calls = 5 * symbol_count if request.endpoint in {"intraday", "technical"} else 5
        return ApiCostEstimate(
            calls,
            calls > CONFIRMATION_CALL_THRESHOLD,
            "This endpoint is documented as a 5-call request.",
        )

    if request.endpoint == "live_ohlcv":
        calls = len(request.symbols)
        return ApiCostEstimate(
            calls,
            calls > CONFIRMATION_CALL_THRESHOLD,
            "Live OHLCV is estimated at one call per ticker.",
        )

    if request.endpoint in {"historical_eod", "dividends", "splits"}:
        calls = len(request.symbols)
        return ApiCostEstimate(
            calls,
            calls > CONFIRMATION_CALL_THRESHOLD,
            "One request is generated per selected symbol.",
        )

    return ApiCostEstimate(1, False, "Estimated as one API call.")


def _bulk_date_count(request: ApiRequest) -> int:
    date_from = request.value("date_from")
    date_to = request.value("date_to")
    if isinstance(date_from, date) and isinstance(date_to, date):
        return (date_to - date_from).days + 1
    return 1
