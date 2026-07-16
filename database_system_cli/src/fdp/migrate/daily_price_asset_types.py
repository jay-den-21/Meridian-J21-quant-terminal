"""Operator-controlled reconciliation of daily rows after instrument type corrections."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Table, delete, select, text, tuple_
from sqlalchemy.engine import Connection, Engine

from fdp.storage.tables import DAILY_PRICE_TABLES, instrument, stock_daily_price
from fdp.storage.upsert import build_daily_price_upsert

DEFAULT_RECONCILE_CHUNK_SIZE = 1_000
PRICE_COPY_COLUMNS = tuple(
    column.name for column in stock_daily_price.columns if not column.primary_key
)
PRICE_PAYLOAD_COLUMNS = (
    "symbol",
    "provider_symbol",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "currency",
    "source",
    "source_updated_at",
)


@dataclass(frozen=True)
class AssetTypeMismatchGroup:
    """One source-table/current-instrument-type mismatch group."""

    source_asset_type: str
    target_asset_type: str
    rows_count: int
    instruments_count: int


@dataclass(frozen=True)
class AssetTypeReconcilePlan:
    """Read-only mismatch inventory across canonical daily tables."""

    groups: tuple[AssetTypeMismatchGroup, ...]

    @property
    def total_rows(self) -> int:
        return sum(group.rows_count for group in self.groups)


@dataclass(frozen=True)
class AssetTypeReconcileResult:
    """Committed chunk summary for an idempotent reconcile run."""

    status: str
    chunks_completed: int
    rows_moved: int
    remaining_rows: int


def plan_daily_price_asset_type_reconcile(connection: Connection) -> AssetTypeReconcilePlan:
    """Count rows whose physical table disagrees with current instrument.asset_type."""
    canonical_types = ",".join(f"'{asset_type}'" for asset_type in DAILY_PRICE_TABLES)
    groups: list[AssetTypeMismatchGroup] = []
    for source_asset_type, price_table in DAILY_PRICE_TABLES.items():
        statement = text(
            f"""
            SELECT i.asset_type AS target_asset_type,
                   COUNT(*) AS rows_count,
                   COUNT(DISTINCT i.instrument_id) AS instruments_count
            FROM us_share.instrument AS i
            STRAIGHT_JOIN us_share.{price_table.name} AS p
              ON p.instrument_id = i.instrument_id
            WHERE i.asset_type <> :source_asset_type
              AND i.asset_type IN ({canonical_types})
            GROUP BY i.asset_type
            """
        )
        for row in connection.execute(
            statement,
            {"source_asset_type": source_asset_type},
        ).mappings():
            groups.append(
                AssetTypeMismatchGroup(
                    source_asset_type=source_asset_type,
                    target_asset_type=str(row["target_asset_type"]),
                    rows_count=int(row["rows_count"]),
                    instruments_count=int(row["instruments_count"]),
                )
            )
    groups.sort(key=lambda group: (group.source_asset_type, group.target_asset_type))
    return AssetTypeReconcilePlan(tuple(groups))


def reconcile_daily_price_asset_types(
    engine: Engine,
    *,
    chunk_size: int = DEFAULT_RECONCILE_CHUNK_SIZE,
    max_chunks: int | None = None,
) -> AssetTypeReconcileResult:
    """Copy, verify, and delete mismatched rows in bounded transactions.

    Input: database engine, chunk size, and optional global chunk cap.
    Output: committed row/chunk counters plus the remaining mismatch count.
    Flow: current instrument type -> target upsert -> payload verify -> source delete.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if max_chunks is not None and max_chunks <= 0:
        raise ValueError("max_chunks must be positive")

    chunks_completed = 0
    rows_moved = 0
    stopped_at_limit = False
    for source_asset_type, source_table in DAILY_PRICE_TABLES.items():
        while True:
            if max_chunks is not None and chunks_completed >= max_chunks:
                stopped_at_limit = True
                break
            with engine.begin() as connection:
                rows = _next_mismatch_rows(
                    connection,
                    source_asset_type=source_asset_type,
                    source_table=source_table,
                    chunk_size=chunk_size,
                )
                if not rows:
                    break
                _reconcile_chunk(
                    connection,
                    source_asset_type=source_asset_type,
                    source_table=source_table,
                    rows=rows,
                )
            chunks_completed += 1
            rows_moved += len(rows)
        if stopped_at_limit:
            break

    with engine.connect() as connection:
        remaining_rows = plan_daily_price_asset_type_reconcile(connection).total_rows
    return AssetTypeReconcileResult(
        status="completed" if remaining_rows == 0 else "partial",
        chunks_completed=chunks_completed,
        rows_moved=rows_moved,
        remaining_rows=remaining_rows,
    )


