"""Workflows for EODHD Bulk EOD rows that did not match instruments at ingest time."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from sqlalchemy import and_, bindparam, func, or_, select, tuple_, update
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.identity import (
    DatedInstrumentIdentityResolver,
    InstrumentIdentityResolution,
)
from fdp.sources.eodhd.prices import parse_daily_price_rows
from fdp.storage.tables import (
    DAILY_PRICE_TABLES,
    bulk_unmatched_daily_price_observation,
    instrument,
    instrument_identity_resolution_audit,
)
from fdp.storage.upsert import (
    build_daily_price_upsert,
    build_identity_resolution_audit_upsert,
)

ROUTABLE_ASSET_TYPES = {"stock", "etf", "fund", "index"}
REFRESHABLE_CLASSIFICATION_STATUSES = (
    "unresolved",
    "needs_instrument",
    "unknown",
    "ambiguous",
    "non_price_asset",
)
DEFAULT_CLASSIFICATION_STATUSES = ("unresolved",)
MENU_CLASSIFICATION_STATUSES = ("unresolved", "needs_instrument", "unknown")
ADVANCED_CLASSIFICATION_STATUSES = {"ambiguous", "non_price_asset"}


@dataclass(frozen=True)
class BulkUnmatchedSummaryRow:
    classification_status: str
    classified_asset_type: str | None
    row_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "classification_status": self.classification_status,
            "classified_asset_type": self.classified_asset_type,
            "row_count": self.row_count,
        }


@dataclass(frozen=True)
class BulkUnmatchedClassifyResult:
    scanned: int
    matched: int
    ambiguous: int
    needs_instrument: int
    non_price_asset: int
    unknown: int

    def to_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "matched": self.matched,
            "ambiguous": self.ambiguous,
            "needs_instrument": self.needs_instrument,
            "non_price_asset": self.non_price_asset,
            "unknown": self.unknown,
        }


@dataclass(frozen=True)
class BulkUnmatchedClassifySnapshot:
    """Frozen eligible counts and upper bounds for one classification run."""

    status_counts: dict[str, int]
    snapshot_max_by_status: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.status_counts.values())


@dataclass(frozen=True)
class BulkUnmatchedClassifyBatchResult:
    """Facts committed by one status-scoped keyset batch."""

    source_status: str
    scanned: int
    updated: int
    target_status_counts: dict[str, int]
    last_observation_id: int | None
    last_trade_date: date | None


@dataclass(frozen=True)
class BulkUnmatchedRouteFailure:
    """One retained route conflict that must be written as a quality issue."""

    observation_id: int
    instrument_id: int
    symbol: str
    provider_symbol: str
    trade_date: date
    asset_type: str
    reason: str
    issue_type: str = "identity_route_conflict"


@dataclass(frozen=True)
class BulkUnmatchedRouteResult:
    dry_run: bool
    routeable: int
    rows_inserted: int
    rows_rejected: int
    routed: int
    observations_selected: int = 0
    groups_selected: int = 0
    shadowed: int = 0
    route_failed: int = 0
    identity_audits: int = 0
    last_instrument_id: int | None = None
    last_trade_date: date | None = None
    route_failures: tuple[BulkUnmatchedRouteFailure, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "routeable": self.routeable,
            "rows_inserted": self.rows_inserted,
            "rows_rejected": self.rows_rejected,
            "routed": self.routed,
            "observations_selected": self.observations_selected,
            "groups_selected": self.groups_selected,
            "shadowed": self.shadowed,
            "route_failed": self.route_failed,
            "identity_audits": self.identity_audits,
            "last_instrument_id": self.last_instrument_id,
            "last_trade_date": (
                self.last_trade_date.isoformat() if self.last_trade_date else None
            ),
        }


def summarize_bulk_unmatched_observations(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str = "US",
) -> list[BulkUnmatchedSummaryRow]:
    """Summarize unmatched staging rows by classification status and asset type."""
    statement = (
        select(
            bulk_unmatched_daily_price_observation.c.classification_status,
            bulk_unmatched_daily_price_observation.c.classified_asset_type,
            func.count().label("row_count"),
        )
        .where(*_base_observation_conditions(date_from=date_from, date_to=date_to, market=market))
        .group_by(
            bulk_unmatched_daily_price_observation.c.classification_status,
            bulk_unmatched_daily_price_observation.c.classified_asset_type,
        )
        .order_by(
            bulk_unmatched_daily_price_observation.c.classification_status,
            bulk_unmatched_daily_price_observation.c.classified_asset_type,
        )
    )
    return [
        BulkUnmatchedSummaryRow(
            classification_status=str(row["classification_status"]),
            classified_asset_type=row["classified_asset_type"],
            row_count=int(row["row_count"]),
        )
        for row in connection.execute(statement).mappings()
    ]


def list_bulk_unmatched_observations(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str = "US",
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Return a bounded preview of unmatched staging rows for operator review."""
    conditions = _base_observation_conditions(date_from=date_from, date_to=date_to, market=market)
    if status:
        conditions.append(bulk_unmatched_daily_price_observation.c.classification_status == status)
    statement = (
        select(
            bulk_unmatched_daily_price_observation.c.observation_id,
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.provider_symbol,
            bulk_unmatched_daily_price_observation.c.symbol,
            bulk_unmatched_daily_price_observation.c.name,
            bulk_unmatched_daily_price_observation.c.eodhd_type,
            bulk_unmatched_daily_price_observation.c.classification_status,
            bulk_unmatched_daily_price_observation.c.classified_asset_type,
            bulk_unmatched_daily_price_observation.c.matched_instrument_id,
            bulk_unmatched_daily_price_observation.c.reason,
        )
        .where(*conditions)
        .order_by(
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.provider_symbol,
        )
        .limit(limit)
    )
    return [dict(row) for row in connection.execute(statement).mappings()]


