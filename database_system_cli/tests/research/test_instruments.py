from datetime import date
from typing import Any

import pytest
from sqlalchemy.dialects import mysql

from fdp.research import InstrumentUniverseReader


class FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeMappings:
        return FakeMappings(self.rows)


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.rows)


def _mysql_sql(statement: Any) -> str:
    compiled = statement.compile(
        dialect=mysql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    return " ".join(str(compiled).split())


def test_reader_is_exported_from_research_package() -> None:
    assert InstrumentUniverseReader.__module__ == "fdp.research.instruments"


def test_instrument_query_uses_explicit_sorted_ids_and_date_overlap() -> None:
    reader = InstrumentUniverseReader(
        FakeConnection(),
        date_from="2024-01-01",
        date_to="2025-12-31",
    )

    statement = reader.build_instruments_query(instrument_ids=[7, 2, 7])
    sql = _mysql_sql(statement)

    assert statement.is_select
    assert "instrument.instrument_id IN (2, 7)" in sql
    assert "instrument.listed_date IS NULL OR" in sql
    assert "instrument.listed_date <= '2025-12-31'" in sql
    assert "instrument.delisted_date IS NULL OR" in sql
    assert "instrument.delisted_date >= '2024-01-01'" in sql
    assert sql.endswith("ORDER BY us_share.instrument.instrument_id")


def test_candidate_query_matches_current_and_overlapping_historical_identifiers() -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    statement = reader.build_find_instrument_candidates_query(
        identifiers=[" splk.us ", "SPLK", "splk"],
        date_from="2024-01-01",
        date_to="2025-12-31",
        market="us",
        asset_type="STOCK",
    )
    sql = _mysql_sql(statement)

    assert statement.is_select
    assert "instrument.symbol IN ('SPLK', 'SPLK.US')" in sql
    assert "instrument.provider_symbol IN ('SPLK', 'SPLK.US')" in sql
    assert "instrument_identifier_history.id_type IN ('ticker', 'provider_symbol')" in sql
    assert "instrument_identifier_history.id_value IN ('SPLK', 'SPLK.US')" in sql
    assert "instrument_identifier_history.valid_from IS NULL OR" in sql
    assert "instrument_identifier_history.valid_from <= '2025-12-31'" in sql
    assert "instrument_identifier_history.valid_to IS NULL OR" in sql
    assert "instrument_identifier_history.valid_to >= '2024-01-01'" in sql
    assert "instrument.listed_date IS NULL OR" in sql
    assert "instrument.delisted_date IS NULL OR" in sql
    assert "instrument.market = 'US'" in sql
    assert "instrument.asset_type = 'stock'" in sql
    assert "instrument.is_active =" not in sql
    assert "SELECT DISTINCT" not in sql
    assert " LIMIT " not in sql
    assert sql.endswith("ORDER BY us_share.instrument.instrument_id")


def test_candidate_query_without_dates_keeps_all_identifier_history_intervals() -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    sql = _mysql_sql(reader.build_find_instrument_candidates_query(identifiers=["REUSED"]))

    assert "instrument_identifier_history" in sql
    assert "instrument_identifier_history.valid_from" not in sql
    assert "instrument_identifier_history.valid_to" not in sql
    assert "instrument.market =" not in sql
    assert "instrument.asset_type =" not in sql


def test_candidate_reader_returns_every_candidate_including_inactive() -> None:
    rows = [
        {"instrument_id": 101, "symbol": "REUSED", "is_active": False},
        {"instrument_id": 202, "symbol": "REUSED", "is_active": True},
    ]
    connection = FakeConnection(rows)
    reader = InstrumentUniverseReader(connection)

    result = reader.find_instrument_candidates(identifiers=["REUSED"])

    assert result == rows
    assert [row["instrument_id"] for row in result] == [101, 202]
    assert result[0]["is_active"] is False
    assert len(connection.statements) == 1


def test_empty_candidate_identifiers_return_without_querying() -> None:
    connection = FakeConnection()
    reader = InstrumentUniverseReader(connection)

    result = reader.find_instrument_candidates(identifiers=[" "])

    assert result == []
    assert connection.statements == []


def test_empty_candidate_builder_cannot_scan_all_instruments() -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    sql = _mysql_sql(reader.build_find_instrument_candidates_query(identifiers=[]))

    assert "WHERE false = 1" in sql


def test_candidate_query_rejects_non_string_identifiers() -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    with pytest.raises(ValueError, match="identifiers"):
        reader.build_find_instrument_candidates_query(identifiers=[1])


@pytest.mark.parametrize(
    ("field_name", "kwargs"),
    [
        ("market", {"market": " "}),
        ("asset_type", {"asset_type": " "}),
    ],
)
def test_candidate_query_rejects_empty_optional_filters(
    field_name: str,
    kwargs: dict[str, str],
) -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    with pytest.raises(ValueError, match=field_name):
        reader.build_find_instrument_candidates_query(identifiers=["AAPL"], **kwargs)


def test_identifier_history_query_uses_interval_overlap_and_stable_order() -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    statement = reader.build_identifier_history_query(
        instrument_ids=[19, 3],
        date_from=date(2024, 1, 1),
        date_to=date(2025, 12, 31),
    )
    sql = _mysql_sql(statement)

    assert statement.is_select
    assert "instrument_identifier_history.instrument_id IN (3, 19)" in sql
    assert "valid_from IS NULL OR" in sql
    assert "valid_from <= '2025-12-31'" in sql
    assert "valid_to IS NULL OR" in sql
    assert "valid_to >= '2024-01-01'" in sql
    assert "ORDER BY us_share.instrument_identifier_history.instrument_id" in sql
    assert sql.endswith("instrument_identifier_history.identifier_history_id")


def test_lifecycle_query_keeps_undated_evidence_with_date_bounds() -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    statement = reader.build_lifecycle_events_query(
        instrument_ids=[5],
        date_from="2024-01-01",
        date_to="2025-12-31",
    )
    sql = _mysql_sql(statement)

    assert statement.is_select
    assert "instrument_lifecycle_event.instrument_id IN (5)" in sql
    assert "event_date IS NULL OR" in sql
    assert "event_date BETWEEN '2024-01-01' AND '2025-12-31'" in sql
    assert "ORDER BY us_share.instrument_lifecycle_event.instrument_id" in sql
    assert sql.endswith("instrument_lifecycle_event.lifecycle_event_id")


@pytest.mark.parametrize(
    "method_name",
    ["get_instruments", "get_identifier_history", "get_lifecycle_events"],
)
def test_empty_instrument_ids_return_without_querying(method_name: str) -> None:
    connection = FakeConnection()
    reader = InstrumentUniverseReader(connection)

    rows = getattr(reader, method_name)(instrument_ids=[])

    assert rows == []
    assert connection.statements == []


def test_empty_builder_is_a_select_that_cannot_scan_all_rows() -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    sql = _mysql_sql(reader.build_instruments_query(instrument_ids=[]))

    assert "WHERE false = 1" in sql


def test_identifier_reader_preserves_reused_ticker_rows() -> None:
    rows = [
        {
            "identifier_history_id": 10,
            "instrument_id": 101,
            "id_type": "ticker",
            "id_value": "REUSED",
        },
        {
            "identifier_history_id": 20,
            "instrument_id": 202,
            "id_type": "ticker",
            "id_value": "REUSED",
        },
    ]
    connection = FakeConnection(rows)
    reader = InstrumentUniverseReader(connection)

    result = reader.get_identifier_history(instrument_ids=[101, 202])

    assert result == rows
    assert {row["instrument_id"] for row in result} == {101, 202}
    assert len(connection.statements) == 1


def test_method_date_bounds_override_reader_defaults() -> None:
    reader = InstrumentUniverseReader(
        FakeConnection(),
        date_from="2020-01-01",
        date_to="2020-12-31",
    )

    resolved = reader.resolve_date_range(date_from="2024-01-01", date_to="2025-12-31")

    assert resolved == (date(2024, 1, 1), date(2025, 12, 31))


def test_reader_rejects_partial_date_bounds() -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    with pytest.raises(ValueError, match="provided together"):
        reader.build_identifier_history_query(
            instrument_ids=[1],
            date_from="2024-01-01",
        )


@pytest.mark.parametrize("instrument_ids", [[0], [-1], [True], ["1"]])
def test_reader_rejects_non_positive_or_non_integer_ids(instrument_ids: list[Any]) -> None:
    reader = InstrumentUniverseReader(FakeConnection())

    with pytest.raises(ValueError, match="instrument_ids"):
        reader.build_instruments_query(instrument_ids=instrument_ids)
