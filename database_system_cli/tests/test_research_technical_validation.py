import pytest

from fdp.research.technical_validation import (
    _compare_indicator_series,
    required_technical_validation_units,
)


def test_required_technical_validation_units_uses_fixed_weighted_matrix() -> None:
    assert required_technical_validation_units(3) == 45

    with pytest.raises(ValueError, match="positive"):
        required_technical_validation_units(0)


def test_compare_indicator_series_matches_dates_and_reports_max_error() -> None:
    count, max_error = _compare_indicator_series(
        [
            {"trade_date": "2024-01-30", "sma_20": 185.787485},
            {"trade_date": "2024-01-31", "sma_20": 185.72618},
            {"trade_date": "2024-02-01", "sma_20": None},
        ],
        [
            {"date": "2024-01-30", "sma": 185.7875},
            {"date": "2024-01-31", "sma": 185.7262},
            {"date": "2024-02-01", "sma": 185.8552},
        ],
        local_field="sma_20",
        provider_field="sma",
    )

    assert count == 2
    assert max_error == pytest.approx(0.00002)
