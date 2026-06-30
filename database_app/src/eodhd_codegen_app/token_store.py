from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


SERVICE_NAME = "financial-data-platform.database_app.eodhd"
ACCOUNT_NAME = "default"


class TokenStoreError(RuntimeError):
    """Raised when the local token store cannot complete an operation."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class TokenStatus:
    configured: bool
    source: str
    can_delete: bool
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "source": self.source,
            "can_delete": self.can_delete,
            "message": self.message,
        }


class TokenStore:
    """Read and write the EODHD token without returning it to the browser.

    Input: token entered through local app config or `EODHD_API_KEY`.
    Output: hidden token status for UI and secret value only for server-side execution.
    Flow: local app config -> optional macOS Keychain lookup -> environment fallback -> execution client.
    """

    def __init__(
        self,
        *,
        runner: Runner = subprocess.run,
        fallback_path: Path | None = None,
        prefer_keychain: bool = False,
    ) -> None:
        self.runner = runner
        self.fallback_path = fallback_path or _default_fallback_path()
        self.prefer_keychain = prefer_keychain

    def status(self) -> TokenStatus:
        source = self.stored_token_source()
        if source:
            return TokenStatus(
                configured=True,
                source=source,
                can_delete=True,
                message="Token is stored in macOS Keychain."
                if source == "keychain"
                else "Token is stored in local app config.",
            )
        if os.environ.get("EODHD_API_KEY"):
            return TokenStatus(
                configured=True,
                source="environment",
                can_delete=False,
                message="Token is configured through EODHD_API_KEY fallback.",
            )
        return TokenStatus(
            configured=False,
            source="none",
            can_delete=False,
            message="No token configured.",
        )

    def resolve_token(self) -> str:
        return self.get_stored_token() or os.environ.get("EODHD_API_KEY", "")

    def stored_token_source(self) -> str:
        if not self.prefer_keychain and self.get_file_token():
            return "local_file"
        if self.get_keychain_token():
            return "keychain"
        if self.get_file_token():
            return "local_file"
        return ""

    def get_stored_token(self) -> str:
        if self.prefer_keychain:
            return self.get_keychain_token() or self.get_file_token()
        return self.get_file_token() or self.get_keychain_token()

    def get_keychain_token(self) -> str:
        if shutil.which("security") is None:
            return ""
        try:
            result = self.runner(
                [
                    "security",
                    "find-generic-password",
                    "-a",
                    ACCOUNT_NAME,
                    "-s",
                    SERVICE_NAME,
                    "-w",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def get_file_token(self) -> str:
        try:
            return self.fallback_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise TokenStoreError("Failed to read local token config") from exc

    def set_stored_token(self, token: str) -> TokenStatus:
        clean = token.strip()
        if len(clean) < 8:
            raise TokenStoreError("Token is too short")
        if len(clean) > 256:
            raise TokenStoreError("Token is too long")
        if any(ord(char) < 33 for char in clean):
            raise TokenStoreError("Token must not contain whitespace or control characters")
        if self.prefer_keychain and self._set_keychain_token(clean):
            self._delete_file_token(missing_ok=True)
            return self.status()
        self._set_file_token(clean)
        return self.status()

    def _set_keychain_token(self, token: str) -> bool:
        if shutil.which("security") is None:
            return False
        try:
            result = self.runner(
                [
                    "security",
                    "add-generic-password",
                    "-a",
                    ACCOUNT_NAME,
                    "-s",
                    SERVICE_NAME,
                    "-U",
                    "-w",
                ],
                capture_output=True,
                input=f"{token}\n{token}\n",
                text=True,
                timeout=3,
            )
        except subprocess.TimeoutExpired:
            return False
        if result.returncode != 0:
            return False
        return self.get_keychain_token() == token

    def _set_file_token(self, token: str) -> None:
        try:
            self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.fallback_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{token}\n")
            os.chmod(self.fallback_path, 0o600)
        except OSError as exc:
            raise TokenStoreError("Failed to store token in local app config") from exc

    def delete_stored_token(self) -> TokenStatus:
        source = self.stored_token_source()
        if not source:
            return self.status()
        self._delete_file_token(missing_ok=True)
        if source == "keychain" or self.prefer_keychain:
            self._delete_keychain_token()
            return self.status()
        if os.environ.get("EODHD_API_KEY"):
            return TokenStatus(
                configured=True,
                source="environment",
                can_delete=False,
                message="Token is configured through EODHD_API_KEY fallback.",
            )
        return TokenStatus(
            configured=False,
            source="none",
            can_delete=False,
            message="No token configured.",
        )

    def _delete_keychain_token(self) -> None:
        if shutil.which("security") is not None:
            try:
                result = self.runner(
                    [
                        "security",
                        "delete-generic-password",
                        "-a",
                        ACCOUNT_NAME,
                        "-s",
                        SERVICE_NAME,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
            except subprocess.TimeoutExpired:
                return
            if result.returncode not in {0, 44}:
                raise TokenStoreError("Failed to delete token from macOS Keychain")

    def _delete_file_token(self, *, missing_ok: bool) -> None:
        try:
            self.fallback_path.unlink(missing_ok=missing_ok)
        except OSError as exc:
            raise TokenStoreError("Failed to delete local token config") from exc


def _default_fallback_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "FinancialDataPlatform" / "database_app" / "eodhd_token"