def validate_classification_statuses(statuses: Iterable[str]) -> tuple[str, ...]:
    """Normalize and validate classifier input states before any database write."""
    normalized = tuple(dict.fromkeys(value.strip().lower() for value in statuses if value.strip()))
    if not normalized:
        raise ValueError("at least one classification status is required")
    unsupported = sorted(set(normalized) - set(REFRESHABLE_CLASSIFICATION_STATUSES))
    if unsupported:
        raise ValueError(
            "classification status cannot be refreshed: " + ", ".join(unsupported)
        )
    return tuple(
        status for status in REFRESHABLE_CLASSIFICATION_STATUSES if status in normalized
    )


def inspect_bulk_unmatched_classify_snapshot(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str = "US",
    statuses: Iterable[str] = DEFAULT_CLASSIFICATION_STATUSES,
    run_id: int | None = None,
) -> BulkUnmatchedClassifySnapshot:
    """Return eligible counts and max IDs without changing staging state."""
    normalized = validate_classification_statuses(statuses)
    conditions = [
        *_base_observation_conditions(date_from=date_from, date_to=date_to, market=market),
        bulk_unmatched_daily_price_observation.c.classification_status.in_(normalized),
    ]
    if run_id is not None:
        conditions.append(
            or_(
                bulk_unmatched_daily_price_observation.c.last_classified_run_id.is_(None),
                bulk_unmatched_daily_price_observation.c.last_classified_run_id != run_id,
            )
        )
    statement = (
        select(
            bulk_unmatched_daily_price_observation.c.classification_status,
            func.count().label("row_count"),
            func.max(bulk_unmatched_daily_price_observation.c.observation_id).label(
                "snapshot_max_observation_id"
            ),
        )
        .where(*conditions)
        .group_by(bulk_unmatched_daily_price_observation.c.classification_status)
    )
    rows = list(connection.execute(statement).mappings())
    counts = {status: 0 for status in normalized}
    maxima = {status: 0 for status in normalized}
    for row in rows:
        status = str(row["classification_status"])
        counts[status] = int(row["row_count"])
        maxima[status] = int(row["snapshot_max_observation_id"] or 0)
    return BulkUnmatchedClassifySnapshot(
        status_counts=counts,
        snapshot_max_by_status=maxima,
    )


