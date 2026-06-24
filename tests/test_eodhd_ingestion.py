from dataclasses import dataclass
from datetime import date
from typing import Any

from fdp.sources.eodhd.client import EodhdApiResponse
from fdp.sources.eodhd.ingestion import (
    load_index_daily_prices,
    load_exchange_symbols,
    load_historical_daily_prices,
    load_market_calendar,
    reconcile_symbol_changes,
)
from fdp.sources.eodhd.instruments import SymbolChange
from fdp.storage.tables import (
    api_call_log,
    index_daily_price,
    ingestion_task_run,
    instrument,
    instrument_identifier_history,
    market_calendar,
    stock_daily_price,
)


@dataclass
class FakeResult:
    inserted_primary_key: tuple[int, ...] = ()


class FakeMappings:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def first(self) -> dict[str, Any] | None:
        return self.row


class FakeSelectResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def mappings(self) -> FakeMappings:
        return FakeMappings(self.row)


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    def execute(self, statement) -> FakeResult:
        self.statements.append(statement)
        table = getattr(statement, "table", None)
        if table is ingestion_task_run:
            return FakeResult(inserted_primary_key=(123,))
        return FakeResult()


class FakeClient:
    def get_symbol_change_history(self, from_date: date) -> EodhdApiResponse:
        assert from_date == date(2022, 7, 22)
        return EodhdApiResponse(
            endpoint="/symbol-change-history",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=0,
            duration_ms=8,
            payload=[],
        )

    def get_exchange_symbols(self, market: str) -> EodhdApiResponse:
        assert market == "US"
        return EodhdApiResponse(
            endpoint="/exchange-symbol-list/US",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=3,
            duration_ms=12,
            payload=[
                {
                    "Code": "AAPL",
                    "Name": "Apple Inc.",
                    "Exchange": "NASDAQ",
                    "Type": "Common Stock",
                    "Currency": "USD",
                },
                {"Code": "ABC", "Type": "Bond"},
                {"Code": "BAD", "Type": "ETF", "Currency": "USD"},
            ],
        )


def test_load_exchange_symbols_records_task_api_log_and_upserts_valid_rows() -> None:
    connection = FakeConnection()

    result = load_exchange_symbols(connection, FakeClient())

    assert result == result.__class__(
        run_id=123,
        status="partial_failed",
        rows_fetched=3,
        rows_accepted=1,
        rows_rejected=2,
        api_calls=2,
        rejected_rows=result.rejected_rows,
        error_message="2 EODHD instrument row(s) were rejected",
    )
    assert [row.reason for row in result.rejected_rows] == [
        "unsupported_asset_type",
        "missing required EODHD field: Name, name",
    ]

    statement_tables = [getattr(statement, "table", None) for statement in connection.statements]
    assert statement_tables == [
        ingestion_task_run,
        api_call_log,
        api_call_log,
        instrument,
        ingestion_task_run,
    ]


class FailingClient:
    def get_symbol_change_history(self, from_date: date) -> EodhdApiResponse:
        return EodhdApiResponse(
            endpoint="/symbol-change-history",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=0,
            duration_ms=8,
            payload=[],
        )

    def get_exchange_symbols(self, market: str) -> EodhdApiResponse:
        return EodhdApiResponse(
            endpoint="/exchange-symbol-list/US",
            status_code=500,
            success=False,
            retry_count=3,
            rows_returned=0,
            duration_ms=30,
            payload=[],
            error_message="server error",
        )


def test_load_exchange_symbols_marks_task_failed_when_api_fails() -> None:
    connection = FakeConnection()

    result = load_exchange_symbols(connection, FailingClient())

    assert result.status == "failed"
    assert result.error_message == "server error"
    statement_tables = [getattr(statement, "table", None) for statement in connection.statements]
    assert statement_tables == [
        ingestion_task_run,
        api_call_log,
        api_call_log,
        ingestion_task_run,
    ]


class FailingSymbolChangeClient:
    def get_symbol_change_history(self, from_date: date) -> EodhdApiResponse:
        return EodhdApiResponse(
            endpoint="/symbol-change-history",
            status_code=500,
            success=False,
            retry_count=3,
            rows_returned=0,
            duration_ms=30,
            payload=[],
            error_message="rename API failed",
        )


def test_load_exchange_symbols_fails_when_symbol_change_history_fails() -> None:
    connection = FakeConnection()

    result = load_exchange_symbols(connection, FailingSymbolChangeClient())

    assert result.status == "failed"
    assert result.api_calls == 1
    assert result.error_message == "rename API failed"
    statement_tables = [getattr(statement, "table", None) for statement in connection.statements]
    assert statement_tables == [
        ingestion_task_run,
        api_call_log,
        ingestion_task_run,
    ]


class FakeReconcileConnection:
    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.select_rows = [{"instrument_id": 42}, None]

    def execute(self, statement):
        self.statements.append(statement)
        table = getattr(statement, "table", None)
        if table is None:
            return FakeSelectResult(self.select_rows.pop(0))
        return FakeResult()


def test_reconcile_symbol_changes_updates_existing_old_provider_symbol() -> None:
    connection = FakeReconcileConnection()
    symbol_change = SymbolChange(
        exchange="US",
        old_symbol="FB",
        new_symbol="META",
        old_provider_symbol="FB.US",
        new_provider_symbol="META.US",
        company_name="Meta Platforms Inc.",
        effective=date(2022, 6, 9),
    )

    reconciled = reconcile_symbol_changes(connection, [symbol_change])

    assert reconciled == 1
    statement_tables = [getattr(statement, "table", None) for statement in connection.statements]
    assert instrument in statement_tables
    assert instrument_identifier_history in statement_tables


class FakeHistoryMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class FakeHistorySelectResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeHistoryMappings:
        return FakeHistoryMappings(self.rows)


class FakeHistoryConnection:
    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.instrument_rows = [
            {
                "instrument_id": 1,
                "symbol": "AAPL",
                "provider_symbol": "AAPL.US",
                "asset_type": "stock",
                "currency": "USD",
            }
        ]

    def execute(self, statement):
        self.statements.append(statement)
        table = getattr(statement, "table", None)
        if table is ingestion_task_run:
            return FakeResult(inserted_primary_key=(456,))
        if table is None:
            return FakeHistorySelectResult(self.instrument_rows)
        return FakeResult()


class FakeHistoryClient:
    def get_historical_eod(
        self,
        provider_symbol: str,
        *,
        date_from: date,
        date_to: date,
    ) -> EodhdApiResponse:
        assert provider_symbol == "AAPL.US"
        assert date_from == date(2023, 1, 1)
        assert date_to == date(2024, 1, 1)
        return EodhdApiResponse(
            endpoint="/eod/AAPL.US",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=1,
            duration_ms=10,
            payload=[
                {
                    "date": "2023-01-03",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "adjusted_close": "100.5",
                    "volume": "1000",
                }
            ],
        )


def test_load_historical_daily_prices_upserts_valid_rows() -> None:
    connection = FakeHistoryConnection()

    result = load_historical_daily_prices(
        connection,
        FakeHistoryClient(),
        symbols=["AAPL"],
        date_from=date(2023, 1, 1),
        date_to=date(2024, 1, 1),
    )

    assert result.status == "success"
    assert result.run_id == 456
    assert result.symbols_loaded == 1
    assert result.rows_fetched == 1
    assert result.rows_inserted == 1
    assert result.rows_rejected == 0
    statement_tables = [getattr(statement, "table", None) for statement in connection.statements]
    assert statement_tables == [
        ingestion_task_run,
        None,
        api_call_log,
        stock_daily_price,
        ingestion_task_run,
    ]


class FakeIndexConnection(FakeHistoryConnection):
    def __init__(self) -> None:
        super().__init__()
        self.instrument_rows = [
            {
                "instrument_id": 10,
                "symbol": "GSPC",
                "provider_symbol": "GSPC.INDX",
                "asset_type": "index",
                "currency": "USD",
            }
        ]


class FakeIndexClient:
    def get_historical_eod(
        self,
        provider_symbol: str,
        *,
        date_from: date,
        date_to: date,
    ) -> EodhdApiResponse:
        assert provider_symbol == "GSPC.INDX"
        assert date_from == date(2023, 1, 1)
        assert date_to == date(2025, 12, 31)
        return EodhdApiResponse(
            endpoint="/eod/GSPC.INDX",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=1,
            duration_ms=10,
            payload=[
                {
                    "date": "2023-01-03",
                    "open": "3853.29",
                    "high": "3878.46",
                    "low": "3794.33",
                    "close": "3824.14",
                    "adjusted_close": "3824.14",
                    "volume": "3959140000",
                }
            ],
        )


def test_load_index_daily_prices_creates_index_instrument_and_upserts_prices() -> None:
    connection = FakeIndexConnection()

    result = load_index_daily_prices(
        connection,
        FakeIndexClient(),
        provider_symbols=["GSPC.INDX"],
        date_from=date(2023, 1, 1),
        date_to=date(2025, 12, 31),
    )

    assert result.status == "success"
    assert result.symbols_loaded == 1
    assert result.rows_fetched == 1
    assert result.rows_inserted == 1
    statement_tables = [getattr(statement, "table", None) for statement in connection.statements]
    assert statement_tables == [
        ingestion_task_run,
        instrument,
        None,
        api_call_log,
        index_daily_price,
        ingestion_task_run,
    ]


class FakeCalendarConnection:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    def execute(self, statement):
        self.statements.append(statement)
        table = getattr(statement, "table", None)
        if table is ingestion_task_run:
            return FakeResult(inserted_primary_key=(789,))
        return FakeResult()


class FakeCalendarClient:
    def get_exchange_details(
        self,
        market: str,
        *,
        date_from: date,
        date_to: date,
    ) -> EodhdApiResponse:
        assert market == "US"
        assert date_from == date(2023, 1, 1)
        assert date_to == date(2023, 1, 4)
        return EodhdApiResponse(
            endpoint="/exchange-details/US",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=1,
            duration_ms=10,
            payload=[
                {
                    "TradingHours": {"WorkingDays": "Mon,Tue,Wed,Thu,Fri"},
                    "ExchangeHolidays": {
                        "0": {
                            "Holiday": "New Year's Monday",
                            "Date": "2023-01-02",
                            "Type": "official",
                        }
                    },
                }
            ],
        )


def test_load_market_calendar_upserts_generated_calendar_rows() -> None:
    connection = FakeCalendarConnection()

    result = load_market_calendar(
        connection,
        FakeCalendarClient(),
        date_from=date(2023, 1, 1),
        date_to=date(2023, 1, 4),
    )

    assert result.status == "success"
    assert result.run_id == 789
    assert result.rows_fetched == 1
    assert result.rows_inserted == 4
    statement_tables = [getattr(statement, "table", None) for statement in connection.statements]
    assert statement_tables == [
        ingestion_task_run,
        api_call_log,
        market_calendar,
        ingestion_task_run,
    ]
