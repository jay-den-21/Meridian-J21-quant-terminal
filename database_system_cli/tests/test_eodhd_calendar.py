from datetime import date

from fdp.sources.eodhd.calendar import (
    US_MARKET_CLOSURE_OVERRIDE_SOURCE,
    build_market_calendar_rows,
)


def test_build_market_calendar_rows_uses_official_holidays_and_weekends() -> None:
    rows = build_market_calendar_rows(
        {
            "TradingHours": {"WorkingDays": "Mon,Tue,Wed,Thu,Fri"},
            "ExchangeHolidays": {
                "0": {
                    "Holiday": "New Year's Monday",
                    "Date": "2023-01-02",
                    "Type": "official",
                }
            },
        },
        date_from=date(2023, 1, 1),
        date_to=date(2023, 1, 4),
    )

    rows_by_date = {row["calendar_date"]: row for row in rows}

    assert rows_by_date[date(2023, 1, 1)]["is_trading_day"] is False
    assert rows_by_date[date(2023, 1, 2)]["is_trading_day"] is False
    assert rows_by_date[date(2023, 1, 3)]["is_trading_day"] is True
    assert rows_by_date[date(2023, 1, 4)]["is_trading_day"] is True


def test_build_market_calendar_rows_applies_documented_us_closure_overrides() -> None:
    payload = {
        "TradingHours": {"WorkingDays": "Mon,Tue,Wed,Thu,Fri"},
        "ExchangeHolidays": {},
    }

    rows = build_market_calendar_rows(
        payload,
        date_from=date(2012, 1, 2),
        date_to=date(2012, 10, 30),
        market="US",
    )
    rows_by_date = {row["calendar_date"]: row for row in rows}

    for closure_date in (date(2012, 1, 2), date(2012, 10, 29), date(2012, 10, 30)):
        assert rows_by_date[closure_date]["is_trading_day"] is False
        assert rows_by_date[closure_date]["source"] == US_MARKET_CLOSURE_OVERRIDE_SOURCE
    assert rows_by_date[date(2012, 7, 3)]["is_trading_day"] is True


def test_build_market_calendar_rows_does_not_apply_us_overrides_to_other_markets() -> None:
    rows = build_market_calendar_rows(
        {
            "TradingHours": {"WorkingDays": "Mon,Tue,Wed,Thu,Fri"},
            "ExchangeHolidays": {},
        },
        date_from=date(2012, 10, 29),
        date_to=date(2012, 10, 30),
        market="LSE",
    )

    assert all(row["is_trading_day"] is True for row in rows)
