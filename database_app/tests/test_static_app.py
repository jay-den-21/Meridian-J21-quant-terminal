from __future__ import annotations

from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "src" / "eodhd_codegen_app" / "static" / "app.js"


def _app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_pool_load_uses_sequence_guard_against_stale_responses() -> None:
    script = _app_js()

    assert "poolLoadSeq" in script
    assert "const loadSeq = ++state.poolLoadSeq;" in script
    assert "if (loadSeq !== state.poolLoadSeq)" in script


def test_pool_exchange_is_derived_from_pool_state_not_stale_params() -> None:
    script = _app_js()
    function_body = script.split("function draftRequestExchange", 1)[1].split("function buildPayloadFromDraft", 1)[0]

    assert "draft?.params?.exchange" not in function_body
    assert "syncDraftExchangeFromPool" in script
    assert "state.draft.params.exchange = draftRequestExchange();" in script


def test_advanced_filter_can_leave_preset_mode_explicitly() -> None:
    script = _app_js()

    assert "advanced.usePreset = document.getElementById(\"adv_use_preset\").checked;" in script
    assert "} else if (advanced.exchange) {" in script
    assert "state.draft.pool.source = \"asset_type\";" in script


def test_csv_export_defers_object_url_revocation() -> None:
    script = _app_js()

    assert "function buildCsvText(rows)" in script
    assert "function downloadCsvText(csvText)" in script
    assert "window.setTimeout(() => {" in script
    assert "URL.revokeObjectURL(objectUrl);" in script


def test_import_tickers_resolves_against_database_instead_of_regex_only() -> None:
    script = _app_js()
    import_body = script.split("async function addImportedSymbols", 1)[1].split("function extractSymbolTokens", 1)[0]

    assert 'postJson("/api/universe/resolve", { tokens })' in import_body
    assert "providerSymbolFromToken(token" not in import_body
    assert "normalizeResolvedRow" in import_body


def test_result_preview_prioritizes_request_symbol_column() -> None:
    script = _app_js()

    assert 'const priority = ["_provider_symbol", "provider_symbol", "code", "symbol", "datetime", "date"];' in script
    assert 'return column === "_provider_symbol" ? "request_symbol" : column;' in script
    assert "chips.push(`symbols: ${compactSymbolList(selected)}`);" in script
