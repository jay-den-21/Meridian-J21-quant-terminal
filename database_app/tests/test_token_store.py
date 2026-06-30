from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from eodhd_codegen_app.token_store import ACCOUNT_NAME, SERVICE_NAME, TokenStatus, TokenStore, TokenStoreError


def test_token_status_public_dict_never_contains_secret() -> None:
    status = TokenStatus(
        configured=True,
        source="keychain",
        can_delete=True,
        message="Token is stored in macOS Keychain.",
    )

    payload = status.as_dict()

    assert "token" not in payload
    assert "api_key" not in payload
    assert "secret-value" not in str(payload)


def test_token_store_uses_environment_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EODHD_API_KEY", "env-token")
    monkeypatch.setattr("shutil.which", lambda name: None)
    store = TokenStore(
        runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
        fallback_path=tmp_path / "missing-token",
    )

    status = store.status()

    assert status.configured is True
    assert status.source == "environment"
    assert status.can_delete is False
    assert store.resolve_token() == "env-token"


def test_token_store_prefers_saved_login_token_over_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EODHD_API_KEY", "env-token")
    fallback_path = tmp_path / "token"
    fallback_path.write_text("login-token-123\n", encoding="utf-8")
    store = TokenStore(
        runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
        fallback_path=fallback_path,
    )

    status = store.status()

    assert status.configured is True
    assert status.source == "local_file"
    assert status.can_delete is True
    assert store.resolve_token() == "login-token-123"


def test_delete_saved_login_token_reveals_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EODHD_API_KEY", "env-token")
    fallback_path = tmp_path / "token"
    fallback_path.write_text("login-token-123\n", encoding="utf-8")
    store = TokenStore(
        runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
        fallback_path=fallback_path,
    )

    status = store.delete_stored_token()

    assert not fallback_path.exists()
    assert status.source == "environment"
    assert status.can_delete is False
    assert store.resolve_token() == "env-token"


def test_token_store_uses_security_args_without_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/security" if name == "security" else None)
    calls: list[list[str]] = []
    inputs: list[str] = []

    def fake_runner(args, **kwargs):
        calls.append(args)
        inputs.append(kwargs.get("input", ""))
        if args[:2] == ["security", "find-generic-password"]:
            return subprocess.CompletedProcess(args, 0, "stored-token-123\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    store = TokenStore(runner=fake_runner, fallback_path=tmp_path / "unused", prefer_keychain=True)
    store.set_stored_token("stored-token-123")

    assert calls[0][:2] == ["security", "add-generic-password"]
    assert calls[0][-1] == "-w"
    assert "stored-token-123" not in calls[0]
    assert inputs[0] == "stored-token-123\nstored-token-123\n"
    assert ACCOUNT_NAME in calls[0]
    assert SERVICE_NAME in calls[0]


def test_token_store_falls_back_to_local_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/security" if name == "security" else None)

    calls = []

    def fake_runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, "", "keychain failed")

    fallback_path = tmp_path / "token"
    store = TokenStore(runner=fake_runner, fallback_path=fallback_path)

    status = store.set_stored_token("stored-token-456")

    assert status.configured is True
    assert status.source == "local_file"
    assert fallback_path.read_text(encoding="utf-8").strip() == "stored-token-456"
    assert oct(fallback_path.stat().st_mode & 0o777) == "0o600"
    assert store.resolve_token() == "stored-token-456"
    assert calls == []


def test_token_store_ignores_keychain_lookup_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/security" if name == "security" else None)

    def fake_runner(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0))

    store = TokenStore(runner=fake_runner, fallback_path=tmp_path / "missing-token", prefer_keychain=True)

    assert store.status().configured is False


def test_token_delete_local_file_does_not_call_keychain_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/security" if name == "security" else None)
    calls = []

    def fake_runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    fallback_path = tmp_path / "token"
    fallback_path.write_text("stored-token-789\n", encoding="utf-8")
    store = TokenStore(runner=fake_runner, fallback_path=fallback_path)

    status = store.delete_stored_token()

    assert status.configured is False
    assert not fallback_path.exists()
    assert calls == []


def test_token_delete_keychain_timeout_does_not_block(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/security" if name == "security" else None)

    def fake_runner(args, **kwargs):
        if args[:2] == ["security", "find-generic-password"]:
            return subprocess.CompletedProcess(args, 0, "stored-token-123\n", "")
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0))

    store = TokenStore(runner=fake_runner, fallback_path=tmp_path / "missing-token")

    assert store.delete_stored_token().configured is True


def test_token_store_rejects_bad_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/security" if name == "security" else None)
    store = TokenStore()

    with pytest.raises(TokenStoreError, match="too short"):
        store.set_stored_token("short")

    with pytest.raises(TokenStoreError, match="must not contain whitespace"):
        store.set_stored_token("bad token with spaces")
