from __future__ import annotations

from eodhd_codegen_app.cost import estimate_api_cost
from eodhd_codegen_app.request_model import validate_payload


def test_bulk_cost_requires_confirmation() -> None:
    request = validate_payload(
        {
            "endpoint": "bulk_last_day_eod",
            "params": {"exchange": "US", "symbols": "AAPL,MSFT"},
        }
    )

    cost = estimate_api_cost(request)

    assert cost.estimated_api_calls == 102
    assert cost.requires_confirmation is True


def test_normal_historical_cost_is_per_symbol_without_confirmation() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "params": {
                "symbols": "AAPL.US,MSFT.US",
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
            },
        }
    )

    cost = estimate_api_cost(request)

    assert cost.estimated_api_calls == 2
    assert cost.requires_confirmation is False


def test_bulk_date_range_cost_multiplies_by_date_count() -> None:
    request = validate_payload(
        {
            "endpoint": "bulk_last_day_eod",
            "params": {
                "exchange": "US",
                "symbols": "AAPL,MSFT",
                "date_from": "2024-01-02",
                "date_to": "2024-01-04",
            },
        }
    )

    cost = estimate_api_cost(request)

    assert cost.estimated_api_calls == 306
    assert cost.requires_confirmation is True


def test_large_normal_symbol_list_requires_execution_confirmation() -> None:
    request = validate_payload(
        {
            "endpoint": "historical_eod",
            "params": {
                "symbols": ",".join(f"S{i}.US" for i in range(75)),
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
            },
        }
    )

    cost = estimate_api_cost(request)

    assert cost.estimated_api_calls == 75
    assert cost.requires_confirmation is True
