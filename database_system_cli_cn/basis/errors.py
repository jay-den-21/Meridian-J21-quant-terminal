"""Errors raised by the clean-room Python replacement."""

from typing import NoReturn


class UnsupportedLegacyAuthorizationError(RuntimeError):
    """The removed machine-bound authorization API was invoked."""


def legacy_authorization_removed(api_name: str) -> NoReturn:
    """Raise the common, explicit error used by every removed entry point."""
    raise UnsupportedLegacyAuthorizationError(
        f"{api_name} belonged to the removed machine-bound authorization layer; "
        "configure your own Tushare token instead"
    )
