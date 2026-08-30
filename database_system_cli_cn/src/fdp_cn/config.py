"""Lazy, secret-safe configuration for the CN CLI."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from sqlalchemy.engine import URL, make_url
import yaml


PRODUCT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PRODUCT_ROOT / "config" / "ts2db_config.yaml"
DEFAULT_TUSHARE_MAX_RETRIES = 3
DEFAULT_TUSHARE_RETRY_DELAY_SECONDS = 61


@dataclass(frozen=True)
class TushareRuntimeConfig:
    max_retries: int = DEFAULT_TUSHARE_MAX_RETRIES
    retry_delay_seconds: int = DEFAULT_TUSHARE_RETRY_DELAY_SECONDS


def database_url_from_env() -> URL:
    """Return the configured a_share URL without interpolating credentials."""
    explicit = os.getenv("FDP_CN_DATABASE_URL")
    if explicit:
        url = make_url(explicit)
    else:
        config = _load_config()
        raw = _mapping(config, "db_config")
        url = URL.create(
            "mysql+pymysql",
            username=_required_text(raw, "user"),
            password=_required_password(raw, "pwd"),
            host=_required_text(raw, "host"),
            port=_positive_int(raw.get("port"), name="db_config.port"),
            database=_required_text(raw, "db"),
        )
    if url.database != "a_share":
        raise ValueError("J21 database only writes the a_share database")
    return url


def tushare_token_from_env() -> str:
    """Read the token only when a live direct client is constructed."""
    explicit = os.getenv("TUSHARE_TOKEN")
    if explicit:
        return explicit
    config = _load_config()
    servers = config.get("server_config")
    if not isinstance(servers, list):
        raise ValueError("server_config must be a list")
    for value in servers:
        if isinstance(value, dict) and value.get("server") == "ts":
            return _required_text(value, "token")
    raise ValueError("Tushare token is missing from TUSHARE_TOKEN or server_config")


def tushare_runtime_config_from_env() -> TushareRuntimeConfig:
    retry_override = os.getenv("TUSHARE_MAX_RETRIES")
    delay_override = os.getenv("TUSHARE_RETRY_DELAY_SECONDS")
    if retry_override is not None and delay_override is not None:
        run: dict[str, Any] = {}
    elif DEFAULT_CONFIG_PATH.is_file():
        config = _load_config()
        raw_run = config.get("run_config", {})
        if not isinstance(raw_run, dict):
            raise ValueError("run_config must be a mapping")
        run = raw_run
    else:
        run = {}
    return TushareRuntimeConfig(
        max_retries=_nonnegative_int(
            retry_override if retry_override is not None else run.get("retry_times"),
            default=DEFAULT_TUSHARE_MAX_RETRIES,
            name="TUSHARE_MAX_RETRIES",
        ),
        retry_delay_seconds=_nonnegative_int(
            delay_override
            if delay_override is not None
            else run.get("retry_sleep_time"),
            default=DEFAULT_TUSHARE_RETRY_DELAY_SECONDS,
            name="TUSHARE_RETRY_DELAY_SECONDS",
        ),
    )


def _load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"private configuration is missing: {path}") from error
    except yaml.YAMLError as error:
        raise ValueError("private configuration is not valid YAML") from error
    if not isinstance(value, dict):
        raise ValueError("private configuration must be a YAML mapping")
    return value


def _mapping(value: dict[str, Any], name: str) -> dict[str, Any]:
    nested = value.get(name)
    if not isinstance(nested, dict):
        raise ValueError(f"{name} must be a mapping")
    return nested


def _required_text(value: dict[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{name} must be non-empty text")
    return item.strip()


def _required_password(value: dict[str, Any], name: str) -> str:
    """Accept quoted or numeric YAML passwords without logging either form."""
    item = value.get(name)
    if isinstance(item, bool) or item is None:
        raise ValueError(f"{name} must be non-empty text or an integer")
    if isinstance(item, int):
        return str(item)
    if isinstance(item, str) and item:
        return item
    raise ValueError(f"{name} must be non-empty text or an integer")


def _positive_int(value: object, *, name: str) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _nonnegative_int(value: object, *, default: int, name: str) -> int:
    if value in {None, ""}:
        return default
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if parsed < 0:
        raise ValueError(f"{name} must be zero or greater")
    return parsed
