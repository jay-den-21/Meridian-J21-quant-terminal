from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote_plus


DEFAULT_MARKET = "US"
DEFAULT_PROVIDER = "EODHD"
DEFAULT_SCHEMA = "us_share"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / "database_system_cli" / ".env"
MAJOR_US_EXCHANGES = ("NYSE", "NASDAQ", "AMEX", "ARCA", "NYSE ARCA", "BATS")
OTC_EXCHANGES = (
    "OTC",
    "OTCBB",
    "OTCCE",
    "OTCGREY",
    "OTCMKTS",
    "OTCPK",
    "OTCQB",
    "OTCQX",
    "PINK",
    "PINX",
)
MAX_UNIVERSE_ROWS = 2000
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class DatabaseStatus:
    configured: bool
    available: bool
    source: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "available": self.available,
            "source": self.source,
            "message": self.message,
        }


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    source: str


@dataclass(frozen=True)
class PoolQuery:
    source: str
    label: str
    market: str = DEFAULT_MARKET
    provider: str = DEFAULT_PROVIDER
    active_only: bool = True
    exchanges: tuple[str, ...] = ()
    asset_types: tuple[str, ...] = ()
    exclude_otc: bool = False
    text_search: str = ""
    limit: int = MAX_UNIVERSE_ROWS


class DbUniverseRepository:
    """Read-only universe access against the existing `us_share.instrument` table."""

    def __init__(
        self,
        *,
        config: DatabaseConfig | None = None,
        env: Mapping[str, str] | None = None,
        env_file: Path = DEFAULT_ENV_FILE,
        schema: str = DEFAULT_SCHEMA,
    ) -> None:
        self._config = config
        self._env = env
        self._env_file = env_file
        self._schema = _safe_identifier(schema, "schema")

    @classmethod
    def from_environment(cls) -> "DbUniverseRepository":
        return cls()

    def status(self) -> DatabaseStatus:
        config = self._resolve_config()
        if config is None:
            return DatabaseStatus(
                configured=False,
                available=False,
                source="none",
                message=(
                    "Database pool source is not configured. Set FDP_DATABASE_URL or FDP_DB_* "
                    "in the process environment or database_system_cli/.env."
                ),
            )
        try:
            with self._engine(config).connect() as connection:
                connection.execute(
                    _sql_text(
                        f"""
                        SELECT provider_symbol, symbol, name, exchange, asset_type, is_active, market, provider
                        FROM {self._schema}.instrument
                        LIMIT 1
                        """
                    )
                )
        except ModuleNotFoundError:
            return DatabaseStatus(
                configured=True,
                available=False,
                source=config.source,
                message="SQLAlchemy/PyMySQL is not installed for the database pool source.",
            )
        except Exception:
            return DatabaseStatus(
                configured=True,
                available=False,
                source=config.source,
                message=(
                    "Database instrument table could not be read. Check FDP_DATABASE_URL or "
                    "FDP_DB_* and the us_share.instrument schema."
                ),
            )
        return DatabaseStatus(
            configured=True,
            available=True,
            source=config.source,
            message="Database pool source is ready.",
        )

    def menu_facets(self) -> dict[str, list[dict[str, object]]]:
        config = self._resolve_config()
        if config is None:
            return {"exchanges": [], "asset_types": []}
        try:
            with self._engine(config).connect() as connection:
                exchanges = [
                    {
                        "code": str(row["exchange"]),
                        "label": str(row["exchange"]),
                        "count": int(row["row_count"]),
                    }
                    for row in connection.execute(
                        _sql_text(
                            f"""
                            SELECT exchange, COUNT(*) AS row_count
                            FROM {self._schema}.instrument
                            WHERE market = :market
                              AND provider = :provider
                              AND is_active = 1
                              AND exchange <> ''
                            GROUP BY exchange
                            ORDER BY exchange
                            """
                        ),
                        {"market": DEFAULT_MARKET, "provider": DEFAULT_PROVIDER},
                    ).mappings()
                ]
                asset_types = [
                    {
                        "id": str(row["asset_type"]),
                        "label": str(row["asset_type"]).replace("_", " ").title(),
                        "count": int(row["row_count"]),
                    }
                    for row in connection.execute(
                        _sql_text(
                            f"""
                            SELECT asset_type, COUNT(*) AS row_count
                            FROM {self._schema}.instrument
                            WHERE market = :market
                              AND provider = :provider
                              AND is_active = 1
                              AND asset_type <> ''
                            GROUP BY asset_type
                            ORDER BY asset_type
                            """
                        ),
                        {"market": DEFAULT_MARKET, "provider": DEFAULT_PROVIDER},
                    ).mappings()
                ]
        except Exception:
            return {"exchanges": [], "asset_types": []}
        return {"exchanges": exchanges, "asset_types": asset_types}

    def load_rows(self, query: PoolQuery) -> list[dict[str, str]]:
        config = self._resolve_config()
        if config is None:
            return []
        statement, params = _build_rows_statement(query, schema=self._schema)
        with self._engine(config).connect() as connection:
            rows = connection.execute(statement, params).mappings().all()
        return [_row_as_dict(row, source=query.source) for row in rows]

    def resolve_symbols(self, tokens: tuple[str, ...], *, market: str = DEFAULT_MARKET) -> list[dict[str, str]]:
        config = self._resolve_config()
        if config is None or not tokens:
            return []
        statement, params = _build_resolve_statement(tokens, schema=self._schema, market=market)
        with self._engine(config).connect() as connection:
            rows = connection.execute(statement, params).mappings().all()
        return [_row_as_dict(row, source="db_import") for row in rows]

    def _resolve_config(self) -> DatabaseConfig | None:
        if self._config is not None:
            return self._config
        return database_config_from_environment(env=self._env, env_file=self._env_file)

    def _engine(self, config: DatabaseConfig) -> Any:
        from sqlalchemy import create_engine

        kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if config.url.startswith("mysql"):
            kwargs["connect_args"] = {"connect_timeout": 2}
        return create_engine(config.url, **kwargs)


