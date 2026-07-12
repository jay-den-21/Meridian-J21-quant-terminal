from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from eodhd_codegen_app.client import EodhdExecutionError, ExecutionResult
from eodhd_codegen_app.instrument_catalog import (
    ExchangeDirectoryCache,
    catalog_menu_payload,
    load_eodhd_exchange_directory,
    normalize_eodhd_exchange_rows,
)
from eodhd_codegen_app.universe_db import DatabaseStatus


@dataclass
class FakeCatalogRepository:
    available: bool = True

    def status(self) -> DatabaseStatus:
        return DatabaseStatus(
            configured=self.available,
            available=self.available,
            source="test" if self.available else "none",
            message="ready" if self.available else "database unavailable",
        )

    def menu_facets(self) -> dict[str, list[dict[str, object]]]:
        return {
            "exchanges": [
                {"code": "NASDAQ", "label": "NASDAQ", "count": 3},
                {"code": "INDX", "label": "Index", "count": 2},
            ],
            "asset_types": [
                {"id": "stock", "label": "Stock", "count": 3},
                {"id": "index", "label": "Index", "count": 2},
            ],
        }


class FakeCatalogClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls = 0

    def execute(self, request, *, api_key: str) -> ExecutionResult:
        self.calls += 1
        return ExecutionResult(
            rows=self.rows,
            preview_rows=self.rows,
            source_row_count=len(self.rows),
            returned_row_count=len(self.rows),
            truncated=False,
            requests_made=1,
            status_codes=[200],
        )


def test_catalog_menu_uses_db_facets_without_network_call() -> None:
    payload = catalog_menu_payload(repository=FakeCatalogRepository(), cache=ExchangeDirectoryCache())
    categories = {row["id"]: row for row in payload["categories"]}

    assert payload["eodhd_cache"]["loaded"] is False
    assert payload["exchanges"] == [
        {
            "code": "NASDAQ",
            "label": "NASDAQ",
            "name": "NASDAQ",
            "country": "",
            "currency": "",
            "operating_mic": "",
            "local_count": 3,
            "sources": ["local_db"],
        }
    ]
    assert categories["stock"]["local_count"] == 3
    assert categories["index"]["fixed_exchange"] == "INDX"
    assert payload["index_constituents"]["enabled"] is False


def test_catalog_menu_remains_explicit_when_db_is_unavailable() -> None:
    payload = catalog_menu_payload(repository=FakeCatalogRepository(available=False), cache=ExchangeDirectoryCache())

    assert payload["db"]["available"] is False
    assert payload["exchanges"] == []
    assert {row["fixed_exchange"] for row in payload["categories"] if row["venue_mode"] == "fixed"} == {
        "INDX",
        "FOREX",
        "CC",
        "GBOND",
        "MONEY",
    }


def test_explicit_eodhd_exchange_load_merges_and_then_hits_cache() -> None:
    cache = ExchangeDirectoryCache()
    client = FakeCatalogClient(
        [
            {"Code": "NASDAQ", "Name": "Nasdaq", "Country": "USA", "Currency": "USD"},
            {"Code": "LSE", "Name": "London Exchange", "Country": "UK", "Currency": "GBP"},
        ]
    )
    repo = FakeCatalogRepository()

    first = load_eodhd_exchange_directory(
        api_key="secret-token",
        client=client,
        repository=repo,
        cache=cache,
    )
    second = load_eodhd_exchange_directory(
        api_key="secret-token",
        client=client,
        repository=repo,
        cache=cache,
    )
    exchanges = {row["code"]: row for row in first["exchanges"]}

    assert client.calls == 1
    assert first["api_calls"] == 1
    assert first["cache_hit"] is False
    assert second["api_calls"] == 0
    assert second["cache_hit"] is True
    assert exchanges["NASDAQ"]["sources"] == ["local_db", "eodhd"]
    assert exchanges["NASDAQ"]["local_count"] == 3
    assert exchanges["LSE"]["sources"] == ["eodhd"]


def test_exchange_normalization_drops_invalid_rows_and_requires_token() -> None:
    assert normalize_eodhd_exchange_rows(
        [{"Code": " lse ", "Name": "London"}, {"Code": "BAD!", "Name": "Bad"}]
    ) == [
        {
            "code": "LSE",
            "label": "London",
            "name": "London",
            "country": "",
            "currency": "",
            "operating_mic": "",
            "local_count": 0,
            "sources": ["eodhd"],
        }
    ]

    with pytest.raises(EodhdExecutionError, match="Login / Config"):
        load_eodhd_exchange_directory(
            api_key="",
            client=FakeCatalogClient([]),
            repository=FakeCatalogRepository(),
            cache=ExchangeDirectoryCache(),
        )
