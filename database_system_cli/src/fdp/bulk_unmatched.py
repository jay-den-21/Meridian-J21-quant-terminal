"""Workflows for EODHD Bulk EOD rows that did not match instruments at ingest time."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.identity import (
    DatedInstrumentIdentityResolver,
    InstrumentIdentityResolution,
)
from fdp.sources.eodhd.prices import RejectedDailyPriceRow, parse_daily_price_rows
from fdp.storage.tables import (
    bulk_unmatched_daily_price_observation,
    instrument,
)
from fdp.storage.upsert import build_daily_price_upsert

ROUTABLE_ASSET_TYPES = {"stock", "etf", "fund", "index"}


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
class BulkUnmatchedRouteResult:
    dry_run: bool
    routeable: int
    rows_inserted: int
    rows_rejected: int
    routed: int

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "routeable": self.routeable,
            "rows_inserted": self.rows_inserted,
            "rows_rejected": self.rows_rejected,
            "routed": self.routed,
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

    scanned = matched = ambiguous = needs_instrument = non_price_asset = unknown = 0
    for row in connection.execute(statement).mappings():
        scanned += 1
        type_bucket = _bucket_eodhd_type(row["eodhd_type"])
        resolution = active_resolver.resolve(
            provider_symbol=str(row["provider_symbol"]),
            trade_date=row["trade_date"],
            eodhd_type=row["eodhd_type"],
        )
        status, asset_type, matched_id, reason = _classification_decision(
            type_bucket=type_bucket,
            resolution=resolution,
        )
        if status == "matched":
            matched += 1
        elif status == "ambiguous":
            ambiguous += 1
        elif status == "needs_instrument":
            needs_instrument += 1
        elif status == "non_price_asset":
            non_price_asset += 1
        else:
            unknown += 1
        connection.execute(
            update(bulk_unmatched_daily_price_observation)
            .where(
                bulk_unmatched_daily_price_observation.c.observation_id == row["observation_id"]
            )
            .values(
                classification_status=status,
                classified_asset_type=asset_type,
                matched_instrument_id=matched_id,
                reason=reason,
                updated_at=func.current_timestamp(),
            )
        )

    return BulkUnmatchedClassifyResult(
        scanned=scanned,
        matched=matched,
        ambiguous=ambiguous,
        needs_instrument=needs_instrument,
        non_price_asset=non_price_asset,
        unknown=unknown,
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
) -> BulkUnmatchedRouteResult:
    """Route high-confidence matched unmatched rows into split daily price tables."""
    selected_asset_types = asset_types or sorted(ROUTABLE_ASSET_TYPES)
    unsupported = sorted(set(selected_asset_types) - ROUTABLE_ASSET_TYPES)
    if unsupported:
        raise ValueError(f"unsupported asset type(s): {', '.join(unsupported)}")

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
            *_base_observation_conditions(date_from=date_from, date_to=date_to, market=market),
            bulk_unmatched_daily_price_observation.c.classification_status == "matched",
            instrument.c.asset_type.in_(selected_asset_types),
        )
        .order_by(
            bulk_unmatched_daily_price_observation.c.trade_date,
            bulk_unmatched_daily_price_observation.c.provider_symbol,
        )
    )
    if limit is not None:
        statement = statement.limit(limit)

    rows = [dict(row) for row in connection.execute(statement).mappings()]
    selected_rows, suppressed_rows = _select_route_rows(rows)
    if dry_run:
        return BulkUnmatchedRouteResult(
            dry_run=True,
            routeable=len(selected_rows),
            rows_inserted=0,
            rows_rejected=len(suppressed_rows),
            routed=0,
        )

    accepted_by_asset_type: dict[str, list[dict[str, object]]] = {}
    rejected_ids: list[int] = []
    routed_ids: list[int] = []
    _mark_suppressed_route_rows(connection, suppressed_rows)
    for row in selected_rows:
        payload = {
            "date": row["trade_date"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "adjusted_close": row["adjusted_close"],
            "volume": row["volume"],
        }
        parsed = parse_daily_price_rows(
            [payload],
            instrument_id=int(row["instrument_id"]),
            symbol=str(row["observed_symbol"]),
            provider_symbol=str(row["observed_provider_symbol"]),
            currency=str(row["currency"]),
        )
        if parsed.accepted:
            asset_type = str(row["asset_type"])
            accepted_by_asset_type.setdefault(asset_type, []).extend(parsed.accepted)
            routed_ids.append(int(row["observation_id"]))
        else:
            rejected_ids.append(int(row["observation_id"]))
            _mark_route_failed(connection, row["observation_id"], parsed.rejected)

    rows_inserted = 0
    for asset_type, price_rows in accepted_by_asset_type.items():
        connection.execute(build_daily_price_upsert(asset_type, price_rows))
        rows_inserted += len(price_rows)
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
        routeable=len(selected_rows),
        rows_inserted=rows_inserted,
        rows_rejected=len(rejected_ids) + len(suppressed_rows),
        routed=len(routed_ids),
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


def _mark_route_failed(
    connection: Connection,
    observation_id: object,
    rejected_rows: list[RejectedDailyPriceRow],
) -> None:
    reason = "; ".join(row.reason for row in rejected_rows) or "route_failed"
    connection.execute(
        update(bulk_unmatched_daily_price_observation)
        .where(bulk_unmatched_daily_price_observation.c.observation_id == observation_id)
        .values(
            classification_status="route_failed",
            reason=reason,
            updated_at=func.current_timestamp(),
        )
    )
