"""Event-date identity resolution for ticker-based corporate-action histories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import select
from sqlalchemy.engine import Connection

from fdp.storage.tables import instrument, instrument_identifier_history

CorporateActionMatchMethod = Literal[
    "dated_provider_symbol_history",
    "current_provider_symbol",
    "current_after_historical_owner",
    "current_provider_symbol_fallback",
]


@dataclass(frozen=True)
class CorporateActionIdentityResolution:
    """One safe event-date owner or an explicit unresolved reason."""

    instrument: dict[str, object] | None
    matched_by: CorporateActionMatchMethod | None
    reason: str | None
    candidate_instrument_ids: tuple[int, ...] = ()


class CorporateActionIdentityResolver:
    """Resolve one ticker-based event without assigning old history to its current owner.

    Input: stock owners plus non-stock ticker-collision guards and bounded history.
    Output: one candidate owner or explicit ambiguity; persistence still requires stock.
    Flow: valid dated history -> safe current-after-history -> unique current -> unresolved.
    """

    def __init__(
        self,
        *,
        current_rows: list[dict[str, object]],
        history_rows: list[dict[str, object]],
    ) -> None:
        self._current_by_symbol = _group_current(current_rows)
        self._history_by_symbol = _group_history(history_rows)

    @classmethod
    def from_connection(
        cls,
        connection: Connection,
        *,
        market: str,
    ) -> "CorporateActionIdentityResolver":
        """Load stock owners and non-stock rows used only to reject ticker collisions."""
        columns = (
            instrument.c.instrument_id,
            instrument.c.symbol,
            instrument.c.provider_symbol,
            instrument.c.asset_type,
            instrument.c.currency,
            instrument.c.listed_date,
            instrument.c.delisted_date,
        )
        conditions = (
            instrument.c.provider == "EODHD",
            instrument.c.market == market,
            instrument.c.asset_type.in_(("stock", "etf", "fund")),
        )
        current_rows = [
            dict(row)
            for row in connection.execute(select(*columns).where(*conditions)).mappings()
        ]
        history_rows = [
            dict(row)
            for row in connection.execute(
                select(
                    *columns,
                    instrument_identifier_history.c.id_value,
                    instrument_identifier_history.c.valid_from,
                    instrument_identifier_history.c.valid_to,
                    instrument_identifier_history.c.source.label("history_source"),
                )
                .select_from(
                    instrument_identifier_history.join(
                        instrument,
                        instrument_identifier_history.c.instrument_id
                        == instrument.c.instrument_id,
                    )
                )
                .where(
                    instrument_identifier_history.c.id_type == "provider_symbol",
                    *conditions,
                )
            ).mappings()
        ]
        return cls(current_rows=current_rows, history_rows=history_rows)

    def resolve(
        self,
        *,
        provider_symbol: str,
        action_date: date,
    ) -> CorporateActionIdentityResolution:
        """Resolve the event owner, preferring dated evidence over endpoint identity."""
        key = provider_symbol.strip().upper()
        all_history = self._history_by_symbol.get(key, [])
        bounded_history = [row for row in all_history if _has_validity_bound(row)]
        dated = [row for row in bounded_history if _is_valid_on(row, action_date)]
        if dated:
            return _unique_resolution(
                dated,
                matched_by="dated_provider_symbol_history",
                ambiguous_reason="ambiguous_dated_provider_symbol_owner",
            )

        current = self._current_by_symbol.get(key, [])
        if bounded_history:
            future_starts = [
                row["valid_from"]
                for row in bounded_history
                if row.get("valid_from") is not None and action_date < row["valid_from"]
            ]
            finite_ends = [
                row["valid_to"]
                for row in bounded_history
                if row.get("valid_to") is not None
            ]
            if finite_ends and action_date > max(finite_ends) and not future_starts:
                return _unique_resolution(
                    current,
                    matched_by="current_after_historical_owner",
                    ambiguous_reason="ambiguous_current_provider_symbol_owner",
                )
            if current:
                # EODHD's current-symbol endpoint can return the same security's
                # pre-rename history. A dated prior owner still wins above; without
                # one, the unique endpoint owner is the best available identity.
                return _unique_resolution(
                    current,
                    matched_by="current_provider_symbol_fallback",
                    ambiguous_reason="ambiguous_current_provider_symbol_owner",
                )
            return _unresolved(
                "provider_symbol_not_valid_on_action_date",
                bounded_history,
            )

        return _unique_resolution(
            current,
            matched_by="current_provider_symbol",
            ambiguous_reason="ambiguous_current_provider_symbol_owner",
        )

    @property
    def bounded_provider_symbols(self) -> tuple[str, ...]:
        """Provider symbols whose event rows require date-aware ownership checks."""
        return tuple(
            sorted(
                key
                for key, rows in self._history_by_symbol.items()
                if any(_has_validity_bound(row) for row in rows)
            )
        )


def _group_current(
    rows: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["provider_symbol"]).upper(), []).append(row)
    return grouped


def _group_history(
    rows: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["id_value"]).upper(), []).append(row)
    return grouped


def _has_validity_bound(row: dict[str, object]) -> bool:
    return row.get("valid_from") is not None or row.get("valid_to") is not None


def _is_valid_on(row: dict[str, object], action_date: date) -> bool:
    valid_from = row.get("valid_from")
    valid_to = row.get("valid_to")
    return (valid_from is None or valid_from <= action_date) and (
        valid_to is None or action_date <= valid_to
    )


def _unique_resolution(
    rows: list[dict[str, object]],
    *,
    matched_by: CorporateActionMatchMethod,
    ambiguous_reason: str,
) -> CorporateActionIdentityResolution:
    by_id = {int(row["instrument_id"]): row for row in rows}
    if len(by_id) == 1:
        return CorporateActionIdentityResolution(
            instrument=next(iter(by_id.values())),
            matched_by=matched_by,
            reason=None,
        )
    if not by_id:
        return _unresolved("provider_symbol_owner_not_found", [])
    return _unresolved(ambiguous_reason, list(by_id.values()))


def _unresolved(
    reason: str,
    rows: list[dict[str, object]],
) -> CorporateActionIdentityResolution:
    return CorporateActionIdentityResolution(
        instrument=None,
        matched_by=None,
        reason=reason,
        candidate_instrument_ids=tuple(
            sorted({int(row["instrument_id"]) for row in rows})
        ),
    )
