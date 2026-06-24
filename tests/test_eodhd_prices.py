from datetime import date
from decimal import Decimal

from fdp.sources.eodhd import parse_daily_price_row, parse_daily_price_rows


def test_parse_daily_price_row_validates_and_attaches_instrument_metadata() -> None:
    row = parse_daily_price_row(
        {
            "date": "2023-01-03",
            "open": "100.00",
            "high": "101.00",
            "low": "99.50",
            "close": "100.25",
            "adjusted_close": "100.20",
            "volume": "1234567",
        },
        instrument_id=1,
        symbol="AAPL",
        provider_symbol="AAPL.US",
        currency="USD",
    )

    assert row == {
        "instrument_id": 1,
        "symbol": "AAPL",
        "provider_symbol": "AAPL.US",
        "trade_date": date(2023, 1, 3),
        "open": Decimal("100.00"),
        "high": Decimal("101.00"),
        "low": Decimal("99.50"),
        "close": Decimal("100.25"),
        "adjusted_close": Decimal("100.20"),
        "volume": 1234567,
        "currency": "USD",
        "source": "EODHD",
        "source_updated_at": None,
    }


def test_parse_daily_price_rows_rejects_invalid_ohlcv_rows() -> None:
    parsed = parse_daily_price_rows(
        [
            {
                "date": "2023-01-03",
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100",
                "adjusted_close": "100",
                "volume": "1000",
            },
            {
                "date": "2023-01-04",
                "open": "100",
                "high": "98",
                "low": "99",
                "close": "100",
                "adjusted_close": "100",
                "volume": "1000",
            },
        ],
        instrument_id=1,
        symbol="AAPL",
        provider_symbol="AAPL.US",
        currency="USD",
    )

    assert len(parsed.accepted) == 1
    assert len(parsed.rejected) == 1
    assert parsed.rejected[0].provider_symbol == "AAPL.US"
    assert parsed.rejected[0].reason == "invalid_ohlcv: high is lower than low"
