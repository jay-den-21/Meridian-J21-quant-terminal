"""Canonical and unmatched persistence for EODHD ID Mapping pages."""

from __future__ import annotations

from dataclasses import dataclass
import json

from sqlalchemy import case, select, update
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.id_mapping import (
    ID_MAPPING_SOURCE,
    IDENTIFIER_TYPES,
    IdentifierMappingEnvelope,
    IdentifierMappingRecord,
)
from fdp.sources.eodhd.ingest.common import now_utc
from fdp.storage.tables import (
    identifier_mapping_unmatched_observation,
    instrument,
    instrument_identifier_history,
)
from fdp.storage.upsert import (
    build_identifier_history_upsert,
    build_identifier_mapping_unmatched_upsert,
)


@dataclass(frozen=True)
class IdentifierResolution:
    """Exact provider-symbol resolution outcome for one mapping row."""

    instrument_id: int | None
    reason: str | None
    candidate_instrument_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class IdentifierMappingPageResult:
    """Committed facts produced by one ID Mapping response page."""

    total: int
    offset: int
    rows_fetched: int
    rows_matched: int
    identifiers_inserted: int
    identifiers_unchanged: int
    rows_unmatched: int
    rows_invalid: int
    identifier_conflicts: int
    next_offset: int | None


@dataclass(frozen=True)
class IdentifierMappingResolver:
    """Resolve provider symbols without fuzzy names or external-ID guessing."""

    current: dict[str, int]
    historical: dict[str, frozenset[int]]

    @classmethod
    def from_connection(
        cls,
        connection: Connection,
        provider_symbols: list[str],
    ) -> "IdentifierMappingResolver":
        normalized = sorted(set(provider_symbols))
        if not normalized:
            return cls(current={}, historical={})
        current = {
            str(row["provider_symbol"]): int(row["instrument_id"])
            for row in connection.execute(
                select(instrument.c.instrument_id, instrument.c.provider_symbol).where(
                    instrument.c.provider == "EODHD",
                    instrument.c.provider_symbol.in_(normalized),
                )
            ).mappings()
        }
        historical_sets: dict[str, set[int]] = {}
        for row in connection.execute(
            select(
                instrument_identifier_history.c.id_value,
                instrument_identifier_history.c.instrument_id,
            ).where(
                instrument_identifier_history.c.id_type == "provider_symbol",
                instrument_identifier_history.c.id_value.in_(normalized),
            )
        ).mappings():
            historical_sets.setdefault(str(row["id_value"]), set()).add(
                int(row["instrument_id"])
            )
        return cls(
            current=current,
            historical={key: frozenset(value) for key, value in historical_sets.items()},
        )

    def resolve(self, provider_symbol: str) -> IdentifierResolution:
        current_id = self.current.get(provider_symbol)
        if current_id is not None:
            return IdentifierResolution(current_id, None, (current_id,))
        historical_ids = tuple(sorted(self.historical.get(provider_symbol, ())))
        if len(historical_ids) == 1:
            return IdentifierResolution(historical_ids[0], None, historical_ids)
        if historical_ids:
            return IdentifierResolution(None, "ambiguous_provider_symbol_history", historical_ids)
        return IdentifierResolution(None, "missing_instrument")


def process_identifier_mapping_page(
    connection: Connection,
    *,
    run_id: int,
    market: str,
    envelope: IdentifierMappingEnvelope,
) -> IdentifierMappingPageResult:
    """Resolve, validate, and persist one already-fetched mapping page.

    Input: transaction, aggregate run id, market, and parsed provider envelope.
    Output: page counters and next offset after canonical/unmatched upserts.
    Flow: exact symbol resolution -> ID conflict check -> canonical or observation.
    """
    if envelope.has_next and not envelope.rows:
        raise ValueError("EODHD ID mapping returned an empty page before declared total")

    provider_symbols = [
        row.provider_symbol for row in envelope.rows if row.provider_symbol is not None
    ]
    resolver = IdentifierMappingResolver.from_connection(connection, provider_symbols)
    resolutions = {
        row.fingerprint: (
            resolver.resolve(row.provider_symbol)
            if row.provider_symbol is not None and row.row_error != "invalid_provider_symbol"
            else IdentifierResolution(None, "invalid_provider_symbol")
        )
        for row in envelope.rows
    }
    matched_instrument_ids = sorted(
        {
            resolution.instrument_id
            for resolution in resolutions.values()
            if resolution.instrument_id is not None
        }
    )
    existing = _load_existing_undated_identifiers(connection, matched_instrument_ids)

    canonical_rows: list[dict[str, object]] = []
    canonical_keys_seen: set[tuple[int, str, str]] = set()
    unmatched_rows: list[dict[str, object]] = []
    resolved_fingerprints: list[tuple[str, int]] = []
    rows_matched = 0
    inserted = 0
    unchanged = 0
    invalid_rows = 0
    conflict_count = 0

    for record in envelope.rows:
        resolution = resolutions[record.fingerprint]
        issues = _record_issues(record, resolution)
        if record.row_error or record.invalid_fields:
            invalid_rows += 1
        if resolution.instrument_id is not None:
            rows_matched += 1
            for id_type, id_value in record.identifiers.items():
                key = (resolution.instrument_id, id_type, id_value)
                if key in canonical_keys_seen:
                    continue
                canonical_keys_seen.add(key)
                canonical_rows.append(
                    {
                        "instrument_id": resolution.instrument_id,
                        "id_type": id_type,
                        "id_value": id_value,
                        "valid_from": None,
                        "valid_to": None,
                        "source": ID_MAPPING_SOURCE,
                    }
                )
                if key in existing:
                    unchanged += 1
                else:
                    inserted += 1
                    existing.add(key)

        if issues:
            unmatched_rows.append(
                _unmatched_observation_row(
                    record,
                    run_id=run_id,
                    market=market,
                    reason=";".join(dict.fromkeys(issues)),
                    resolution=resolution,
                )
            )
        elif resolution.instrument_id is not None:
            resolved_fingerprints.append((record.fingerprint, resolution.instrument_id))

    if canonical_rows:
        connection.execute(build_identifier_history_upsert(canonical_rows))
    if unmatched_rows:
        connection.execute(build_identifier_mapping_unmatched_upsert(unmatched_rows))
    _mark_prior_observations_resolved(
        connection,
        run_id=run_id,
        resolved_fingerprints=resolved_fingerprints,
    )

    next_offset = envelope.offset + len(envelope.rows) if envelope.has_next else None
    return IdentifierMappingPageResult(
        total=envelope.total,
        offset=envelope.offset,
        rows_fetched=len(envelope.rows),
        rows_matched=rows_matched,
        identifiers_inserted=inserted,
        identifiers_unchanged=unchanged,
        rows_unmatched=len(unmatched_rows),
        rows_invalid=invalid_rows,
        identifier_conflicts=conflict_count,
        next_offset=next_offset,
    )


