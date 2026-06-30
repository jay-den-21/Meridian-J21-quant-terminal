from __future__ import annotations

from eodhd_codegen_app.endpoints import INVENTORY_ONLY_ENDPOINTS, SUPPORTED_ENDPOINTS, endpoint_payload


def test_supported_endpoints_have_docs_and_subscription_evidence() -> None:
    assert len(SUPPORTED_ENDPOINTS) >= 10

    for spec in SUPPORTED_ENDPOINTS.values():
        assert spec.implemented is True
        assert spec.official_doc_url.startswith("https://eodhd.com/")
        assert spec.plan_evidence
        assert spec.call_cost_note
        assert spec.default_format in spec.formats


def test_inventory_only_endpoints_are_not_executable() -> None:
    assert "fundamentals" in INVENTORY_ONLY_ENDPOINTS
    assert "calendar_news" in INVENTORY_ONLY_ENDPOINTS

    for spec in INVENTORY_ONLY_ENDPOINTS.values():
        assert spec.implemented is False
        assert spec.implementation_note


def test_endpoint_payload_contains_parameter_specs_for_frontend_renderer() -> None:
    payload = endpoint_payload()
    historical = next(item for item in payload if item["id"] == "historical_eod")
    param_names = {param["name"] for param in historical["params"]}

    assert {"symbols", "date_from", "date_to", "period", "order"}.issubset(param_names)
    assert historical["formats"] == ["json", "csv"]
