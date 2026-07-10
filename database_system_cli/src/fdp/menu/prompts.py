"""Questionary adapter kept injectable for non-interactive tests."""

from __future__ import annotations

from typing import Any

import questionary


class PromptSession:
    def select(
        self,
        message: str,
        choices: list[tuple[str, Any]],
        *,
        default: Any | None = None,
    ) -> Any:
        rendered = [questionary.Choice(title=label, value=value) for label, value in choices]
        return questionary.select(message, choices=rendered, default=default).ask()

    def checkbox(
        self,
        message: str,
        choices: list[tuple[str, Any]],
        *,
        defaults: set[Any] | None = None,
    ) -> list[Any] | None:
        selected = defaults or set()
        rendered = [
            questionary.Choice(title=label, value=value, checked=value in selected)
            for label, value in choices
        ]
        return questionary.checkbox(message, choices=rendered).ask()

    def text(self, message: str, *, default: str = "") -> str | None:
        return questionary.text(message, default=default).ask()

    def confirm(self, message: str, *, default: bool = False) -> bool | None:
        return questionary.confirm(message, default=default).ask()
