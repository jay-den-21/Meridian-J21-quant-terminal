from datetime import date, timedelta

import pytest

from fdp.research import calculate_daily_indicators


def _rows(count: int, *, constant: bool = False) -> list[dict[str, object]]:
    first_day = date(2024, 1, 1)
    rows = []
    for index in range(count):
        close = 100.0 if constant else 100.0 + index
        rows.append(
            {
                "trade_date": first_day + timedelta(days=index),
                "open": close - 1.0,
                "high": close + 1.0,
                "low": close - 2.0,
                "close": close,
                "adjusted_close": close / 2.0,
                "volume": 1_000 + index,
            }
        )
    return rows


def test_calculate_daily_indicators_adjusts_ohlc_and_preserves_input() -> None:
    rows = _rows(30)

    enriched = calculate_daily_indicators(rows)

    assert rows[0].get("analysis_close") is None
    assert enriched[0]["price_mode"] == "adjusted"
    assert enriched[0]["analysis_open"] == pytest.approx(49.5)
    assert enriched[0]["analysis_close"] == pytest.approx(50.0)
    assert enriched[19]["sma_20"] == pytest.approx(54.75)
    assert enriched[19]["bollinger_mid"] == enriched[19]["sma_20"]
    assert enriched[18]["sma_20"] is None
    assert enriched[29]["rsi_14"] == pytest.approx(100.0)
    assert enriched[19]["volume_sma_20"] == pytest.approx(1009.5)
    assert enriched[19]["volatility_20"] is None
    assert enriched[20]["volatility_20"] is not None


def test_calculate_daily_indicators_supports_raw_mode_and_macd_warmup() -> None:
    enriched = calculate_daily_indicators(_rows(40), adjusted=False)

    assert enriched[0]["price_mode"] == "raw"
    assert enriched[0]["analysis_close"] == pytest.approx(100.0)
    assert enriched[24]["macd"] is None
    assert enriched[25]["macd"] is not None
    assert enriched[32]["macd_signal"] is None
    assert enriched[33]["macd_signal"] is not None
    assert enriched[33]["macd_histogram"] is not None


def test_calculate_daily_indicators_flat_series_has_neutral_rsi_and_bands() -> None:
    enriched = calculate_daily_indicators(_rows(25, constant=True), adjusted=False)

    assert enriched[14]["rsi_14"] == pytest.approx(50.0)
    assert enriched[19]["bollinger_upper"] == pytest.approx(100.0)
    assert enriched[19]["bollinger_lower"] == pytest.approx(100.0)
    assert enriched[20]["volatility_20"] == pytest.approx(0.0)


def test_calculate_daily_indicators_sorts_rows_and_rejects_invalid_values() -> None:
    rows = list(reversed(_rows(3)))

    enriched = calculate_daily_indicators(rows)

    assert enriched[0]["trade_date"] < enriched[-1]["trade_date"]

    invalid = _rows(1)
    invalid[0]["high"] = None
    with pytest.raises(ValueError, match="missing values: high"):
        calculate_daily_indicators(invalid)


def test_calculate_daily_indicators_rejects_zero_adjustment_denominator() -> None:
    row = _rows(1)[0]
    row["close"] = 0.0

    with pytest.raises(ValueError, match="close is zero"):
        calculate_daily_indicators([row])
