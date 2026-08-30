"""Typed, credential-safe failures for the Tushare source layer."""

from __future__ import annotations

import re


_CREDENTIAL_LABEL = (
    r"token|access_token|api_key|authorization|password|passwd|secret|credential|cookie"
)
_JSON_CREDENTIAL = re.compile(
    rf'(?i)(["\'](?:{_CREDENTIAL_LABEL})["\']\s*:\s*)["\'][^"\']*["\']'
)
_AUTH_SCHEME = re.compile(r"(?i)\b(bearer|basic)\s+[^\s,;]+")
_TOKEN_ASSIGNMENT = re.compile(rf"(?i)({_CREDENTIAL_LABEL})\s*[:=]\s*[^\s,;&]+")
_URI_USERINFO = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)([^/@\s:]+):([^@\s/]+)@")


def safe_error_message(message: object, *, token: str | None = None) -> str:
    """Return a bounded message with common credential forms removed."""
    value = str(message).replace("\r", " ").replace("\n", " ")
    if token:
        value = value.replace(token, "[REDACTED]")
    value = _URI_USERINFO.sub(r"\1[REDACTED]@", value)
    value = _JSON_CREDENTIAL.sub(r'\1"[REDACTED]"', value)
    value = _AUTH_SCHEME.sub(lambda match: f"{match.group(1)} [REDACTED]", value)
    value = _TOKEN_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return value[:300]


class TushareError(RuntimeError):
    """Base failure safe to expose in a Job result or progress event."""

    kind = "tushare_error"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        attempts: int | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.attempts = attempts
        self.status_code = status_code


class TushareCatalogError(TushareError):
    kind = "catalog"


class TushareCapabilityError(TushareCatalogError):
    kind = "capability"


class TushareParameterError(TushareError, ValueError):
    kind = "parameter"


class TushareDataError(TushareError, ValueError):
    kind = "data"


class TushareTransportError(TushareError):
    kind = "network"
    retryable = True


class TushareHttpError(TushareTransportError):
    kind = "http"


class TushareRedirectError(TushareHttpError):
    kind = "redirect"
    retryable = False


class TushareResponseTooLargeError(TushareTransportError):
    kind = "response_too_large"
    retryable = False


class TushareProtocolError(TushareError):
    kind = "protocol"


class TushareProviderError(TushareError):
    kind = "provider"

    def __init__(self, message: str, *, provider_code: int, **kwargs: object) -> None:
        super().__init__(message, **kwargs)
        self.provider_code = provider_code


class TushareAuthenticationError(TushareProviderError):
    kind = "authentication"


class TusharePermissionError(TushareProviderError):
    kind = "permission"


class TushareRateLimitError(TushareProviderError):
    kind = "rate_limit"
    retryable = True


class TushareNoDataError(TushareProviderError):
    kind = "no_data"


class TushareStorageError(TushareError):
    kind = "storage"


class TusharePostCommitStorageError(TushareStorageError):
    """A page committed successfully, but its connection cleanup failed."""

    kind = "storage_post_commit"
    page_committed = True


class TushareRunLeaseCleanupError(TushareStorageError):
    """Run state was persisted, but releasing its execution lease was not confirmed."""

    kind = "run_lease_cleanup"
