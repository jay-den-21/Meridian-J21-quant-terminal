"""Point-in-time instrument identity resolution for EODHD Bulk EOD rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.instruments import normalize_eodhd_asset_type
from fdp.storage.tables import instrument, instrument_identifier_history

IdentityMatchSource = Literal["identifier_history", "current_provider_symbol"]
IdentityConfidence = Literal["high", "medium"]
InstrumentStatus = Literal["active", "inactive", "all"]
IDENTITY_RESOLVER_VERSION = "bulk-v1"


@dataclass(frozen=True)
class InstrumentIdentityResolution:
    """Result of resolving one observed provider symbol on one trading date."""

    instrument: dict[str, object] | None
    matched_by: IdentityMatchSource | None
    reason: str | None
    candidate_instrument_ids: tuple[int, ...] = ()
    confidence: IdentityConfidence | None = None
    evidence_type: str | None = None
    resolver_version: str = IDENTITY_RESOLVER_VERSION

    def audit_row(
        self,
        *,
        provider_symbol: str,
        trade_date: date,
        run_id: int,
        market: str,
        source: str = "EODHD",
        supersedes_audit_id: int | None = None,
    ) -> dict[str, object]:
        """Build one aggregate identity-audit input for a resolved Bulk row."""
        if self.instrument is None or self.matched_by is None or self.confidence is None:
            raise ValueError("only resolved identities can produce an audit row")
        if self.evidence_type is None:
            raise ValueError("resolved identity is missing evidence_type")
        return {
            "instrument_id": int(self.instrument["instrument_id"]),
            "provider_symbol": provider_symbol.strip().upper(),
            "market": market.upper(),
            "source": source,
            "match_method": self.matched_by,
            "confidence": self.confidence,
            "evidence_type": self.evidence_type,
            "resolver_version": self.resolver_version,
            "observed_from": trade_date,
            "observed_to": trade_date,
            "first_run_id": run_id,
            "last_run_id": run_id,
            "reason": _resolved_reason(self),
            "supersedes_audit_id": supersedes_audit_id,
        }


class DatedInstrumentIdentityResolver:
    """Resolve Bulk EOD identity without guessing from company name or ticker text.

    Input: current instrument rows, dated provider-symbol history, and allowed asset types.
    Output: one exact instrument row or an explicit unresolved/ambiguous reason.
    Flow: dated history -> current provider symbol -> type compatibility -> instrument id.
    """

    def __init__(
        self,
        *,
        current_rows: list[dict[str, object]],
        history_rows: list[dict[str, object]],
        asset_types: list[str],
    ) -> None:
        self._asset_types = set(asset_types)
        self._current_by_provider_symbol = _group_by_provider_symbol(current_rows)
        self._history_by_provider_symbol = _group_by_history_value(history_rows)

    @classmethod
    def from_connection(
        cls,
        connection: Connection,
        *,
        market: str,
        asset_types: list[str],
        instrument_status: InstrumentStatus,
    ) -> "DatedInstrumentIdentityResolver":
        """Load one market-scoped identity snapshot for a single Bulk response."""
        status_conditions = _instrument_status_conditions(instrument_status)
        instrument_conditions = [
            instrument.c.market == market,
            instrument.c.provider == "EODHD",
            instrument.c.asset_type.in_(asset_types),
            *status_conditions,
        ]
        columns = (
            instrument.c.instrument_id,
            instrument.c.symbol,
            instrument.c.provider_symbol,
            instrument.c.asset_type,
            instrument.c.currency,
            instrument.c.listed_date,
            instrument.c.delisted_date,
        )
        current_rows = [
            dict(row)
            for row in connection.execute(select(*columns).where(*instrument_conditions)).mappings()
        ]
        history_rows = [
            dict(row)
            for row in connection.execute(
                select(
                    *columns,
                    instrument_identifier_history.c.id_value,
                    instrument_identifier_history.c.valid_from,
                    instrument_identifier_history.c.valid_to,
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
                    *instrument_conditions,
                )
            ).mappings()
        ]
        return cls(
            current_rows=current_rows,
            history_rows=history_rows,
            asset_types=asset_types,
        )

    def resolve(
        self,
        *,
        provider_symbol: str,
        trade_date: date,
        eodhd_type: object,
    ) -> InstrumentIdentityResolution:
        """Return one date/type-compatible identity or a reason suitable for staging."""
        normalized_provider_symbol = provider_symbol.strip().upper()
        observed_asset_type = normalize_eodhd_asset_type(eodhd_type)
        provider_type_missing = _provider_type_is_missing(eodhd_type)
        if observed_asset_type is None and not provider_type_missing:
            return _unresolved("unsupported_eodhd_type")
        if observed_asset_type is not None and observed_asset_type not in self._asset_types:
            return _unresolved(f"asset_type_not_selected:{observed_asset_type}")

        all_history = self._history_by_provider_symbol.get(normalized_provider_symbol, [])
        authoritative_history = [row for row in all_history if _has_validity_bound(row)]
        dated_history = [
            row for row in authoritative_history if _is_valid_on(row, trade_date)
        ]
        if dated_history:
            return _resolve_candidates(
                dated_history,
                observed_asset_type=observed_asset_type,
                matched_by="identifier_history",
                confidence="high",
                evidence_type="dated_provider_symbol_history",
                mismatch_reason="identifier_history_asset_type_mismatch",
                ambiguous_reason="ambiguous_identifier_history",
            )

        current_candidates = self._current_by_provider_symbol.get(normalized_provider_symbol, [])
        if authoritative_history and current_candidates:
            if provider_type_missing:
                return _unresolved(
                    "identifier_not_valid_on_trade_date",
                    candidate_rows=[*authoritative_history, *current_candidates],
                )
            historical_types = {str(row["asset_type"]) for row in authoritative_history}
            current_types = {str(row["asset_type"]) for row in current_candidates}
            if (
                observed_asset_type is not None
                and observed_asset_type in historical_types
                and observed_asset_type in current_types
            ):
                return _unresolved(
                    "identifier_not_valid_on_trade_date",
                    candidate_rows=[*authoritative_history, *current_candidates],
                )

        if current_candidates:
            return _resolve_candidates(
                current_candidates,
                observed_asset_type=observed_asset_type,
                matched_by="current_provider_symbol",
                confidence="medium",
                evidence_type="unique_current_provider_symbol",
                mismatch_reason="current_provider_symbol_asset_type_mismatch",
                ambiguous_reason="ambiguous_current_provider_symbol",
            )
        if authoritative_history:
            return _unresolved(
                "identifier_not_valid_on_trade_date",
                candidate_rows=authoritative_history,
            )
        if all_history:
            candidate_ids = {int(row["instrument_id"]) for row in all_history}
            reason = (
                "ambiguous_identifier_history"
                if len(candidate_ids) > 1
                else "undated_identifier_history_not_authoritative"
            )
            return _unresolved(reason, candidate_rows=all_history)
        return _unresolved("provider_symbol_not_found")


def _instrument_status_conditions(instrument_status: InstrumentStatus) -> list[Any]:
    if instrument_status == "active":
        return [instrument.c.is_active.is_(True)]
    if instrument_status == "inactive":
        return [instrument.c.is_active.is_(False)]
    if instrument_status == "all":
        return []
    raise ValueError("instrument_status must be active, inactive, or all")


def _group_by_provider_symbol(
    rows: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        key = str(row["provider_symbol"]).upper()
        grouped.setdefault(key, []).append(row)
    return grouped


def _group_by_history_value(
    rows: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        key = str(row["id_value"]).upper()
        grouped.setdefault(key, []).append(row)
    return grouped


def _is_valid_on(row: dict[str, object], trade_date: date) -> bool:
    valid_from = row.get("valid_from")
    valid_to = row.get("valid_to")
    return (valid_from is None or valid_from <= trade_date) and (
        valid_to is None or trade_date <= valid_to
    )


def _has_validity_bound(row: dict[str, object]) -> bool:
    return row.get("valid_from") is not None or row.get("valid_to") is not None


def _resolve_candidates(
    rows: list[dict[str, object]],
    *,
    observed_asset_type: str | None,
    matched_by: IdentityMatchSource,
    confidence: IdentityConfidence,
    evidence_type: str,
    mismatch_reason: str,
    ambiguous_reason: str,
) -> InstrumentIdentityResolution:
    compatible_by_id = {
        int(row["instrument_id"]): row
        for row in rows
        if observed_asset_type is None or row["asset_type"] == observed_asset_type
    }
    if not compatible_by_id:
        return _unresolved(mismatch_reason, candidate_rows=rows)
    if len(compatible_by_id) > 1:
        return _unresolved(ambiguous_reason, candidate_rows=list(compatible_by_id.values()))
    return InstrumentIdentityResolution(
        instrument=next(iter(compatible_by_id.values())),
        matched_by=matched_by,
        reason=None,
        confidence=confidence,
        evidence_type=evidence_type,
    )


def _provider_type_is_missing(value: object) -> bool:
    return value is None or not str(value).strip()


def _unresolved(
    reason: str,
    *,
    candidate_rows: list[dict[str, object]] | None = None,
) -> InstrumentIdentityResolution:
    candidate_ids = tuple(
        sorted({int(row["instrument_id"]) for row in candidate_rows or []})
    )
    return InstrumentIdentityResolution(
        instrument=None,
        matched_by=None,
        reason=reason,
        candidate_instrument_ids=candidate_ids,
    )


def _resolved_reason(resolution: InstrumentIdentityResolution) -> str:
    if resolution.matched_by == "identifier_history":
        return "dated identifier history winner"
    if resolution.matched_by == "current_provider_symbol":
        return "unique current provider symbol without dated conflict"
    raise ValueError("resolved identity has no supported match method")
