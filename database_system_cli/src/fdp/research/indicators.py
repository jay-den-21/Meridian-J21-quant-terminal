"""Deterministic technical indicators calculated from local daily prices."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import log, sqrt
from statistics import fmean, pstdev, stdev
from typing import Any


def calculate_daily_indicators(
    rows: Sequence[Mapping[str, Any]],
    *,
    adjusted: bool = True,
) -> list[dict[str, Any]]:
    """Return chronologically sorted daily rows enriched with local indicators.

    Input: daily OHLCV mappings containing `trade_date`, raw OHLC, adjusted close, and volume.
    Output: copied rows with analysis OHLC plus SMA/EMA/Bollinger/RSI/MACD/volume/volatility.
    Flow: sort rows -> normalize adjusted prices -> calculate aligned series -> enrich copies.
    """
    normalized = [_normalize_price_row(row, adjusted=adjusted) for row in rows]
    normalized.sort(key=lambda row: row["trade_date"])
    if not normalized:
        return []

    closes = [row["analysis_close"] for row in normalized]
    volumes = [row["volume"] for row in normalized]
    sma_20 = _rolling_mean(closes, 20)
    sma_50 = _rolling_mean(closes, 50)
    sma_200 = _rolling_mean(closes, 200)
    ema_20 = _ema(closes, 20)
    bollinger_std = _rolling_population_stddev(closes, 20)
    rsi_14 = _rsi_wilder(closes, 14)
    ema_12 = _ema(closes, 12)
    ema_26 = _ema(closes, 26)
    macd = [
        fast - slow if fast is not None and slow is not None else None
        for fast, slow in zip(ema_12, ema_26, strict=True)
    ]
    macd_signal = _ema_optional(macd, 9)
    macd_histogram = [
        value - signal if value is not None and signal is not None else None
        for value, signal in zip(macd, macd_signal, strict=True)
    ]
    volume_sma_20 = _rolling_mean(volumes, 20)
    volatility_20 = _annualized_log_return_volatility(closes, 20)

    result: list[dict[str, Any]] = []
    for index, row in enumerate(normalized):
        enriched = dict(row)
        enriched.update(
            {
                "sma_20": sma_20[index],
                "sma_50": sma_50[index],
                "sma_200": sma_200[index],
                "ema_20": ema_20[index],
                "bollinger_mid": sma_20[index],
                "bollinger_upper": _bollinger_band(
                    sma_20[index], bollinger_std[index], multiplier=2.0
                ),
                "bollinger_lower": _bollinger_band(
                    sma_20[index], bollinger_std[index], multiplier=-2.0
                ),
                "rsi_14": rsi_14[index],
                "macd": macd[index],
                "macd_signal": macd_signal[index],
                "macd_histogram": macd_histogram[index],
                "volume_sma_20": volume_sma_20[index],
                "volatility_20": volatility_20[index],
            }
        )
        result.append(enriched)
    return result


def _normalize_price_row(
    row: Mapping[str, Any],
    *,
    adjusted: bool,
) -> dict[str, Any]:
    required = ("trade_date", "open", "high", "low", "close", "volume")
    missing = [field for field in required if row.get(field) is None]
    if missing:
        raise ValueError(f"daily indicator row is missing values: {', '.join(missing)}")

    raw_close = float(row["close"])
    adjusted_close_value = row.get("adjusted_close")
    factor = 1.0
    if adjusted and adjusted_close_value is not None:
        if raw_close == 0:
            raise ValueError("cannot adjust a daily row whose close is zero")
        factor = float(adjusted_close_value) / raw_close

    normalized = dict(row)
    normalized.update(
        {
            "analysis_open": float(row["open"]) * factor,
            "analysis_high": float(row["high"]) * factor,
            "analysis_low": float(row["low"]) * factor,
            "analysis_close": raw_close * factor,
            "volume": float(row["volume"]),
            "price_mode": "adjusted" if adjusted else "raw",
        }
    )
    return normalized


def _rolling_mean(values: Sequence[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    rolling_sum = 0.0
    for index, value in enumerate(values):
        rolling_sum += value
        if index >= period:
            rolling_sum -= values[index - period]
        if index >= period - 1:
            result[index] = rolling_sum / period
    return result


def _rolling_population_stddev(
    values: Sequence[float],
    period: int,
) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        result[index] = pstdev(values[index - period + 1 : index + 1])
    return result


def _ema(values: Sequence[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result

    alpha = 2.0 / (period + 1.0)
    result[period - 1] = fmean(values[:period])
    for index in range(period, len(values)):
        previous = result[index - 1]
        assert previous is not None
        result[index] = alpha * values[index] + (1.0 - alpha) * previous
    return result


def _ema_optional(values: Sequence[float | None], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    available = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(available) < period:
        return result

    seed_index = available[period - 1][0]
    result[seed_index] = fmean(float(value) for _, value in available[:period])
    alpha = 2.0 / (period + 1.0)
    previous = result[seed_index]
    assert previous is not None
    for index, value in available[period:]:
        previous = alpha * float(value) + (1.0 - alpha) * previous
        result[index] = previous
    return result


def _rsi_wilder(values: Sequence[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result

    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = fmean(gains[:period])
    average_loss = fmean(losses[:period])
    result[period] = _rsi_value(average_gain, average_loss)

    for change_index in range(period, len(changes)):
        average_gain = ((period - 1) * average_gain + gains[change_index]) / period
        average_loss = ((period - 1) * average_loss + losses[change_index]) / period
        result[change_index + 1] = _rsi_value(average_gain, average_loss)
    return result


def _rsi_value(average_gain: float, average_loss: float) -> float:
    if average_gain == 0 and average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _annualized_log_return_volatility(
    values: Sequence[float],
    period: int,
) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    returns: list[float] = []
    for index in range(1, len(values)):
        previous = values[index - 1]
        current = values[index]
        if previous <= 0 or current <= 0:
            raise ValueError("volatility requires positive analysis_close values")
        returns.append(log(current / previous))
        if len(returns) >= period:
            result[index] = stdev(returns[-period:]) * sqrt(252.0)
    return result


def _bollinger_band(
    mean: float | None,
    deviation: float | None,
    *,
    multiplier: float,
) -> float | None:
    if mean is None or deviation is None:
        return None
    return mean + multiplier * deviation