def database_config_from_environment(
    *,
    env: Mapping[str, str] | None = None,
    env_file: Path = DEFAULT_ENV_FILE,
) -> DatabaseConfig | None:
    process_env = env if env is not None else os.environ
    file_env = read_env_file(env_file)

    explicit_url, source = _first_config_value("FDP_DATABASE_URL", process_env, file_env)
    if explicit_url:
        return DatabaseConfig(url=explicit_url, source=source)

    required_values: dict[str, str] = {}
    source = "none"
    for key in ("FDP_DB_HOST", "FDP_DB_USER", "FDP_DB_PASSWORD", "FDP_DB_NAME"):
        value, value_source = _first_config_value(key, process_env, file_env)
        if not value:
            return None
        required_values[key] = value
        if source == "none":
            source = value_source

    driver, driver_source = _first_config_value("FDP_DB_DRIVER", process_env, file_env, default="mysql+pymysql")
    port, port_source = _first_config_value("FDP_DB_PORT", process_env, file_env, default="3306")
    if source == "none":
        source = driver_source if driver_source != "default" else port_source

    user = quote_plus(required_values["FDP_DB_USER"])
    password = quote_plus(required_values["FDP_DB_PASSWORD"])
    host = required_values["FDP_DB_HOST"]
    database = required_values["FDP_DB_NAME"]
    return DatabaseConfig(
        url=f"{driver}://{user}:{password}@{host}:{port}/{database}",
        source=source,
    )


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _first_config_value(
    key: str,
    process_env: Mapping[str, str],
    file_env: Mapping[str, str],
    *,
    default: str = "",
) -> tuple[str, str]:
    process_value = str(process_env.get(key, "")).strip()
    if process_value:
        return process_value, "environment"
    file_value = str(file_env.get(key, "")).strip()
    if file_value:
        return file_value, "database_system_cli/.env"
    return default, "default" if default else "none"


def _build_rows_statement(query: PoolQuery, *, schema: str) -> tuple[Any, dict[str, Any]]:
    from sqlalchemy import bindparam

    clauses = ["market = :market", "provider = :provider"]
    params: dict[str, Any] = {
        "market": query.market,
        "provider": query.provider,
        "limit": min(max(int(query.limit), 1), MAX_UNIVERSE_ROWS),
    }
    expanding_params: list[str] = []

    if query.active_only:
        clauses.append("is_active = 1")
    if query.exchanges:
        clauses.append("exchange IN :exchanges")
        params["exchanges"] = tuple(_clean_token(item) for item in query.exchanges if _clean_token(item))
        expanding_params.append("exchanges")
    if query.asset_types:
        clauses.append("asset_type IN :asset_types")
        params["asset_types"] = tuple(_clean_token(item).lower() for item in query.asset_types if _clean_token(item))
        expanding_params.append("asset_types")
    if query.exclude_otc:
        clauses.append("exchange NOT IN :otc_exchanges")
        params["otc_exchanges"] = OTC_EXCHANGES
        expanding_params.append("otc_exchanges")
    if query.text_search:
        clauses.append("(provider_symbol LIKE :text_search OR symbol LIKE :text_search OR name LIKE :text_search)")
        params["text_search"] = f"%{query.text_search}%"

    statement = _sql_text(
        f"""
        SELECT provider_symbol, symbol, name, exchange, asset_type
        FROM {schema}.instrument
        WHERE {" AND ".join(clauses)}
        ORDER BY asset_type, exchange, provider_symbol
        LIMIT :limit
        """
    )
    for name in expanding_params:
        statement = statement.bindparams(bindparam(name, expanding=True))
    return statement, params


def _build_resolve_statement(tokens: tuple[str, ...], *, schema: str, market: str) -> tuple[Any, dict[str, Any]]:
    from sqlalchemy import bindparam

    clean_tokens = tuple(sorted({_clean_match_token(token).lower() for token in tokens if _clean_match_token(token)}))
    statement = _sql_text(
        f"""
        SELECT provider_symbol, symbol, name, exchange, asset_type
        FROM {schema}.instrument
        WHERE market = :market
          AND provider = :provider
          AND is_active = 1
          AND (LOWER(symbol) IN :tokens OR LOWER(provider_symbol) IN :tokens)
        ORDER BY provider_symbol
        LIMIT :limit
        """
    ).bindparams(bindparam("tokens", expanding=True))
    return statement, {
        "market": market,
        "provider": DEFAULT_PROVIDER,
        "tokens": clean_tokens,
        "limit": min(len(clean_tokens), MAX_UNIVERSE_ROWS),
    }


def _row_as_dict(row: Mapping[str, Any], *, source: str) -> dict[str, str]:
    return {
        "provider_symbol": str(row.get("provider_symbol") or "").upper(),
        "symbol": str(row.get("symbol") or "").upper(),
        "name": str(row.get("name") or ""),
        "exchange": str(row.get("exchange") or "").upper(),
        "type": str(row.get("asset_type") or "").lower(),
        "source": source,
    }


def _sql_text(statement: str) -> Any:
    from sqlalchemy import text

    return text(statement)


def _safe_identifier(value: str, name: str) -> str:
    if not SAFE_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"invalid database {name}")
    return value


def _clean_token(value: object) -> str:
    return str(value or "").strip().upper()


def _clean_match_token(value: object) -> str:
    return str(value or "").strip()
