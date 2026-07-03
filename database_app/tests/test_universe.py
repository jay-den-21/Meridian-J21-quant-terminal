from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from eodhd_codegen_app.universe import build_pool_query, load_universe, menu_payload, resolve_universe_symbols
from eodhd_codegen_app.universe_db import DatabaseStatus, PoolQuery


@dataclass
class FakeUniverseRepository:
    status_value: DatabaseStatus
    rows: list[dict[str, str]] | None = None
    fail_load: bool = False
    last_query: PoolQuery | None = None
    last_resolve_tokens: tuple[str, ...] = ()

    def status(self) -> DatabaseStatus:
        return self.status_value

    def menu_facets(self) -> dict[str, list[dict[str, object]]]:
        return {
            "exchanges": [{"code": "NASDAQ", "label": "NASDAQ", "count": 2}],
            "asset_types": [{"id": "stock", "label": "Stock", "count": 2}],
        }

    def load_rows(self, query: PoolQuery) -> list[dict[str, str]]:
        self.last_query = query
        if self.fail_load:
            raise RuntimeError("database password leaked in raw exception")
        return self.rows or []

    def resolve_symbols(self, tokens: tuple[str, ...], *, market: str = "US") -> list[dict[str, str]]:
        self.last_resolve_tokens = tokens
        return [
            row
            for row in self.rows or []
            if row["symbol"].lower() in {token.lower() for token in tokens}
            or row["provider_symbol"].lower() in {token.lower() for token in tokens}
        ]


def test_menu_payload_marks_index_assets_and_sectors_boundaries() -> None:
    payload = menu_payload(repository=_available_repo())

    categories = {item["id"]: item for item in payload["categories"]}
    assert categories["index_assets"]["enabled"] is True
    assert "not index constituent" in categories["index_assets"]["help_text"].lower()
    assert categories["sectors"]["enabled"] is False
    assert "taxonomy" in categories["sectors"]["disabled_reason"].lower()
    assert payload["exchanges"][0]["code"] == "NASDAQ"


def test_menu_payload_reports_missing_db_without_secret() -> None:
    status = DatabaseStatus(
        configured=True,
        available=False,
        source="database_system_cli/.env",
        message="Database connection failed. Check FDP_DATABASE_URL or FDP_DB_*.",
    )

    payload = menu_payload(repository=FakeUniverseRepository(status))

    assert payload["db"]["available"] is False
    assert "password" not in str(payload).lower()
    assert "secret" not in str(payload).lower()
    assert payload["categories"][0]["enabled"] is False


def test_load_universe_returns_explicit_unavailable_payload_without_api_key() -> None:
    status = DatabaseStatus(
        configured=False,
        available=False,
        source="none",
        message="Database pool source is not configured.",
    )

    payload = load_universe({"source": "preset"}, repository=FakeUniverseRepository(status))

    assert payload["unavailable"] is True
    assert payload["rows"] == []
    assert payload["db"]["available"] is False


def test_load_universe_returns_secret_safe_unavailable_when_query_fails() -> None:
    repo = _available_repo()
    repo.fail_load = True

    payload = load_universe({"source": "preset", "preset": "us_major_common"}, repository=repo)

    assert payload["unavailable"] is True
    assert payload["rows"] == []
    assert payload["db"]["available"] is False
    assert "password" not in str(payload).lower()


def test_resolve_universe_symbols_uses_database_exact_matches_case_insensitive() -> None:
    repo = _available_repo(
        rows=[
            {
                "provider_symbol": "AAPL.US",
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "exchange": "NASDAQ",
                "type": "stock",
                "source": "db_import",
            },
            {
                "provider_symbol": "BRK-B.US",
                "symbol": "BRK-B",
                "name": "Berkshire Hathaway Inc.",
                "exchange": "NYSE",
                "type": "stock",
                "source": "db_import",
            },
        ]
    )

    payload = resolve_universe_symbols({"tokens": ["aapl", "FUCK", "BRK.B", "bad!"]}, repository=repo)

    resolved = payload["resolved"]
    assert [item["input"] for item in resolved] == ["AAPL"]
    assert [item["row"]["provider_symbol"] for item in resolved] == ["AAPL.US"]
    assert payload["unmatched"] == ["FUCK", "BRK.B"]
    assert payload["invalid"] == ["BAD!"]
    assert "BRK-B.US" not in repo.last_resolve_tokens
    assert "BRK.B" in repo.last_resolve_tokens


def test_resolve_universe_symbols_reports_unavailable_without_fallback() -> None:
    repo = FakeUniverseRepository(
        DatabaseStatus(
            configured=False,
            available=False,
            source="none",
            message="Database pool source is not configured.",
        )
    )

    payload = resolve_universe_symbols({"tokens": ["AAPL", "FUCK"]}, repository=repo)

    assert payload["unavailable"] is True
    assert payload["resolved"] == []
    assert payload["unmatched"] == ["AAPL", "FUCK"]


def test_load_default_major_pool_uses_database_rows() -> None:
    repo = _available_repo(
        rows=[
            {
                "provider_symbol": "AAPL.US",
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "exchange": "NASDAQ",
                "type": "stock",
                "source": "db_preset",
            }
        ]
    )

    payload = load_universe({"source": "preset", "preset": "us_major_common"}, repository=repo)

    assert payload["unavailable"] is False
    assert payload["rows"][0]["provider_symbol"] == "AAPL.US"
    assert repo.last_query is not None
    assert repo.last_query.source == "db_preset"
    assert repo.last_query.asset_types == ("stock",)
    assert repo.last_query.exchanges == ("NYSE", "NASDAQ", "AMEX", "ARCA", "NYSE ARCA", "BATS")
    assert repo.last_query.exclude_otc is True


def test_build_exchange_pool_query() -> None:
    query = build_pool_query({"source": "exchange", "exchange": "NASDAQ", "asset_type": "stock"})

    assert query.source == "db_exchange"
    assert query.exchanges == ("NASDAQ",)
    assert query.asset_types == ("stock",)
    assert query.limit == 2000


def test_build_asset_type_pool_query() -> None:
    query = build_pool_query({"source": "asset_type", "asset_type": "etf"})

    assert query.source == "db_asset_type"
    assert query.asset_types == ("etf",)
    assert query.exchanges == ()


def test_build_index_asset_query_is_not_constituents() -> None:
    query = build_pool_query(
        {
            "source": "index_assets",
            "filters": {
                "asset_type": "stock",
                "exchange": "NASDAQ",
            },
        }
    )

    assert query.source == "db_index_assets"
    assert query.asset_types == ("index",)
    assert query.exchanges == ()


def test_sector_pool_is_explicitly_rejected() -> None:
    with pytest.raises(ValueError, match="not configured"):
        build_pool_query({"source": "sectors"})


def test_advanced_filters_apply_to_db_query() -> None:
    query = build_pool_query(
        {
            "source": "preset",
            "preset": "us_active_stocks",
            "filters": {
                "active_only": False,
                "exclude_otc": True,
                "exchange": "NYSE",
                "asset_type": "etf",
                "text_search": "SPY",
            },
        }
    )

    assert query.active_only is False
    assert query.exclude_otc is True
    assert query.exchanges == ("NYSE",)
    assert query.asset_types == ("etf",)
    assert query.text_search == "SPY"


def _available_repo(rows: list[dict[str, Any]] | None = None) -> FakeUniverseRepository:
    return FakeUniverseRepository(
        DatabaseStatus(
            configured=True,
            available=True,
            source="database_system_cli/.env",
            message="Database pool source is ready.",
        ),
        rows=rows or [],
    )
