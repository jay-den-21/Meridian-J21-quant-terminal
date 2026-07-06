import pytest

from fdp.config import (
    DEFAULT_EODHD_DAILY_CALL_BUDGET,
    DEFAULT_EODHD_DAILY_RANGE_MAX_WORKERS,
    DEFAULT_EODHD_MAX_REQUESTS_PER_MINUTE,
    DEFAULT_EODHD_MAX_RETRIES,
    DEFAULT_EODHD_RETRY_DELAY_SECONDS,
    EodhdRuntimeConfig,
    eodhd_runtime_config_from_env,
)

EODHD_RUNTIME_ENV_VARS = [
    "EODHD_MAX_RETRIES",
    "EODHD_RETRY_DELAY_SECONDS",
    "EODHD_MAX_REQUESTS_PER_MINUTE",
    "EODHD_DAILY_CALL_BUDGET",
    "EODHD_DAILY_RANGE_PARALLEL",
    "EODHD_DAILY_RANGE_MAX_WORKERS",
]


@pytest.fixture(autouse=True)
def clear_eodhd_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in EODHD_RUNTIME_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_eodhd_runtime_config_uses_yaml_defaults() -> None:
    config = eodhd_runtime_config_from_env()

    assert config == EodhdRuntimeConfig(
        max_retries=DEFAULT_EODHD_MAX_RETRIES,
        retry_delay_seconds=DEFAULT_EODHD_RETRY_DELAY_SECONDS,
        max_requests_per_minute=DEFAULT_EODHD_MAX_REQUESTS_PER_MINUTE,
        daily_call_budget=DEFAULT_EODHD_DAILY_CALL_BUDGET,
        daily_range_parallel_enabled=False,
        daily_range_max_workers=DEFAULT_EODHD_DAILY_RANGE_MAX_WORKERS,
    )


def test_eodhd_runtime_config_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EODHD_MAX_RETRIES", "2")
    monkeypatch.setenv("EODHD_RETRY_DELAY_SECONDS", "12")
    monkeypatch.setenv("EODHD_MAX_REQUESTS_PER_MINUTE", "50")
    monkeypatch.setenv("EODHD_DAILY_CALL_BUDGET", "900")
    monkeypatch.setenv("EODHD_DAILY_RANGE_PARALLEL", "true")
    monkeypatch.setenv("EODHD_DAILY_RANGE_MAX_WORKERS", "3")

    config = eodhd_runtime_config_from_env()

    assert config == EodhdRuntimeConfig(
        max_retries=2,
        retry_delay_seconds=12,
        max_requests_per_minute=50,
        daily_call_budget=900,
        daily_range_parallel_enabled=True,
        daily_range_max_workers=3,
    )


def test_eodhd_runtime_config_rejects_rate_above_official_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EODHD_MAX_REQUESTS_PER_MINUTE", "1001")

    with pytest.raises(ValueError, match="official limit 1000"):
        eodhd_runtime_config_from_env()
