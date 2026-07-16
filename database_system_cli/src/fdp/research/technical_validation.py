"""Compare local daily indicator formulas with small EODHD Technical API samples."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from fdp.research.daily_prices import DailyPriceReader
from fdp.research.indicators import calculate_daily_indicators
from fdp.sources.eodhd.client import EodhdClient
from fdp.storage.tables import instrument

TECHNICAL_API_UNITS_PER_REQUEST = 5
TECHNICAL_VALIDATION_SPECS = (
    ("sma_20", "sma", 20, "sma"),
    ("ema_20", "ema", 20, "ema"),
    ("rsi_14", "rsi", 14, "rsi"),
)


@dataclass(frozen=True)
class TechnicalComparison:
    """One local/provider indicator comparison summary."""

    provider_symbol: str
    asset_type: str
    local_field: str
    provider_function: str
    period: int
    status: str
    provider_rows: int
    overlapping_rows: int
    max_absolute_error: float | None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def required_technical_validation_units(symbol_count: int) -> int:
    """Return the weighted API units required for the fixed validation matrix."""
    if symbol_count < 1:
        raise ValueError("symbol_count must be positive")
    return symbol_count * len(TECHNICAL_VALIDATION_SPECS) * TECHNICAL_API_UNITS_PER_REQUEST


def validate_technical_indicators(
    connection: Connection,
    client: EodhdClient,
    *,
    provider_symbols: list[str],
    date_from: date,
    date_to: date,
    tolerance: float = 0.0002,
) -> list[TechnicalComparison]:
    """Run a bounded local-vs-provider comparison for SMA20, EMA20, and RSI14.

    Input: read connection, budgeted EODHD client, provider symbols, date range, tolerance.
    Output: one comparison per symbol and indicator with overlap/error metrics.
    Flow: resolve instrument -> read local prices -> calculate indicators -> fetch/compare API rows.
    """
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")

    normalized_symbols = [symbol.strip().upper() for symbol in provider_symbols if symbol.strip()]
    if not normalized_symbols:
        raise ValueError("provider_symbols must contain at least one symbol")
    if len(normalized_symbols) != len(set(normalized_symbols)):
        raise ValueError("provider_symbols must not contain duplicates")

    resolved = {
        row["provider_symbol"]: dict(row)
        for row in connection.execute(
            select(
                instrument.c.provider_symbol,
                instrument.c.asset_type,
            ).where(
                instrument.c.market == "US",
                instrument.c.provider_symbol.in_(normalized_symbols),
                instrument.c.asset_type.in_(("stock", "etf", "fund", "index")),
            )
        ).mappings()
    }
    missing = [symbol for symbol in normalized_symbols if symbol not in resolved]
    if missing:
        raise ValueError(f"unknown canonical provider_symbol(s): {', '.join(missing)}")

    reader = DailyPriceReader(connection)
    comparisons: list[TechnicalComparison] = []
    for provider_symbol in normalized_symbols:
        asset_type = str(resolved[provider_symbol]["asset_type"])
        local_rows = reader.get_daily_prices(
            symbols=[provider_symbol],
            asset_type=asset_type,
            date_from=date_from,
            date_to=date_to,
            adjusted=True,
        )
        indicators = calculate_daily_indicators(local_rows, adjusted=True)

        for local_field, provider_function, period, provider_field in TECHNICAL_VALIDATION_SPECS:
            response = client.get_technical(
                provider_symbol,
                function=provider_function,
                period=period,
                date_from=date_from,
                date_to=date_to,
                order="a",
            )
            if not response.success:
                comparisons.append(
                    TechnicalComparison(
                        provider_symbol=provider_symbol,
                        asset_type=asset_type,
                        local_field=local_field,
                        provider_function=provider_function,
                        period=period,
                        status="failed",
                        provider_rows=0,
                        overlapping_rows=0,
                        max_absolute_error=None,
                        error_message=response.error_message,
                    )
                )
                continue

            overlapping_rows, max_error = _compare_indicator_series(
                indicators,
                response.payload,
                local_field=local_field,
                provider_field=provider_field,
            )
            status = "pass" if overlapping_rows > 0 and max_error <= tolerance else "mismatch"
            comparisons.append(
                TechnicalComparison(
                    provider_symbol=provider_symbol,
                    asset_type=asset_type,
                    local_field=local_field,
                    provider_function=provider_function,
                    period=period,
                    status=status,
                    provider_rows=response.rows_returned,
                    overlapping_rows=overlapping_rows,
                    max_absolute_error=max_error if overlapping_rows else None,
                    error_message=None if overlapping_rows else "no overlapping indicator dates",
                )
            )
    return comparisons


def _compare_indicator_series(
    local_rows: list[dict[str, Any]],
    provider_rows: list[dict[str, Any]],
    *,
    local_field: str,
    provider_field: str,
) -> tuple[int, float]:
    local_values = {
        str(row["trade_date"]): float(row[local_field])
        for row in local_rows
        if row.get(local_field) is not None
    }
    errors = []
    for row in provider_rows:
        provider_date = str(row.get("date", ""))
        provider_value = row.get(provider_field)
        if provider_date in local_values and provider_value is not None:
            errors.append(abs(local_values[provider_date] - float(provider_value)))
    return len(errors), max(errors, default=0.0)
