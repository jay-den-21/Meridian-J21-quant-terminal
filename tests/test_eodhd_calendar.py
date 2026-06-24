from datetime import date

from fdp.sources.eodhd.calendar import build_market_calendar_rows


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
