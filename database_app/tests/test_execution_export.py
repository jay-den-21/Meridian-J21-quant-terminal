from __future__ import annotations

from datetime import datetime, timezone

from eodhd_codegen_app.execution_export import (
    ExecutionExportStore,
    ExportSnapshot,
    csv_bytes,
    export_filename,
)
from eodhd_codegen_app.request_model import validate_payload


def test_export_store_replaces_previous_snapshot_and_rejects_unknown_ids() -> None:
    store = ExecutionExportStore()
    request = validate_payload(
        {
            "asset": "instrument",
            "endpoint": "exchange_symbol_list",
            "params": {
                "catalog_asset": "index",
                "exchange": "INDX",
                "type_filter": "all",
            },
        }
    )

    first = store.replace(request, [{"Code": "GSPC"}])
    second = store.replace(request, [{"Code": "DJI"}])

    assert store.get(first.export_id) is None
    assert store.get(second.export_id) == second
    assert store.get("not-valid") is None


def test_csv_export_is_full_utf8_and_formula_safe() -> None:
    snapshot = ExportSnapshot(
        export_id="safe-export-id-value-123",
        endpoint="exchange_symbol_list",
        exchange="NASDAQ",
        created_at=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        rows=(
            {"Code": "SAFE", "Name": "Normal", " =header": "value"},
            {"Code": "DANGER", "Name": "=HYPERLINK(\"https://bad\")"},
            {"Code": "UNICODE", "Name": " \t+SUM(1,1) Shanghai 测试"},
        ),
    )

    text = csv_bytes(snapshot).decode("utf-8")

    assert text.startswith("\ufeff")
    assert "'=HYPERLINK" in text
    assert "' =header" in text
    assert "' \t+SUM" in text
    assert "Shanghai 测试" in text
    assert text.count("\n") == 4
    assert export_filename(snapshot) == "eodhd_exchange_symbol_list_NASDAQ_20260713T120000Z.csv"
