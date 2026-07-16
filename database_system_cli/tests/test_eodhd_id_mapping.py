from __future__ import annotations

from hashlib import sha256
from typing import Any

from sqlalchemy.dialects import mysql

from fdp.sources.eodhd.id_mapping import (
    IdentifierMappingEnvelope,
    parse_identifier_mapping_envelope,
    parse_identifier_mapping_row,
)
from fdp.sources.eodhd.ingest.id_mapping import (
    IdentifierMappingResolver,
    process_identifier_mapping_page,
)
from fdp.storage.tables import (
    identifier_mapping_unmatched_observation,
    instrument_identifier_history,
)


AAPL_MAPPING = {
    "symbol": "AAPL.US",
    "isin": "US0378331005",
    "figi": "BBG000B9XRY4",
    "lei": "HWUPKR0MPOU8FGXBT394",
    "cusip": "037833100",
    "cik": "320193",
}
MSFT_MAPPING = {
    "symbol": "MSFT.US",
    "isin": "US5949181045",
    "figi": "BBG000BPH459",
    "lei": "INR2EJN1ERAN0W5ZP974",
    "cusip": "594918104",
    "cik": "789019",
}


class _MappingsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> "_MappingsResult":
        return self

    def __iter__(self):
        return iter(self.rows)


class _PageConnection:
    def __init__(self, select_rows: list[list[dict[str, Any]]]) -> None:
        self._select_rows = iter(select_rows)
        self.writes: list[Any] = []

    def execute(self, statement: Any) -> _MappingsResult:
        if getattr(statement, "is_select", False):
            return _MappingsResult(next(self._select_rows))
        self.writes.append(statement)
        return _MappingsResult([])


def _envelope(*rows: dict[str, Any]) -> IdentifierMappingEnvelope:
    return parse_identifier_mapping_envelope(
        {
            "meta": {"total": len(rows), "limit": 1000, "offset": 0},
            "data": list(rows),
            "links": {"next": None},
        }
    )


def _insert_params(connection: _PageConnection, table: Any) -> dict[str, Any]:
    statement = next(
        statement
        for statement in connection.writes
        if getattr(statement, "is_insert", False) and statement.table is table
    )
    return statement.compile(dialect=mysql.dialect()).params


def test_parser_accepts_standard_identifiers_and_preserves_cik_zeroes() -> None:
    record = parse_identifier_mapping_row(AAPL_MAPPING)

    assert record.provider_symbol == "AAPL.US"
    assert record.row_error is None
    assert record.invalid_fields == ()
    assert record.identifiers == {
        "isin": "US0378331005",
        "figi": "BBG000B9XRY4",
        "lei": "HWUPKR0MPOU8FGXBT394",
        "cusip": "037833100",
        "cik": "0000320193",
    }


def test_parser_rejects_bad_checksums_and_non_scalar_fields_without_losing_raw_row() -> None:
    record = parse_identifier_mapping_row(
        {
            **AAPL_MAPPING,
            "isin": "US0378331006",
            "figi": "BBG000B9XRY5",
            "cusip": ["037833100"],
        }
    )

    assert record.row_error is None
    assert record.invalid_fields == ("isin", "figi", "cusip")
    assert set(record.identifiers) == {"lei", "cik"}
    assert '"cusip":["037833100"]' in record.raw_payload


def test_parser_treats_blank_optional_identifiers_as_missing() -> None:
    record = parse_identifier_mapping_row(
        {
            **AAPL_MAPPING,
            "cusip": "  ",
            "cik": "",
        }
    )

    assert record.row_error is None
    assert record.invalid_fields == ()
    assert set(record.identifiers) == {"isin", "figi", "lei"}
    assert record.fingerprint == sha256(record.raw_payload.encode()).hexdigest()


def test_parser_validates_pagination_and_retains_malformed_row_evidence() -> None:
    envelope = parse_identifier_mapping_envelope(
        {
            "meta": {"total": 2, "limit": 1, "offset": 0},
            "data": ["not-an-object"],
            "links": {"next": "/api/id-mapping?page[offset]=1"},
        }
    )

    assert envelope.has_next is True
    assert envelope.rows[0].row_error == "mapping_row_not_object"
    assert envelope.rows[0].raw_payload == '"not-an-object"'


