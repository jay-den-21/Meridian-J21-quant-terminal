import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from dotenv import load_dotenv
import yaml


MAX_EODHD_RETRIES = 3
DEFAULT_EODHD_MAX_RETRIES = MAX_EODHD_RETRIES
DEFAULT_EODHD_RETRY_DELAY_SECONDS = 61
EODHD_OFFICIAL_MAX_REQUESTS_PER_MINUTE = 1_000
DEFAULT_EODHD_MAX_REQUESTS_PER_MINUTE = 600
DEFAULT_EODHD_DAILY_CALL_BUDGET = 100_000
DEFAULT_EODHD_DAILY_RANGE_PARALLEL_ENABLED = False
DEFAULT_EODHD_DAILY_RANGE_MAX_WORKERS = 4


@dataclass(frozen=True)
class EodhdRuntimeConfig:
    """Runtime controls for EODHD HTTP usage.

    Input: YAML defaults plus optional environment overrides.
    Output: typed retry, throttling, and daily-range parallel settings.
    Flow: `config/default.yaml` -> env overrides -> CLI/client settings.
    """

    max_retries: int = DEFAULT_EODHD_MAX_RETRIES
    retry_delay_seconds: int = DEFAULT_EODHD_RETRY_DELAY_SECONDS
    max_requests_per_minute: int = DEFAULT_EODHD_MAX_REQUESTS_PER_MINUTE
    daily_call_budget: int = DEFAULT_EODHD_DAILY_CALL_BUDGET
    daily_range_parallel_enabled: bool = DEFAULT_EODHD_DAILY_RANGE_PARALLEL_ENABLED
    daily_range_max_workers: int = DEFAULT_EODHD_DAILY_RANGE_MAX_WORKERS


def load_environment() -> None:
    load_dotenv()


def eodhd_api_key_from_env() -> str:
    load_environment()
    api_key = os.getenv("EODHD_API_KEY")
    if not api_key:
        raise ValueError("EODHD_API_KEY is required")
    return api_key


def database_url_from_env() -> str:
    load_environment()
    explicit_url = os.getenv("FDP_DATABASE_URL")
    if explicit_url:
        return explicit_url

    driver = os.getenv("FDP_DB_DRIVER", "mysql+pymysql")
    host = _required_env("FDP_DB_HOST")
    port = os.getenv("FDP_DB_PORT", "3306")
    user = quote_plus(_required_env("FDP_DB_USER"))
    password = quote_plus(_required_env("FDP_DB_PASSWORD"))
    database = _required_env("FDP_DB_NAME")
    return f"{driver}://{user}:{password}@{host}:{port}/{database}"


def intraday_data_root_from_env() -> Path:
    """Return the explicitly configured intraday data root without creating it."""
    load_environment()
    raw_value = os.getenv("J21_INTRADAY_DATA_ROOT", "").strip()
    if not raw_value:
        raise ValueError("J21_INTRADAY_DATA_ROOT is required for intraday storage")
    return Path(raw_value).expanduser()


def eodhd_runtime_config_from_env() -> EodhdRuntimeConfig:
    """Load EODHD runtime settings from YAML defaults and environment overrides."""
    load_environment()
    yaml_config = _load_default_config()
    eodhd_config = _nested_mapping(yaml_config, "sources", "eodhd")
    parallel_config = _nested_mapping(eodhd_config, "daily_range_parallel")

    config = EodhdRuntimeConfig(
        max_retries=_env_int(
            "EODHD_MAX_RETRIES",
            default=_mapping_int(eodhd_config, "max_retries", DEFAULT_EODHD_MAX_RETRIES),
        ),
        retry_delay_seconds=_env_int(
            "EODHD_RETRY_DELAY_SECONDS",
            default=_mapping_int(
                eodhd_config,
                "retry_delay_seconds",
                DEFAULT_EODHD_RETRY_DELAY_SECONDS,
            ),
        ),
        max_requests_per_minute=_env_int(
            "EODHD_MAX_REQUESTS_PER_MINUTE",
            default=_mapping_int(
                eodhd_config,
                "max_requests_per_minute",
                DEFAULT_EODHD_MAX_REQUESTS_PER_MINUTE,
            ),
        ),
        daily_call_budget=_env_int(
            "EODHD_DAILY_CALL_BUDGET",
            default=_mapping_int(
                eodhd_config,
                "daily_call_budget",
                DEFAULT_EODHD_DAILY_CALL_BUDGET,
            ),
        ),
        daily_range_parallel_enabled=_env_bool(
            "EODHD_DAILY_RANGE_PARALLEL",
            default=_mapping_bool(
                parallel_config,
                "enabled",
                DEFAULT_EODHD_DAILY_RANGE_PARALLEL_ENABLED,
            ),
        ),
        daily_range_max_workers=_env_int(
            "EODHD_DAILY_RANGE_MAX_WORKERS",
            default=_mapping_int(
                parallel_config,
                "max_workers",
                DEFAULT_EODHD_DAILY_RANGE_MAX_WORKERS,
            ),
        ),
    )
    _validate_eodhd_runtime_config(config)
    return config


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _load_default_config() -> dict[str, Any]:
    config_path = Path(__file__).resolve().parents[2] / "config" / "default.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError("config/default.yaml must contain a YAML mapping")
    return loaded


def _nested_mapping(mapping: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _mapping_int(mapping: dict[str, Any], key: str, default: int) -> int:
    value = mapping.get(key)
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"config value {key} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"config value {key} must be positive")
    return parsed


def _mapping_bool(mapping: dict[str, Any], key: str, default: bool) -> bool:
    value = mapping.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _parse_bool(value, name=f"config value {key}")
    raise ValueError(f"config value {key} must be a boolean")


def _env_int(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return _parse_bool(value, name=name)


def _parse_bool(value: str, *, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _validate_eodhd_runtime_config(config: EodhdRuntimeConfig) -> None:
    if not 0 <= config.max_retries <= MAX_EODHD_RETRIES:
        raise ValueError(
            f"EODHD max_retries must be between 0 and {MAX_EODHD_RETRIES}"
        )
    if config.max_requests_per_minute > EODHD_OFFICIAL_MAX_REQUESTS_PER_MINUTE:
        raise ValueError(
            "EODHD max_requests_per_minute must be less than or equal to "
            f"the official limit {EODHD_OFFICIAL_MAX_REQUESTS_PER_MINUTE}"
        )
