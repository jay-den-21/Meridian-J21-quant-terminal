from dataclasses import dataclass
from datetime import date
from typing import Any

from fdp.quality.validation import validate_daily_prices
from fdp.storage.tables import data_quality_check_run, data_quality_issue


@dataclass
class FakeResult:
    inserted_primary_key: tuple[int, ...] = ()


class FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class FakeSelectResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeMappings:
        return FakeMappings(self.rows)


class FakeValidationConnection:
    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.select_rows = [[], [], [], []]

    def execute(self, statement):
        self.statements.append(statement)
        table = getattr(statement, "table", None)
        if table is data_quality_check_run:
            return FakeResult(inserted_primary_key=(101,))
        if table is None:
            return FakeSelectResult(self.select_rows.pop(0))
        return FakeResult()


def test_validate_daily_prices_records_successful_check_run_without_issues() -> None:
    connection = FakeValidationConnection()

    result = validate_daily_prices(
        connection,
        date_from=date(2023, 1, 1),
        date_to=date(2025, 12, 31),
        asset_types=["stock"],
    )

    assert result.issues_found == 0
    assert result.table_summaries[0].check_run_id == 101
    assert result.table_summaries[0].target_table == "stock_daily_price"
    statement_tables = [getattr(statement, "table", None) for statement in connection.statements]
    assert statement_tables.count(data_quality_check_run) == 2
    assert data_quality_issue not in statement_tables