def test_resolver_prefers_current_then_requires_unique_history_owner() -> None:
    resolver = IdentifierMappingResolver(
        current={"CURRENT.US": 1},
        historical={
            "CURRENT.US": frozenset({2, 3}),
            "OLD.US": frozenset({4}),
            "REUSED.US": frozenset({5, 6}),
        },
    )

    assert resolver.resolve("CURRENT.US").instrument_id == 1
    assert resolver.resolve("OLD.US").instrument_id == 4
    assert resolver.resolve("REUSED.US").reason == "ambiguous_provider_symbol_history"
    assert resolver.resolve("MISSING.US").reason == "missing_instrument"


def test_page_writes_matched_ids_and_stages_unknown_symbol() -> None:
    unknown = {**MSFT_MAPPING, "symbol": "UNKNOWN.US"}
    connection = _PageConnection(
        [
            [{"provider_symbol": "AAPL.US", "instrument_id": 11}],
            [],
            [],
        ]
    )

    result = process_identifier_mapping_page(
        connection,
        run_id=7,
        market="US",
        envelope=_envelope(AAPL_MAPPING, unknown),
    )

    assert result.rows_fetched == 2
    assert result.rows_matched == 1
    assert result.identifiers_inserted == 5
    assert result.rows_unmatched == 1
    canonical = _insert_params(connection, instrument_identifier_history)
    unmatched = _insert_params(connection, identifier_mapping_unmatched_observation)
    assert set(value for key, value in canonical.items() if key.startswith("id_type")) == {
        "isin",
        "figi",
        "lei",
        "cusip",
        "cik",
    }
    assert "missing_instrument" in set(
        value for key, value in unmatched.items() if key.startswith("reason")
    )


def test_page_keeps_multiple_undated_aliases_for_the_same_instrument() -> None:
    connection = _PageConnection(
        [
            [{"provider_symbol": "AAPL.US", "instrument_id": 11}],
            [],
            [
                {
                    "instrument_id": 11,
                    "id_type": "isin",
                    "id_value": "US5949181045",
                }
            ],
        ]
    )

    result = process_identifier_mapping_page(
        connection,
        run_id=8,
        market="US",
        envelope=_envelope(AAPL_MAPPING),
    )

    assert result.identifier_conflicts == 0
    assert result.identifiers_inserted == 5
    assert result.rows_unmatched == 0


def test_page_deduplicates_identical_mapping_rows_before_upsert() -> None:
    connection = _PageConnection(
        [
            [{"provider_symbol": "AAPL.US", "instrument_id": 11}],
            [],
            [],
        ]
    )

    result = process_identifier_mapping_page(
        connection,
        run_id=9,
        market="US",
        envelope=_envelope(AAPL_MAPPING, AAPL_MAPPING),
    )

    assert result.rows_matched == 2
    assert result.identifiers_inserted == 5
    canonical = _insert_params(connection, instrument_identifier_history)
    assert len([key for key in canonical if key.startswith("id_type")]) == 5
    assert len([statement for statement in connection.writes if statement.is_update]) == 1


def test_repeated_page_counts_existing_identifiers_as_unchanged() -> None:
    connection = _PageConnection(
        [
            [{"provider_symbol": "AAPL.US", "instrument_id": 11}],
            [],
            [
                {"instrument_id": 11, "id_type": id_type, "id_value": id_value}
                for id_type, id_value in {
                    "isin": "US0378331005",
                    "figi": "BBG000B9XRY4",
                    "lei": "HWUPKR0MPOU8FGXBT394",
                    "cusip": "037833100",
                    "cik": "0000320193",
                }.items()
            ],
        ]
    )

    result = process_identifier_mapping_page(
        connection,
        run_id=9,
        market="US",
        envelope=_envelope(AAPL_MAPPING),
    )

    assert result.identifiers_inserted == 0
    assert result.identifiers_unchanged == 5
    assert result.rows_unmatched == 0
