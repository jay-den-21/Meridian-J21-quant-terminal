"""Build daily market calendar rows from EODHD exchange-details payloads."""

from datetime import date, timedelta
from typing import Any

WEEKDAY_CODES = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def build_market_calendar_rows(
    exchange_details: dict[str, Any],
    *,
    date_from: date,
    date_to: date,
    source: str = "EODHD_EXCHANGE_DETAILS",
) -> list[dict[str, Any]]:
    """Build storage-ready daily calendar rows for one exchange.

    Input: EODHD exchange-details payload and an inclusive date range.
    Output: one `market_calendar` row for every calendar date in the inclusive range.
    Flow: trading weekdays + holiday map -> date range expansion -> calendar rows.
    """
    if date_to < date_from:
        raise ValueError("date_to must be greater than or equal to date_from")

    working_days = _working_day_numbers(exchange_details)
    non_trading_dates = _holiday_dates(exchange_details)

    rows: list[dict[str, Any]] = []
    for calendar_date in _date_range(date_from, date_to):
        is_working_day = calendar_date.weekday() in working_days
        is_trading_day = is_working_day and calendar_date not in non_trading_dates
        rows.append(
            {
                "calendar_date": calendar_date,
                "is_trading_day": is_trading_day,
                "source": source,
            }
        )

    return rows


def _working_day_numbers(exchange_details: dict[str, Any]) -> set[int]:
    trading_hours = exchange_details.get("TradingHours")
    if not isinstance(trading_hours, dict):
        raise ValueError("missing EODHD TradingHours object")

    raw_working_days = trading_hours.get("WorkingDays")
    if not raw_working_days:
        raise ValueError("missing EODHD TradingHours.WorkingDays")

    working_days: set[int] = set()
    for part in str(raw_working_days).replace(" ", "").split(","):
        if not part:
            continue
        code = part[:3].lower()
        if code not in WEEKDAY_CODES:
            raise ValueError(f"invalid EODHD working day: {part}")
        working_days.add(WEEKDAY_CODES[code])

    if not working_days:
        raise ValueError("empty EODHD TradingHours.WorkingDays")
    return working_days


def _holiday_dates(exchange_details: dict[str, Any]) -> set[date]:
    holidays = exchange_details.get("ExchangeHolidays") or {}
    if not isinstance(holidays, dict):
        raise ValueError("invalid EODHD ExchangeHolidays object")

    non_trading_dates: set[date] = set()
    for key, payload in holidays.items():
        if not isinstance(payload, dict):
            continue

        holiday_date = _holiday_date(key, payload)
        holiday_type = str(payload.get("Type", "")).strip().lower()
        if holiday_type:
            non_trading_dates.add(holiday_date)

    return non_trading_dates


def _holiday_date(key: str, payload: dict[str, Any]) -> date:
    raw_date = payload.get("Date", key)
    try:
        return date.fromisoformat(str(raw_date))
    except ValueError as exc:
        raise ValueError(f"invalid EODHD holiday date: {raw_date}") from exc


def _date_range(date_from: date, date_to: date):
    current = date_from
    while current <= date_to:
        yield current
        current += timedelta(days=1)
