from datetime import date

from fdp.quality.corporate_actions import _issue_type
from fdp.sources.eodhd.client import EodhdApiResponse
from fdp.sources.eodhd.corporate_action_identity import CorporateActionIdentityResolver
from fdp.sources.eodhd.corporate_actions import RejectedCorporateActionRow
from fdp.sources.eodhd.ingest.corporate_actions import (
    _parse_action_response,
    load_corporate_action_unit,
)


class RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[object] = []

    def execute(self, statement):
        self.statements.append(statement)
        return None


class FakeCorporateActionClient:
    def get_dividends(self, provider_symbol, *, date_from=None, date_to=None):
        return EodhdApiResponse(
            endpoint=f"/div/{provider_symbol}",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=1,
            duration_ms=1,
            payload=[{"date": "2025-05-12", "value": "0.25"}],
        )

    def get_splits(self, provider_symbol, *, date_from=None, date_to=None):
        return EodhdApiResponse(
            endpoint=f"/splits/{provider_symbol}",
            status_code=200,
            success=True,
            retry_count=0,
            rows_returned=2,
            duration_ms=1,
            payload=[
                {"date": "2020-08-31", "split": "4/1"},
                {"date": "bad", "split": "2/1"},
            ],
        )


def test_corporate_action_unit_audits_calls_and_rejects_bad_rows() -> None:
    connection = RecordingConnection()

    result = load_corporate_action_unit(
        connection,
        FakeCorporateActionClient(),
        run_id=11,
        check_run_id=22,
        market="US",
        instrument_row={
            "instrument_id": 1,
            "symbol": "AAPL",
            "provider_symbol": "AAPL.US",
        },
        action_types=["dividend", "split"],
        date_from=date(2020, 1, 1),
        date_to=date(2025, 12, 31),
    )

    assert result.status == "partial_failed"
    assert result.rows_fetched == 3
    assert result.rows_inserted == 2
    assert result.rows_rejected == 1
    assert result.api_calls == 2
    assert len(connection.statements) == 5  # two API logs, two upserts, one DQ issue insert


def test_corporate_action_rows_route_by_event_date_and_reject_non_stock_owner() -> None:
    current = {
        "instrument_id": 1,
        "symbol": "BAM",
        "provider_symbol": "BAM.US",
        "asset_type": "stock",
    }
    old_stock = {
        "instrument_id": 2,
        "symbol": "BN",
        "provider_symbol": "BN.US",
        "asset_type": "stock",
        "id_value": "BAM.US",
        "valid_from": None,
        "valid_to": date(2022, 12, 11),
    }
    resolver = CorporateActionIdentityResolver(
        current_rows=[current, {key: old_stock[key] for key in current}],
        history_rows=[old_stock],
    )

    parsed = _parse_action_response(
        [
            {"date": "2020-04-02", "value": "0.25"},
            {"date": "2023-04-02", "value": "0.30"},
        ],
        instrument_row=current,
        action_type="dividend",
        identity_resolver=resolver,
    )

    assert [row["instrument_id"] for row in parsed.accepted] == [1, 2]
    assert parsed.rejected == []

    non_stock_resolver = CorporateActionIdentityResolver(
        current_rows=[current],
        history_rows=[{**old_stock, "asset_type": "etf"}],
    )
    rejected = _parse_action_response(
        [{"date": "2020-04-02", "value": "0.25"}],
        instrument_row=current,
        action_type="dividend",
        identity_resolver=non_stock_resolver,
    )
    assert rejected.accepted == []
    assert "owner is not stock" in rejected.rejected[0].reason


def test_corporate_action_quality_issue_distinguishes_identity_from_bad_payload() -> None:
    unresolved = RejectedCorporateActionRow(
        index=0,
        provider_symbol="OLD.US",
        action_type="dividend",
        reason="unresolved corporate-action owner: ambiguous_dated_provider_symbol_owner",
        row={"date": "2025-01-01", "value": "0.25"},
    )
    non_stock = RejectedCorporateActionRow(
        index=0,
        provider_symbol="OLD.US",
        action_type="split",
        reason="corporate-action owner is not stock: instrument_id=2 asset_type=etf",
        row={"date": "2025-01-01", "split": "2/1"},
    )
    invalid = RejectedCorporateActionRow(
        index=0,
        provider_symbol="BAD.US",
        action_type="split",
        reason="invalid EODHD split ratio: non-positive component",
        row={"date": "2025-01-01", "split": "0/1"},
    )

    assert _issue_type(unresolved) == "corporate_action_identity_unresolved"
    assert _issue_type(non_stock) == "corporate_action_non_stock_owner"
    assert _issue_type(invalid) == "invalid_split"
