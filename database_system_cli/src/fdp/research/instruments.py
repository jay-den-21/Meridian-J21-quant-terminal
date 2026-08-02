"""Read-only instrument metadata queries for research code."""

from datetime import date
from typing import Any, Sequence

from sqlalchemy import false, or_, select
from sqlalchemy.engine import Connection
from sqlalchemy.sql import ColumnElement, Select

from fdp.storage.tables import (
    instrument,
    instrument_identifier_history,
    instrument_lifecycle_event,
)

DateInput = date | str | None


class InstrumentUniverseReader:
    """Read instrument evidence by explicit Data Core instrument IDs.

    Input: database connection, explicit instrument IDs, and optional date bounds.
    Output: deterministic instrument, identifier-history, and lifecycle dictionaries.
    Flow: validate IDs/dates -> build SELECT -> execute -> mappings to dictionaries.
    """

    def __init__(
        self,
        connection: Connection,
        *,
        date_from: DateInput = None,
        date_to: DateInput = None,
    ) -> None:
        self.connection = connection
        self.date_from, self.date_to = _coerce_date_range(
            date_from,
            date_to,
            required=False,
        )

    def get_instruments(
        self,
        *,
        instrument_ids: Sequence[int],
        date_from: DateInput = None,
        date_to: DateInput = None,
    ) -> list[dict[str, Any]]:
        """Return deterministic instrument records for explicit IDs."""
        normalized_ids = _normalize_instrument_ids(instrument_ids)
        if not normalized_ids:
            return []
        statement = self.build_instruments_query(
            instrument_ids=normalized_ids,
            date_from=date_from,
            date_to=date_to,
        )
        return self._execute(statement)

    def build_instruments_query(
        self,
        *,
        instrument_ids: Sequence[int],
        date_from: DateInput = None,
        date_to: DateInput = None,
    ) -> Select[Any]:
        """Build the SELECT used by :meth:`get_instruments`."""
        normalized_ids = _normalize_instrument_ids(instrument_ids)
        resolved_from, resolved_to = self.resolve_date_range(
            date_from=date_from,
            date_to=date_to,
        )
        predicates: list[ColumnElement[bool]] = [
            instrument.c.instrument_id.in_(normalized_ids) if normalized_ids else false()
        ]
        if resolved_from is not None and resolved_to is not None:
            predicates.extend(
                (
                    or_(
                        instrument.c.listed_date.is_(None), instrument.c.listed_date <= resolved_to
                    ),
                    or_(
                        instrument.c.delisted_date.is_(None),
                        instrument.c.delisted_date >= resolved_from,
                    ),
                )
            )

        return _instrument_records_select().where(*predicates).order_by(instrument.c.instrument_id)

    def find_instrument_candidates(
        self,
        *,
        identifiers: Sequence[str],
        date_from: DateInput = None,
        date_to: DateInput = None,
        market: str | None = None,
        asset_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return every instrument candidate matching explicit identifiers."""
        normalized_identifiers = _normalize_identifiers(identifiers)
        if not normalized_identifiers:
            return []
        statement = self.build_find_instrument_candidates_query(
            identifiers=normalized_identifiers,
            date_from=date_from,
            date_to=date_to,
            market=market,
            asset_type=asset_type,
        )
        return self._execute(statement)

    def build_find_instrument_candidates_query(
        self,
        *,
        identifiers: Sequence[str],
        date_from: DateInput = None,
        date_to: DateInput = None,
        market: str | None = None,
        asset_type: str | None = None,
    ) -> Select[Any]:
        """Build a bounded SELECT returning all identifier candidates.

        Input: ticker/provider-symbol values plus optional date, market, and asset filters.
        Output: deterministic instrument rows without uniqueness selection.
        Flow: normalize inputs -> match current or overlapping historical IDs -> order rows.
        """
        normalized_identifiers = _normalize_identifiers(identifiers)
        normalized_market = _normalize_optional_filter(market, field_name="market", uppercase=True)
        normalized_asset_type = _normalize_optional_filter(
            asset_type,
            field_name="asset_type",
            uppercase=False,
        )
        resolved_from, resolved_to = self.resolve_date_range(
            date_from=date_from,
            date_to=date_to,
        )

        predicates: list[ColumnElement[bool]] = []
        if normalized_identifiers:
            history_predicates: list[ColumnElement[bool]] = [
                instrument_identifier_history.c.instrument_id == instrument.c.instrument_id,
                instrument_identifier_history.c.id_type.in_(("ticker", "provider_symbol")),
                instrument_identifier_history.c.id_value.in_(normalized_identifiers),
            ]
            if resolved_from is not None and resolved_to is not None:
                history_predicates.extend(
                    (
                        or_(
                            instrument_identifier_history.c.valid_from.is_(None),
                            instrument_identifier_history.c.valid_from <= resolved_to,
                        ),
                        or_(
                            instrument_identifier_history.c.valid_to.is_(None),
                            instrument_identifier_history.c.valid_to >= resolved_from,
                        ),
                    )
                )
            history_match = (
                select(1)
                .select_from(instrument_identifier_history)
                .where(*history_predicates)
                .exists()
            )
            predicates.append(
                or_(
                    instrument.c.symbol.in_(normalized_identifiers),
                    instrument.c.provider_symbol.in_(normalized_identifiers),
                    history_match,
                )
            )
        else:
            predicates.append(false())

        if resolved_from is not None and resolved_to is not None:
            predicates.extend(
                (
                    or_(
                        instrument.c.listed_date.is_(None), instrument.c.listed_date <= resolved_to
                    ),
                    or_(
                        instrument.c.delisted_date.is_(None),
                        instrument.c.delisted_date >= resolved_from,
                    ),
                )
            )
        if normalized_market is not None:
            predicates.append(instrument.c.market == normalized_market)
        if normalized_asset_type is not None:
            predicates.append(instrument.c.asset_type == normalized_asset_type)

        return _instrument_records_select().where(*predicates).order_by(instrument.c.instrument_id)

    def get_identifier_history(
        self,
        *,
        instrument_ids: Sequence[int],
        date_from: DateInput = None,
        date_to: DateInput = None,
    ) -> list[dict[str, Any]]:
        """Return all overlapping identifier rows for explicit IDs."""
        normalized_ids = _normalize_instrument_ids(instrument_ids)
        if not normalized_ids:
            return []
        statement = self.build_identifier_history_query(
            instrument_ids=normalized_ids,
            date_from=date_from,
            date_to=date_to,
        )
        return self._execute(statement)

    def build_identifier_history_query(
        self,
        *,
        instrument_ids: Sequence[int],
        date_from: DateInput = None,
        date_to: DateInput = None,
    ) -> Select[Any]:
        """Build the SELECT used by :meth:`get_identifier_history`."""
        normalized_ids = _normalize_instrument_ids(instrument_ids)
        resolved_from, resolved_to = self.resolve_date_range(
            date_from=date_from,
            date_to=date_to,
        )
        predicates: list[ColumnElement[bool]] = [
            instrument_identifier_history.c.instrument_id.in_(normalized_ids)
            if normalized_ids
            else false()
        ]
        if resolved_from is not None and resolved_to is not None:
            predicates.extend(
                (
                    or_(
                        instrument_identifier_history.c.valid_from.is_(None),
                        instrument_identifier_history.c.valid_from <= resolved_to,
                    ),
                    or_(
                        instrument_identifier_history.c.valid_to.is_(None),
                        instrument_identifier_history.c.valid_to >= resolved_from,
                    ),
                )
            )

        return (
            select(
                instrument_identifier_history.c.identifier_history_id,
                instrument_identifier_history.c.instrument_id,
                instrument_identifier_history.c.id_type,
                instrument_identifier_history.c.id_value,
                instrument_identifier_history.c.valid_from,
                instrument_identifier_history.c.valid_to,
                instrument_identifier_history.c.source,
                instrument_identifier_history.c.created_at,
                instrument_identifier_history.c.updated_at,
            )
            .where(*predicates)
            .order_by(
                instrument_identifier_history.c.instrument_id,
                instrument_identifier_history.c.id_type,
                instrument_identifier_history.c.id_value,
                instrument_identifier_history.c.valid_from,
                instrument_identifier_history.c.valid_to,
                instrument_identifier_history.c.source,
                instrument_identifier_history.c.identifier_history_id,
            )
        )

    def get_lifecycle_events(
        self,
        *,
        instrument_ids: Sequence[int],
        date_from: DateInput = None,
        date_to: DateInput = None,
    ) -> list[dict[str, Any]]:
        """Return lifecycle evidence for explicit IDs, including undated events."""
        normalized_ids = _normalize_instrument_ids(instrument_ids)
        if not normalized_ids:
            return []
        statement = self.build_lifecycle_events_query(
            instrument_ids=normalized_ids,
            date_from=date_from,
            date_to=date_to,
        )
        return self._execute(statement)

    def build_lifecycle_events_query(
        self,
        *,
        instrument_ids: Sequence[int],
        date_from: DateInput = None,
        date_to: DateInput = None,
    ) -> Select[Any]:
        """Build the SELECT used by :meth:`get_lifecycle_events`."""
        normalized_ids = _normalize_instrument_ids(instrument_ids)
        resolved_from, resolved_to = self.resolve_date_range(
            date_from=date_from,
            date_to=date_to,
        )
        predicates: list[ColumnElement[bool]] = [
            instrument_lifecycle_event.c.instrument_id.in_(normalized_ids)
            if normalized_ids
            else false()
        ]
        if resolved_from is not None and resolved_to is not None:
            predicates.append(
                or_(
                    instrument_lifecycle_event.c.event_date.is_(None),
                    instrument_lifecycle_event.c.event_date.between(resolved_from, resolved_to),
                )
            )

        return (
            select(
                instrument_lifecycle_event.c.lifecycle_event_id,
                instrument_lifecycle_event.c.instrument_id,
                instrument_lifecycle_event.c.event_type,
                instrument_lifecycle_event.c.event_date,
                instrument_lifecycle_event.c.symbol,
                instrument_lifecycle_event.c.provider_symbol,
                instrument_lifecycle_event.c.source,
                instrument_lifecycle_event.c.event_key,
                instrument_lifecycle_event.c.details,
                instrument_lifecycle_event.c.created_at,
                instrument_lifecycle_event.c.updated_at,
            )
            .where(*predicates)
            .order_by(
                instrument_lifecycle_event.c.instrument_id,
                instrument_lifecycle_event.c.event_date,
                instrument_lifecycle_event.c.event_type,
                instrument_lifecycle_event.c.source,
                instrument_lifecycle_event.c.event_key,
                instrument_lifecycle_event.c.lifecycle_event_id,
            )
        )

    def resolve_date_range(
        self,
        *,
        date_from: DateInput = None,
        date_to: DateInput = None,
    ) -> tuple[date | None, date | None]:
        """Resolve optional method dates before optional reader defaults."""
        if (date_from is None) != (date_to is None):
            raise ValueError("date_from and date_to must be provided together")
        if date_from is None and date_to is None:
            return self.date_from, self.date_to
        return _coerce_date_range(date_from, date_to, required=True)

    def _execute(self, statement: Select[Any]) -> list[dict[str, Any]]:
        rows = self.connection.execute(statement).mappings().all()
        return [dict(row) for row in rows]


def _normalize_instrument_ids(instrument_ids: Sequence[int]) -> tuple[int, ...]:
    normalized: set[int] = set()
    for instrument_id in instrument_ids:
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int):
            raise ValueError("instrument_ids must contain only integers")
        if instrument_id <= 0:
            raise ValueError("instrument_ids must contain only positive integers")
        normalized.add(instrument_id)
    return tuple(sorted(normalized))


def _normalize_identifiers(identifiers: Sequence[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for identifier in identifiers:
        if not isinstance(identifier, str):
            raise ValueError("identifiers must contain only strings")
        value = identifier.strip().upper()
        if value:
            normalized.add(value)
    return tuple(sorted(normalized))


def _normalize_optional_filter(
    value: str | None,
    *,
    field_name: str,
    uppercase: bool,
) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized.upper() if uppercase else normalized.lower()


def _instrument_records_select() -> Select[Any]:
    return select(
        instrument.c.instrument_id,
        instrument.c.market,
        instrument.c.symbol,
        instrument.c.provider,
        instrument.c.provider_symbol,
        instrument.c.name,
        instrument.c.exchange,
        instrument.c.asset_type,
        instrument.c.currency,
        instrument.c.is_active,
        instrument.c.listed_date,
        instrument.c.delisted_date,
        instrument.c.created_at,
        instrument.c.updated_at,
    )


def _coerce_date_range(
    date_from: DateInput,
    date_to: DateInput,
    *,
    required: bool,
) -> tuple[date | None, date | None]:
    if (date_from is None) != (date_to is None):
        raise ValueError("date_from and date_to must be provided together")
    if date_from is None and date_to is None:
        if required:
            raise ValueError("date_from and date_to are required")
        return None, None

    resolved_from = _coerce_date(date_from, field_name="date_from")
    resolved_to = _coerce_date(date_to, field_name="date_to")
    if resolved_to < resolved_from:
        raise ValueError("date_to must be greater than or equal to date_from")
    return resolved_from, resolved_to


def _coerce_date(value: DateInput, *, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc
