"""Workflows for EODHD Bulk EOD rows that did not match instruments at ingest time."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection

from fdp.sources.eodhd.prices import RejectedDailyPriceRow, parse_daily_price_rows
from fdp.storage.tables import (
    bulk_unmatched_daily_price_observation,
    instrument,
)
from fdp.storage.upsert import (
    build_etf_daily_price_upsert,
    build_index_daily_price_upsert,
    build_stock_daily_price_upsert,
)

ROUTABLE_ASSET_TYPES = {"stock", "etf", "index"}
PRICE_UPSERT_BUILDERS = {
    "stock": build_stock_daily_price_upsert,
    "etf": build_etf_daily_price_upsert,
    "index": build_index_daily_price_upsert,
}


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
    needs_instrument: int
    non_price_asset: int
    unknown: int

    def to_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "matched": self.matched,
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
) -> BulkUnmatchedClassifyResult:
    """Classify unresolved unmatched rows using strict provider-symbol instrument matches."""
    statement = (
        select(
            bulk_unmatched_daily_price_observation.c.observation_id,
            bulk_unmatched_daily_price_observation.c.provider_symbol,
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

    scanned = matched = needs_instrument = non_price_asset = unknown = 0
    for row in connection.execute(statement).mappings():
        scanned += 1
        type_bucket = _bucket_eodhd_type(row["eodhd_type"])
        instrument_row = _load_exact_instrument(
            connection,
            provider_symbol=str(row["provider_symbol"]),
            market=market,
        )
        status, asset_type, matched_id, reason = _classification_decision(
            type_bucket=type_bucket,
            instrument_row=instrument_row,
        )
        if status == "matched":
            matched += 1
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
            instrument.c.instrument_id,
            instrument.c.symbol,
            instrument.c.provider_symbol,
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
    if dry_run:
        return BulkUnmatchedRouteResult(
            dry_run=True,
            routeable=len(rows),
            rows_inserted=0,
            rows_rejected=0,
            routed=0,
        )

    accepted_by_asset_type: dict[str, list[dict[str, object]]] = {}
    rejected_ids: list[int] = []
    routed_ids: list[int] = []
    for row in rows:
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
            symbol=str(row["symbol"]),
            provider_symbol=str(row["provider_symbol"]),
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
        connection.execute(PRICE_UPSERT_BUILDERS[asset_type](price_rows))
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
        routeable=len(rows),
        rows_inserted=rows_inserted,
        rows_rejected=len(rejected_ids),
        routed=len(routed_ids),
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


def _load_exact_instrument(
    connection: Connection,
    *,
    provider_symbol: str,
    market: str,
) -> dict[str, object] | None:
    statement = select(
        instrument.c.instrument_id,
        instrument.c.asset_type,
    ).where(
        and_(
            instrument.c.market == market,
            instrument.c.provider == "EODHD",
            instrument.c.provider_symbol == provider_symbol,
        )
    )
    row = connection.execute(statement).mappings().first()
    return dict(row) if row is not None else None


def _classification_decision(
    *,
    type_bucket: str | None,
    instrument_row: dict[str, object] | None,
) -> tuple[str, str | None, int | None, str]:
    if type_bucket in {"fund", "preferred", "other"}:
        return "non_price_asset", type_bucket, None, f"non_price_eodhd_type:{type_bucket}"
    if instrument_row is not None:
        asset_type = str(instrument_row["asset_type"])
        if asset_type in ROUTABLE_ASSET_TYPES:
            return (
                "matched",
                asset_type,
                int(instrument_row["instrument_id"]),
                "exact_provider_symbol_match",
            )
        return "non_price_asset", asset_type, int(instrument_row["instrument_id"]), "non_price_asset"
    if type_bucket in ROUTABLE_ASSET_TYPES:
        return "needs_instrument", type_bucket, None, "no_exact_provider_symbol_instrument"
    return "unknown", type_bucket or "unknown", None, "unknown_eodhd_type"


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
