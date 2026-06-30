from __future__ import annotations

from pathlib import Path

from eodhd_codegen_app.universe_db import (
    DatabaseStatus,
    database_config_from_environment,
    read_env_file,
)


def test_read_env_file_parses_quotes_and_ignores_comments(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # comment
        FDP_DB_HOST="localhost"
        FDP_DB_USER='research'
        FDP_DB_PASSWORD = secret value
        BAD_LINE
        """,
        encoding="utf-8",
    )

    values = read_env_file(env_file)

    assert values["FDP_DB_HOST"] == "localhost"
    assert values["FDP_DB_USER"] == "research"
    assert values["FDP_DB_PASSWORD"] == "secret value"
    assert "BAD_LINE" not in values


def test_database_config_prefers_process_environment_over_cli_env(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "FDP_DB_HOST=file-host",
                "FDP_DB_USER=file-user",
                "FDP_DB_PASSWORD=file-secret",
                "FDP_DB_NAME=file-db",
            ]
        ),
        encoding="utf-8",
    )
    env = {
        "FDP_DB_HOST": "env-host",
        "FDP_DB_USER": "env-user",
        "FDP_DB_PASSWORD": "env-secret",
        "FDP_DB_NAME": "env-db",
    }

    config = database_config_from_environment(env=env, env_file=env_file)

    assert config is not None
    assert config.source == "environment"
    assert "env-host" in config.url
    assert "env-secret" in config.url
    assert "file-secret" not in config.url


def test_database_config_uses_cli_env_when_process_env_missing(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "FDP_DB_HOST=file-host",
                "FDP_DB_USER=file-user",
                "FDP_DB_PASSWORD=file-secret",
                "FDP_DB_NAME=file-db",
            ]
        ),
        encoding="utf-8",
    )

    config = database_config_from_environment(env={}, env_file=env_file)

    assert config is not None
    assert config.source == "database_system_cli/.env"
    assert "file-host" in config.url


def test_database_config_missing_required_values_returns_none(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FDP_DB_HOST=localhost\n", encoding="utf-8")

    assert database_config_from_environment(env={}, env_file=env_file) is None


def test_database_status_public_dict_never_contains_secret() -> None:
    status = DatabaseStatus(
        configured=True,
        available=False,
        source="database_system_cli/.env",
        message="Database connection failed. Check FDP_DATABASE_URL or FDP_DB_*.",
    )

    payload = status.as_dict()

    assert "token" not in payload
    assert "api_key" not in payload
    assert "secret-password" not in str(payload)