def classify_bulk_unmatched_batch(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    source_status: str,
    snapshot_max_observation_id: int,
    run_id: int,
    market: str = "US",
    after_trade_date: date | None = None,
    after_observation_id: int = 0,
    batch_size: int = 5_000,
    identity_resolver: DatedInstrumentIdentityResolver,
) -> BulkUnmatchedClassifyBatchResult:
    """Classify one stable keyset batch and mark every row with the workflow run."""
    normalized = validate_classification_statuses([source_status])[0]
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if after_observation_id and after_trade_date is None:
        raise ValueError("after_trade_date is required with a non-zero observation cursor")
    cursor_condition = (
        or_(
            bulk_unmatched_daily_price_observation.c.trade_date > after_trade_date,
            and_(
                bulk_unmatched_daily_price_observation.c.trade_date == after_trade_date,
                bulk_unmatched_daily_price_observation.c.observation_id
                > after_observation_id,
            ),
        )
        if after_trade_date is not None
        else None
    )
    conditions = [
        *_base_observation_conditions(date_from=date_from, date_to=date_to, market=market),
        bulk_unmatched_daily_price_observation.c.classification_status == normalized,
        bulk_unmatched_daily_price_observation.c.observation_id
        <= snapshot_max_observation_id,
        or_(
            bulk_unmatched_daily_price_observation.c.last_classified_run_id.is_(None),
            bulk_unmatched_daily_price_observation.c.last_classified_run_id != run_id,
        ),
    ]
    if cursor_condition is not None:
        conditions.append(cursor_condition)
    statement = (
        select(
            bulk_unmatched_daily_price_observation.c.observation_id,
            bulk_unmatched_daily_price_observation.c.provider_symbol,
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.eodhd_type,
        )
        .where(*conditions)
        .with_hint(
            bulk_unmatched_daily_price_observation,
            "FORCE INDEX (ix_bulk_unmatched_market_status_date_id)",
            dialect_name="mysql",
        )
        .order_by(
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.observation_id,
        )
        .limit(batch_size)
    )
    rows = [dict(row) for row in connection.execute(statement).mappings()]
    decisions = _classify_rows(rows, identity_resolver=identity_resolver)
    if decisions:
        update_statement = (
            update(bulk_unmatched_daily_price_observation)
            .where(
                bulk_unmatched_daily_price_observation.c.observation_id
                == bindparam("p_observation_id"),
                bulk_unmatched_daily_price_observation.c.classification_status
                == bindparam("p_source_status"),
            )
            .values(
                classification_status=bindparam("p_target_status"),
                classified_asset_type=bindparam("p_asset_type"),
                matched_instrument_id=bindparam("p_instrument_id"),
                reason=bindparam("p_reason"),
                last_classified_run_id=run_id,
                updated_at=func.current_timestamp(),
            )
        )
        parameters = [
            {
                "p_observation_id": decision["observation_id"],
                "p_source_status": normalized,
                "p_target_status": decision["classification_status"],
                "p_asset_type": decision["classified_asset_type"],
                "p_instrument_id": decision["matched_instrument_id"],
                "p_reason": decision["reason"],
            }
            for decision in decisions
        ]
        execution = connection.execute(update_statement, parameters)
        rowcount = getattr(execution, "rowcount", None)
        if rowcount not in (None, -1, len(decisions)):
            raise RuntimeError(
                "classification batch changed concurrently: "
                f"selected={len(decisions)} updated={rowcount}"
            )
    counts = Counter(str(row["classification_status"]) for row in decisions)
    last_row = rows[-1] if rows else None
    return BulkUnmatchedClassifyBatchResult(
        source_status=normalized,
        scanned=len(rows),
        updated=len(decisions),
        target_status_counts=dict(sorted(counts.items())),
        last_observation_id=(int(last_row["observation_id"]) if last_row else None),
        last_trade_date=(last_row["trade_date"] if last_row else None),
    )


def classify_bulk_unmatched_observations(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str = "US",
    limit: int | None = None,
    identity_resolver: DatedInstrumentIdentityResolver | None = None,
) -> BulkUnmatchedClassifyResult:
    """Classify unresolved rows with the same dated identity contract as Bulk ingest."""
    active_resolver = identity_resolver or DatedInstrumentIdentityResolver.from_connection(
        connection,
        market=market,
        asset_types=sorted(ROUTABLE_ASSET_TYPES),
        instrument_status="all",
    )
    statement = (
        select(
            bulk_unmatched_daily_price_observation.c.observation_id,
            bulk_unmatched_daily_price_observation.c.provider_symbol,
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.eodhd_type,
        )
        .where(
            *_base_observation_conditions(date_from=date_from, date_to=date_to, market=market),
            bulk_unmatched_daily_price_observation.c.classification_status == "unresolved",
        )
        .order_by(
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.provider_symbol,
        )
    )
    if limit is not None:
        statement = statement.limit(limit)

    rows = [dict(row) for row in connection.execute(statement).mappings()]
    decisions = _classify_rows(rows, identity_resolver=active_resolver)
    counts = Counter(str(row["classification_status"]) for row in decisions)
    for decision in decisions:
        connection.execute(
            update(bulk_unmatched_daily_price_observation)
            .where(
                bulk_unmatched_daily_price_observation.c.observation_id
                == decision["observation_id"]
            )
            .values(
                classification_status=decision["classification_status"],
                classified_asset_type=decision["classified_asset_type"],
                matched_instrument_id=decision["matched_instrument_id"],
                reason=decision["reason"],
                updated_at=func.current_timestamp(),
            )
        )

    return BulkUnmatchedClassifyResult(
        scanned=len(decisions),
        matched=counts["matched"],
        ambiguous=counts["ambiguous"],
        needs_instrument=counts["needs_instrument"],
        non_price_asset=counts["non_price_asset"],
        unknown=counts["unknown"],
    )


