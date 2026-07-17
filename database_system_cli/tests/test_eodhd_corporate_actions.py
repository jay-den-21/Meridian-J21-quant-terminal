from datetime import date
from decimal import Decimal

from fdp.sources.eodhd import (
    parse_dividend_row,
    parse_dividend_rows,
    parse_split_row,
    parse_split_rows,
)


def test_parse_dividend_row_attaches_instrument_identity() -> None:
    row = parse_dividend_row(
        {
            "date": "2025-05-12",
            "declarationDate": "2025-05-01",
            "recordDate": "2025-05-13",
            "paymentDate": "2025-05-15",
            "period": "Quarterly",
            "value": "0.25",
            "unadjustedValue": "0.25",
            "currency": "USD",
        },
        instrument_id=1,
        symbol="AAPL",
        provider_symbol="AAPL.US",
    )

    assert row["action_date"] == date(2025, 5, 12)
    assert row["cash_amount"] == Decimal("0.25")
    assert row["record_date"] == date(2025, 5, 13)
    assert row["instrument_id"] == 1
    assert row["action_type"] == "dividend"


def test_parse_split_row_parses_ratio() -> None:
    row = parse_split_row(
        {"date": "2020-08-31", "split": "4.000000/1.000000"},
        instrument_id=1,
        symbol="AAPL",
        provider_symbol="AAPL.US",
    )

    assert row["action_date"] == date(2020, 8, 31)
    assert row["split_numerator"] == Decimal("4.000000")
    assert row["split_denominator"] == Decimal("1.000000")
    assert row["cash_amount"] is None


def test_parse_rows_reject_invalid_and_non_positive_values() -> None:
    dividends = parse_dividend_rows(
        [
            {"date": "2025-05-12", "value": "0.25"},
            {"date": "bad-date", "value": "0.25"},
            {"date": "2025-06-01", "value": "0"},
        ],
        instrument_id=1,
        symbol="AAPL",
        provider_symbol="AAPL.US",
    )
    splits = parse_split_rows(
        [
            {"date": "2020-08-31", "split": "4.000000/1.000000"},
            {"date": "2020-09-01", "split": "0/1"},
        ],
        instrument_id=1,
        symbol="AAPL",
        provider_symbol="AAPL.US",
    )

    assert len(dividends.accepted) == 1
    assert len(dividends.rejected) == 2
    assert len(splits.accepted) == 1
    assert len(splits.rejected) == 1


def test_exact_duplicates_collapse_but_same_date_conflicts_are_rejected() -> None:
    exact = {"date": "2025-05-12", "value": "0.25", "currency": "USD"}
    duplicates = parse_dividend_rows(
        [exact, dict(exact)],
        instrument_id=1,
        symbol="AAPL",
        provider_symbol="AAPL.US",
    )
    conflicts = parse_dividend_rows(
        [exact, {**exact, "value": "0.50"}],
        instrument_id=1,
        symbol="AAPL",
        provider_symbol="AAPL.US",
    )

    assert len(duplicates.accepted) == 1
    assert duplicates.rejected == []
    assert conflicts.accepted == []
    assert len(conflicts.rejected) == 2
    assert all("conflicting" in row.reason for row in conflicts.rejected)