def _next_mismatch_rows(
    connection: Connection,
    *,
    source_asset_type: str,
    source_table: Table,
    chunk_size: int,
) -> list[dict[str, Any]]:
    source_id = next(iter(source_table.primary_key.columns))
    statement = (
        select(
            source_id.label("_source_id"),
            instrument.c.asset_type.label("_target_asset_type"),
            *(source_table.c[column] for column in PRICE_COPY_COLUMNS),
        )
        .select_from(
            instrument.join(
                source_table,
                source_table.c.instrument_id == instrument.c.instrument_id,
            )
        )
        .where(
            instrument.c.asset_type != source_asset_type,
            instrument.c.asset_type.in_(tuple(DAILY_PRICE_TABLES)),
        )
        .order_by(source_id)
        .limit(chunk_size)
        .prefix_with("STRAIGHT_JOIN", dialect="mysql")
    )
    return [dict(row) for row in connection.execute(statement).mappings()]


def _reconcile_chunk(
    connection: Connection,
    *,
    source_asset_type: str,
    source_table: Table,
    rows: list[dict[str, Any]],
) -> None:
    current_types = _current_instrument_types(
        connection,
        {int(row["instrument_id"]) for row in rows},
    )
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        instrument_id = int(row["instrument_id"])
        target_asset_type = str(row["_target_asset_type"])
        if current_types.get(instrument_id) != target_asset_type:
            raise RuntimeError("instrument asset_type changed during reconciliation")
        if target_asset_type == source_asset_type:
            raise RuntimeError("mismatch row no longer requires reconciliation")
        by_target[target_asset_type].append(row)

    for target_asset_type, target_rows in by_target.items():
        target_table = DAILY_PRICE_TABLES[target_asset_type]
        existing = _target_rows(connection, target_table, target_rows)
        for row in target_rows:
            key = _natural_key(row)
            target_row = existing.get(key)
            if target_row is not None and not _payload_matches(row, target_row):
                raise RuntimeError(
                    "conflicting target daily price for "
                    f"instrument_id={key[0]} trade_date={key[1]}"
                )

        missing = [
            {column: row[column] for column in PRICE_COPY_COLUMNS}
            for row in target_rows
            if _natural_key(row) not in existing
        ]
        if missing:
            connection.execute(build_daily_price_upsert(target_asset_type, missing))

        verified = _target_rows(connection, target_table, target_rows)
        for row in target_rows:
            key = _natural_key(row)
            target_row = verified.get(key)
            if target_row is None or not _payload_matches(row, target_row):
                raise RuntimeError(
                    "target verification failed for "
                    f"instrument_id={key[0]} trade_date={key[1]}"
                )

    source_id = next(iter(source_table.primary_key.columns))
    source_ids = [int(row["_source_id"]) for row in rows]
    delete_result = connection.execute(delete(source_table).where(source_id.in_(source_ids)))
    if delete_result.rowcount != len(source_ids):
        raise RuntimeError(
            f"source delete count mismatch: expected {len(source_ids)}, got {delete_result.rowcount}"
        )


def _current_instrument_types(
    connection: Connection,
    instrument_ids: set[int],
) -> dict[int, str]:
    rows = connection.execute(
        select(instrument.c.instrument_id, instrument.c.asset_type).where(
            instrument.c.instrument_id.in_(instrument_ids)
        )
    )
    return {int(instrument_id): str(asset_type) for instrument_id, asset_type in rows}


def _target_rows(
    connection: Connection,
    target_table: Table,
    source_rows: list[dict[str, Any]],
) -> dict[tuple[int, date], dict[str, Any]]:
    keys = [_natural_key(row) for row in source_rows]
    statement = select(
        target_table.c.instrument_id,
        target_table.c.trade_date,
        *(target_table.c[column] for column in PRICE_PAYLOAD_COLUMNS),
    ).where(tuple_(target_table.c.instrument_id, target_table.c.trade_date).in_(keys))
    return {
        (int(row["instrument_id"]), row["trade_date"]): dict(row)
        for row in connection.execute(statement).mappings()
    }


def _natural_key(row: dict[str, Any]) -> tuple[int, date]:
    return int(row["instrument_id"]), row["trade_date"]


def _payload_matches(source: dict[str, Any], target: dict[str, Any]) -> bool:
    return all(source.get(column) == target.get(column) for column in PRICE_PAYLOAD_COLUMNS)