def route_bulk_unmatched_observations(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str = "US",
    asset_types: list[str] | None = None,
    dry_run: bool = True,
    limit: int | None = None,
    run_id: int | None = None,
) -> BulkUnmatchedRouteResult:
    """Route complete instrument/date groups under the identity-confidence policy.

    Input: one market/date scope and a maximum number of complete natural-key groups.
    Output: routed, shadowed, rejected, and audit counts for exactly that batch.
    Flow: group keys -> all aliases -> identity winner -> overwrite guard -> atomic writes.
    """
    selected_asset_types = asset_types or sorted(ROUTABLE_ASSET_TYPES)
    unsupported = sorted(set(selected_asset_types) - ROUTABLE_ASSET_TYPES)
    if unsupported:
        raise ValueError(f"unsupported asset type(s): {', '.join(unsupported)}")
    if limit is not None and limit <= 0:
        raise ValueError("route group limit must be positive")
    if not dry_run and (run_id is None or run_id <= 0):
        raise ValueError("executed route requires a positive reconcile run_id")

    group_keys = _select_route_group_keys(
        connection,
        date_from=date_from,
        date_to=date_to,
        market=market,
        asset_types=selected_asset_types,
        limit=limit,
    )
    if not group_keys:
        return BulkUnmatchedRouteResult(
            dry_run=dry_run,
            routeable=0,
            rows_inserted=0,
            rows_rejected=0,
            routed=0,
        )
    rows = _load_route_group_rows(
        connection,
        date_from=date_from,
        date_to=date_to,
        market=market,
        asset_types=selected_asset_types,
        group_keys=group_keys,
    )
    selected_rows, suppressed_rows = _select_route_rows(rows)
    existing_rows = _load_existing_canonical_rows(connection, selected_rows)
    existing_audits = _load_existing_identity_audits(
        connection,
        market=market,
        selected_rows=selected_rows,
        existing_rows=existing_rows,
    )
    accepted_by_asset_type: dict[str, list[dict[str, object]]] = {}
    routed_ids: list[int] = []
    audit_rows: list[dict[str, object]] = []
    failure_issue_types: dict[int, str] = {}
    for row in selected_rows:
        parsed = parse_daily_price_rows(
            [{
                "date": row["trade_date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "adjusted_close": row["adjusted_close"],
                "volume": row["volume"],
            }],
            instrument_id=int(row["instrument_id"]),
            symbol=str(row["observed_symbol"]),
            provider_symbol=str(row["observed_provider_symbol"]),
            currency=str(row["currency"]),
        )
        if parsed.rejected:
            reason = "; ".join(rejected.reason for rejected in parsed.rejected)
            suppressed_rows.append((row, "route_failed", reason or "route_failed"))
            failure_issue_types[int(row["observation_id"])] = (
                "invalid_ohlcv" if "invalid_ohlcv:" in reason else "api_rejected_row"
            )
            continue
        resolution = _route_identity_resolution(row)
        if resolution is None:
            suppressed_rows.append(
                (
                    row,
                    "route_failed",
                    "unsupported_identity_evidence_for_route;"
                    f"classification_reason={row.get('classification_reason')}",
                )
            )
            continue
        natural_key = (int(row["instrument_id"]), row["trade_date"])
        allowed, supersedes_audit_id, conflict_reason = _canonical_overwrite_decision(
            row=row,
            resolution=resolution,
            existing_row=existing_rows.get(natural_key),
            existing_audits=existing_audits,
        )
        if not allowed:
            suppressed_rows.append((row, "route_failed", conflict_reason))
            continue
        asset_type = str(row["asset_type"])
        accepted_by_asset_type.setdefault(asset_type, []).extend(parsed.accepted)
        routed_ids.append(int(row["observation_id"]))
        audit_rows.append(
            resolution.audit_row(
                provider_symbol=str(row["observed_provider_symbol"]),
                trade_date=row["trade_date"],
                run_id=int(run_id or 0),
                market=market,
                supersedes_audit_id=supersedes_audit_id,
            )
        )

    shadowed_count = sum(status == "shadowed" for _, status, _ in suppressed_rows)
    route_failed_count = sum(status == "route_failed" for _, status, _ in suppressed_rows)
    route_failures = tuple(
        BulkUnmatchedRouteFailure(
            observation_id=int(row["observation_id"]),
            instrument_id=int(row["instrument_id"]),
            symbol=str(row["observed_symbol"]),
            provider_symbol=str(row["observed_provider_symbol"]),
            trade_date=row["trade_date"],
            asset_type=str(row["asset_type"]),
            reason=reason,
            issue_type=failure_issue_types.get(
                int(row["observation_id"]),
                "identity_route_conflict",
            ),
        )
        for row, status, reason in suppressed_rows
        if status == "route_failed"
    )
    last_instrument_id, last_trade_date = group_keys[-1]
    observations_selected = len(rows)
    closed_observations = len(routed_ids) + shadowed_count + route_failed_count
    if observations_selected != closed_observations:
        raise RuntimeError(
            "route observation closure failed: "
            f"selected={observations_selected} routed={len(routed_ids)} "
            f"shadowed={shadowed_count} failed={route_failed_count}"
        )
    if dry_run:
        return BulkUnmatchedRouteResult(
            dry_run=True,
            routeable=len(routed_ids),
            rows_inserted=0,
            rows_rejected=len(suppressed_rows),
            routed=0,
            observations_selected=observations_selected,
            groups_selected=len(group_keys),
            shadowed=shadowed_count,
            route_failed=route_failed_count,
            identity_audits=len(audit_rows),
            last_instrument_id=last_instrument_id,
            last_trade_date=last_trade_date,
            route_failures=route_failures,
        )

    _mark_suppressed_route_rows(connection, suppressed_rows)
    rows_inserted = 0
    for asset_type, price_rows in accepted_by_asset_type.items():
        connection.execute(build_daily_price_upsert(asset_type, price_rows))
        rows_inserted += len(price_rows)
    if audit_rows:
        connection.execute(build_identity_resolution_audit_upsert(audit_rows))
    if routed_ids:
        connection.execute(
            update(bulk_unmatched_daily_price_observation)
            .where(bulk_unmatched_daily_price_observation.c.observation_id.in_(routed_ids))
            .values(
                classification_status="routed",
                reason="routed_to_price_table",
                updated_at=func.current_timestamp(),
            )
        )

    return BulkUnmatchedRouteResult(
        dry_run=False,
        routeable=len(routed_ids),
        rows_inserted=rows_inserted,
        rows_rejected=len(suppressed_rows),
        routed=len(routed_ids),
        observations_selected=observations_selected,
        groups_selected=len(group_keys),
        shadowed=shadowed_count,
        route_failed=route_failed_count,
        identity_audits=len(audit_rows),
        last_instrument_id=last_instrument_id,
        last_trade_date=last_trade_date,
        route_failures=route_failures,
    )


def count_bulk_unmatched_route_groups(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str = "US",
    asset_types: list[str] | None = None,
) -> int:
    """Count complete matched natural-key groups remaining in one route scope."""
    selected_asset_types = asset_types or sorted(ROUTABLE_ASSET_TYPES)
    unsupported = sorted(set(selected_asset_types) - ROUTABLE_ASSET_TYPES)
    if unsupported:
        raise ValueError(f"unsupported asset type(s): {', '.join(unsupported)}")
    grouped = (
        select(
            bulk_unmatched_daily_price_observation.c.matched_instrument_id,
            bulk_unmatched_daily_price_observation.c.trade_date,
        )
        .select_from(
            bulk_unmatched_daily_price_observation.join(
                instrument,
                bulk_unmatched_daily_price_observation.c.matched_instrument_id
                == instrument.c.instrument_id,
            )
        )
        .where(
            *_base_observation_conditions(
                date_from=date_from,
                date_to=date_to,
                market=market,
            ),
            bulk_unmatched_daily_price_observation.c.classification_status == "matched",
            instrument.c.asset_type.in_(selected_asset_types),
        )
        .group_by(
            bulk_unmatched_daily_price_observation.c.matched_instrument_id,
            bulk_unmatched_daily_price_observation.c.trade_date,
        )
        .subquery()
    )
    return int(connection.execute(select(func.count()).select_from(grouped)).scalar_one())


def _select_route_group_keys(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str,
    asset_types: list[str],
    limit: int | None,
) -> list[tuple[int, date]]:
    """Select complete route units before loading any candidate alias rows."""
    statement = (
        select(
            bulk_unmatched_daily_price_observation.c.matched_instrument_id.label(
                "instrument_id"
            ),
            bulk_unmatched_daily_price_observation.c.trade_date,
        )
        .select_from(
            bulk_unmatched_daily_price_observation.join(
                instrument,
                bulk_unmatched_daily_price_observation.c.matched_instrument_id
                == instrument.c.instrument_id,
            )
        )
        .where(
            *_base_observation_conditions(
                date_from=date_from,
                date_to=date_to,
                market=market,
            ),
            bulk_unmatched_daily_price_observation.c.classification_status == "matched",
            instrument.c.asset_type.in_(asset_types),
        )
        .group_by(
            bulk_unmatched_daily_price_observation.c.matched_instrument_id,
            bulk_unmatched_daily_price_observation.c.trade_date,
        )
        .order_by(
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.matched_instrument_id,
        )
    )
    if limit is not None:
        statement = statement.limit(limit)
    return [
        (int(row["instrument_id"]), row["trade_date"])
        for row in connection.execute(statement).mappings()
    ]


def _load_route_group_rows(
    connection: Connection,
    *,
    date_from: date,
    date_to: date,
    market: str,
    asset_types: list[str],
    group_keys: list[tuple[int, date]],
) -> list[dict[str, object]]:
    """Load every staged alias for the selected natural-key groups."""
    statement = (
        select(
            bulk_unmatched_daily_price_observation.c.observation_id,
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.open,
            bulk_unmatched_daily_price_observation.c.high,
            bulk_unmatched_daily_price_observation.c.low,
            bulk_unmatched_daily_price_observation.c.close,
            bulk_unmatched_daily_price_observation.c.adjusted_close,
            bulk_unmatched_daily_price_observation.c.volume,
            bulk_unmatched_daily_price_observation.c.symbol.label("observed_symbol"),
            bulk_unmatched_daily_price_observation.c.provider_symbol.label(
                "observed_provider_symbol"
            ),
            bulk_unmatched_daily_price_observation.c.reason.label("classification_reason"),
            instrument.c.instrument_id,
            instrument.c.asset_type,
            instrument.c.currency,
        )
        .select_from(
            bulk_unmatched_daily_price_observation.join(
                instrument,
                bulk_unmatched_daily_price_observation.c.matched_instrument_id
                == instrument.c.instrument_id,
            )
        )
        .where(
            *_base_observation_conditions(
                date_from=date_from,
                date_to=date_to,
                market=market,
            ),
            bulk_unmatched_daily_price_observation.c.classification_status == "matched",
            instrument.c.asset_type.in_(asset_types),
            tuple_(
                bulk_unmatched_daily_price_observation.c.matched_instrument_id,
                bulk_unmatched_daily_price_observation.c.trade_date,
            ).in_(group_keys),
        )
        .order_by(
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.matched_instrument_id,
            bulk_unmatched_daily_price_observation.c.provider_symbol,
        )
    )
    return [dict(row) for row in connection.execute(statement).mappings()]


def _load_existing_canonical_rows(
    connection: Connection,
    selected_rows: list[dict[str, object]],
) -> dict[tuple[int, date], dict[str, object]]:
    """Load existing canonical symbols so overwrites can be evidence-gated."""
    keys_by_asset: dict[str, set[tuple[int, date]]] = {}
    for row in selected_rows:
        keys_by_asset.setdefault(str(row["asset_type"]), set()).add(
            (int(row["instrument_id"]), row["trade_date"])
        )
    existing: dict[tuple[int, date], dict[str, object]] = {}
    for asset_type, keys in keys_by_asset.items():
        table = DAILY_PRICE_TABLES[asset_type]
        statement = select(
            table.c.instrument_id,
            table.c.trade_date,
            table.c.provider_symbol,
        ).where(tuple_(table.c.instrument_id, table.c.trade_date).in_(sorted(keys)))
        for row in connection.execute(statement).mappings():
            existing[(int(row["instrument_id"]), row["trade_date"])] = dict(row)
    return existing


def _load_existing_identity_audits(
    connection: Connection,
    *,
    market: str,
    selected_rows: list[dict[str, object]],
    existing_rows: dict[tuple[int, date], dict[str, object]],
) -> dict[tuple[int, str], list[dict[str, object]]]:
    """Load only audit evidence needed for provider-symbol replacement checks."""
    pairs: set[tuple[int, str]] = set()
    for row in selected_rows:
        key = (int(row["instrument_id"]), row["trade_date"])
        existing = existing_rows.get(key)
        if existing is None:
            continue
        existing_symbol = str(existing["provider_symbol"]).upper()
        incoming_symbol = str(row["observed_provider_symbol"]).upper()
        if existing_symbol != incoming_symbol:
            pairs.add((int(row["instrument_id"]), existing_symbol))
    if not pairs:
        return {}
    statement = select(
        instrument_identity_resolution_audit.c.audit_id,
        instrument_identity_resolution_audit.c.instrument_id,
        instrument_identity_resolution_audit.c.provider_symbol,
        instrument_identity_resolution_audit.c.confidence,
        instrument_identity_resolution_audit.c.observed_from,
        instrument_identity_resolution_audit.c.observed_to,
    ).where(
        instrument_identity_resolution_audit.c.market == market,
        instrument_identity_resolution_audit.c.source == "EODHD",
        tuple_(
            instrument_identity_resolution_audit.c.instrument_id,
            instrument_identity_resolution_audit.c.provider_symbol,
        ).in_(sorted(pairs)),
    )
    grouped: dict[tuple[int, str], list[dict[str, object]]] = {}
    for row in connection.execute(statement).mappings():
        key = (int(row["instrument_id"]), str(row["provider_symbol"]).upper())
        grouped.setdefault(key, []).append(dict(row))
    return grouped


def _route_identity_resolution(
    row: dict[str, object],
) -> InstrumentIdentityResolution | None:
    reason = row.get("classification_reason")
    if reason == "identifier_history_match":
        return InstrumentIdentityResolution(
            instrument=row,
            matched_by="identifier_history",
            reason=None,
            confidence="high",
            evidence_type="dated_provider_symbol_history",
        )
    if reason == "current_provider_symbol_match":
        return InstrumentIdentityResolution(
            instrument=row,
            matched_by="current_provider_symbol",
            reason=None,
            confidence="medium",
            evidence_type="unique_current_provider_symbol",
        )
    return None


def _canonical_overwrite_decision(
    *,
    row: dict[str, object],
    resolution: InstrumentIdentityResolution,
    existing_row: dict[str, object] | None,
    existing_audits: dict[tuple[int, str], list[dict[str, object]]],
) -> tuple[bool, int | None, str]:
    """Allow refreshes; allow replacements only when high supersedes audited medium."""
    if existing_row is None:
        return True, None, "new_canonical_row"
    incoming_symbol = str(row["observed_provider_symbol"]).upper()
    existing_symbol = str(existing_row["provider_symbol"]).upper()
    if incoming_symbol == existing_symbol:
        return True, None, "same_provider_symbol_refresh"
    if resolution.confidence != "high":
        return (
            False,
            None,
            "canonical_provider_symbol_conflict;incoming_confidence_not_high;"
            f"existing={existing_symbol};incoming={incoming_symbol}",
        )

    audit_candidates = existing_audits.get(
        (int(row["instrument_id"]), existing_symbol),
        [],
    )
    trade_date = row["trade_date"]
    applicable = [
        audit
        for audit in audit_candidates
        if audit["observed_from"] <= trade_date <= audit["observed_to"]
    ]
    applicable.sort(
        key=lambda audit: (
            1 if audit["confidence"] == "high" else 0,
            int(audit["audit_id"]),
        ),
        reverse=True,
    )
    existing_audit = applicable[0] if applicable else None
    if existing_audit is not None and existing_audit["confidence"] == "medium":
        return True, int(existing_audit["audit_id"]), "high_supersedes_medium"
    existing_confidence = (
        str(existing_audit["confidence"]) if existing_audit is not None else "unknown"
    )
    return (
        False,
        None,
        "canonical_provider_symbol_conflict;existing_confidence_not_medium;"
        f"existing={existing_symbol};incoming={incoming_symbol};"
        f"existing_confidence={existing_confidence}",
    )


def _select_route_rows(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[tuple[dict[str, object], str, str]]]:
    """Apply dated-history precedence before routing staged rows to natural keys."""
    grouped: dict[tuple[int, date], list[dict[str, object]]] = {}
    for row in rows:
        key = (int(row["instrument_id"]), row["trade_date"])
        grouped.setdefault(key, []).append(row)

    selected: list[dict[str, object]] = []
    suppressed: list[tuple[dict[str, object], str, str]] = []
    for (instrument_id, trade_date), group in grouped.items():
        if len(group) == 1:
            selected.append(group[0])
            continue
        dated = [
            row
            for row in group
            if row.get("classification_reason") == "identifier_history_match"
        ]
        if len(dated) == 1:
            winner = dated[0]
            selected.append(winner)
            reason = (
                "shadowed_by_dated_identifier_history;"
                f"instrument_id={instrument_id};trade_date={trade_date};"
                f"selected_observation_id={winner['observation_id']}"
            )
            suppressed.extend(
                (row, "shadowed", reason) for row in group if row is not winner
            )
            continue
        provider_symbols = ",".join(
            sorted({str(row["observed_provider_symbol"]) for row in group})
        )
        reason = (
            "ambiguous_provider_aliases_for_instrument_date;"
            f"instrument_id={instrument_id};trade_date={trade_date};"
            f"candidate_provider_symbols={provider_symbols}"
        )
        suppressed.extend((row, "route_failed", reason) for row in group)

    return selected, suppressed


def _mark_suppressed_route_rows(
    connection: Connection,
    rows: list[tuple[dict[str, object], str, str]],
) -> None:
    grouped: dict[tuple[str, str], list[int]] = {}
    for row, status, reason in rows:
        grouped.setdefault((status, reason), []).append(int(row["observation_id"]))
    for (status, reason), observation_ids in grouped.items():
        connection.execute(
            update(bulk_unmatched_daily_price_observation)
            .where(bulk_unmatched_daily_price_observation.c.observation_id.in_(observation_ids))
            .values(
                classification_status=status,
                reason=reason,
                updated_at=func.current_timestamp(),
            )
        )


def _base_observation_conditions(
    *,
    date_from: date,
    date_to: date,
    market: str,
) -> list[Any]:
    return [
        bulk_unmatched_daily_price_observation.c.market == market,
        bulk_unmatched_daily_price_observation.c.trade_date >= date_from,
        bulk_unmatched_daily_price_observation.c.trade_date <= date_to,
    ]


def _classify_rows(
    rows: list[dict[str, object]],
    *,
    identity_resolver: DatedInstrumentIdentityResolver,
) -> list[dict[str, object]]:
    decisions: list[dict[str, object]] = []
    for row in rows:
        type_bucket = _bucket_eodhd_type(row["eodhd_type"])
        resolution = identity_resolver.resolve(
            provider_symbol=str(row["provider_symbol"]),
            trade_date=row["trade_date"],
            eodhd_type=row["eodhd_type"],
        )
        status, asset_type, matched_id, reason = _classification_decision(
            type_bucket=type_bucket,
            resolution=resolution,
        )
        decisions.append(
            {
                "observation_id": int(row["observation_id"]),
                "classification_status": status,
                "classified_asset_type": asset_type,
                "matched_instrument_id": matched_id,
                "reason": reason,
            }
        )
    return decisions


def _classification_decision(
    *,
    type_bucket: str | None,
    resolution: InstrumentIdentityResolution,
) -> tuple[str, str | None, int | None, str]:
    if type_bucket in {"preferred", "other"}:
        return "non_price_asset", type_bucket, None, f"non_price_eodhd_type:{type_bucket}"
    instrument_row = resolution.instrument
    if instrument_row is not None:
        asset_type = str(instrument_row["asset_type"])
        if asset_type in ROUTABLE_ASSET_TYPES:
            return (
                "matched",
                asset_type,
                int(instrument_row["instrument_id"]),
                f"{resolution.matched_by}_match",
            )
        return "non_price_asset", asset_type, int(instrument_row["instrument_id"]), "non_price_asset"
    if resolution.reason and resolution.reason.startswith("ambiguous_"):
        return "ambiguous", type_bucket or "unknown", None, _resolution_reason(resolution)
    if resolution.reason == "identifier_not_valid_on_trade_date":
        return "ambiguous", type_bucket or "unknown", None, _resolution_reason(resolution)
    if type_bucket in ROUTABLE_ASSET_TYPES:
        return "needs_instrument", type_bucket, None, _resolution_reason(resolution)
    return "unknown", type_bucket or "unknown", None, _resolution_reason(resolution)


def _resolution_reason(resolution: InstrumentIdentityResolution) -> str:
    reason = resolution.reason or "unresolved_instrument_identity"
    if not resolution.candidate_instrument_ids:
        return str(reason)
    candidates = ",".join(str(value) for value in resolution.candidate_instrument_ids)
    return f"{reason};candidate_instrument_ids={candidates}"


def _bucket_eodhd_type(value: object) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    if normalized in {"common stock", "stock"}:
        return "stock"
    if normalized == "etf":
        return "etf"
    if normalized == "index":
        return "index"
    if "fund" in normalized:
        return "fund"
    if "preferred" in normalized or "preference" in normalized:
        return "preferred"
    if any(token in normalized for token in ("note", "bond", "unit", "warrant", "right")):
        return "other"
    return "unknown"