def _load_existing_undated_identifiers(
    connection: Connection,
    instrument_ids: list[int],
) -> set[tuple[int, str, str]]:
    if not instrument_ids:
        return set()
    existing: set[tuple[int, str, str]] = set()
    for row in connection.execute(
        select(
            instrument_identifier_history.c.instrument_id,
            instrument_identifier_history.c.id_type,
            instrument_identifier_history.c.id_value,
        ).where(
            instrument_identifier_history.c.instrument_id.in_(instrument_ids),
            instrument_identifier_history.c.id_type.in_(IDENTIFIER_TYPES),
            instrument_identifier_history.c.source == ID_MAPPING_SOURCE,
            instrument_identifier_history.c.valid_from.is_(None),
            instrument_identifier_history.c.valid_to.is_(None),
        )
    ).mappings():
        existing.add(
            (
                int(row["instrument_id"]),
                str(row["id_type"]),
                str(row["id_value"]),
            )
        )
    return existing


def _record_issues(
    record: IdentifierMappingRecord,
    resolution: IdentifierResolution,
) -> list[str]:
    issues: list[str] = []
    if record.row_error:
        issues.append(record.row_error)
    if record.invalid_fields:
        issues.append(f"invalid_identifier_fields={','.join(record.invalid_fields)}")
    if resolution.reason and resolution.reason not in issues:
        issues.append(resolution.reason)
    return issues


def _unmatched_observation_row(
    record: IdentifierMappingRecord,
    *,
    run_id: int,
    market: str,
    reason: str,
    resolution: IdentifierResolution,
) -> dict[str, object]:
    return {
        "last_run_id": run_id,
        "market": market,
        "provider_symbol": record.provider_symbol,
        **{id_type: record.source_values.get(id_type) for id_type in IDENTIFIER_TYPES},
        "raw_payload": record.raw_payload,
        "mapping_fingerprint": record.fingerprint,
        "reason": reason,
        "candidate_instrument_ids": (
            json.dumps(list(resolution.candidate_instrument_ids))
            if resolution.candidate_instrument_ids
            else None
        ),
        "resolution_status": "pending",
        "resolved_instrument_id": resolution.instrument_id,
        "source": ID_MAPPING_SOURCE,
        "resolved_at": None,
    }


def _mark_prior_observations_resolved(
    connection: Connection,
    *,
    run_id: int,
    resolved_fingerprints: list[tuple[str, int]],
) -> None:
    resolved_by_fingerprint = dict(resolved_fingerprints)
    if not resolved_by_fingerprint:
        return
    observed_at = now_utc()
    connection.execute(
        update(identifier_mapping_unmatched_observation)
        .where(
            identifier_mapping_unmatched_observation.c.source == ID_MAPPING_SOURCE,
            identifier_mapping_unmatched_observation.c.mapping_fingerprint.in_(
                resolved_by_fingerprint
            ),
            identifier_mapping_unmatched_observation.c.resolution_status != "resolved",
        )
        .values(
            last_run_id=run_id,
            reason="resolved",
            resolution_status="resolved",
            resolved_instrument_id=case(
                resolved_by_fingerprint,
                value=identifier_mapping_unmatched_observation.c.mapping_fingerprint,
                else_=identifier_mapping_unmatched_observation.c.resolved_instrument_id,
            ),
            resolved_at=observed_at,
            last_seen_at=observed_at,
            updated_at=observed_at,
        )
    )
