"""Resumable operator workflow for separating Fund rows from the ETF price table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.engine import Connection, Engine

from fdp.storage.tables import fund_daily_price_split_run

DEFAULT_CHUNK_SIZE = 10_000
SAMPLE_MODULUS = 997
COPYABLE_STATUSES = {"copying", "copied", "verification_failed"}
FINALIZABLE_STATUSES = {"verified", "finalizing"}
COMPACT_SWAP_DELETE_RATIO = 0.5
CHUNK_DELETE_STRATEGY = "chunk_delete"
COMPACT_SWAP_STRATEGY = "compact_swap"
TARGET_SECONDARY_INDEXES = {
    "ix_fund_daily_price_symbol_date": ("symbol", "trade_date"),
    "ix_fund_daily_price_trade_date": ("trade_date",),
}
SOURCE_SECONDARY_INDEXES = {
    "ix_etf_daily_price_symbol_date": ("symbol", "trade_date"),
    "ix_etf_daily_price_trade_date": ("trade_date",),
}

PRICE_COPY_COLUMNS = (
    "instrument_id",
    "symbol",
    "provider_symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "currency",
    "source",
    "source_updated_at",
    "created_at",
    "updated_at",
)
PRICE_UPDATE_COLUMNS = (
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
    "updated_at",
)
ETF_COMPACT_COPY_COLUMNS = ("etf_daily_price_id", *PRICE_COPY_COLUMNS)


@dataclass(frozen=True)
class FundSplitPlan:
    """Read-only preflight counts for the ETF/Fund physical split."""

    source_total_rows: int
    source_fund_rows: int
    source_unexpected_rows: int
    target_total_rows: int
    target_non_fund_rows: int

    @property
    def ready(self) -> bool:
        return (
            self.source_fund_rows > 0
            and self.source_unexpected_rows == 0
            and self.target_total_rows == 0
            and self.target_non_fund_rows == 0
        )


@dataclass(frozen=True)
class FundSplitCopyResult:
    fund_split_run_id: int
    status: str
    chunks_completed: int
    rows_copied: int
    last_source_id: int


@dataclass(frozen=True)
class FundSplitVerification:
    fund_split_run_id: int
    status: str
    passed: bool
    fingerprint: str
    details: dict[str, int]


@dataclass(frozen=True)
class FundSplitFinalizeResult:
    fund_split_run_id: int
    status: str
    chunks_completed: int
    rows_deleted: int
    verification: FundSplitVerification


@dataclass(frozen=True)
class BackupEvidence:
    path: str
    size_bytes: int
    sha256: str


def plan_fund_daily_prices(connection: Connection) -> FundSplitPlan:
    """Return exact source/target counts without writing migration state."""
    return FundSplitPlan(
        source_total_rows=_scalar(connection, "SELECT COUNT(*) FROM us_share.etf_daily_price"),
        source_fund_rows=_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM us_share.etf_daily_price AS p
            JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
            WHERE i.asset_type = 'fund'
            """,
        ),
        source_unexpected_rows=_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM us_share.etf_daily_price AS p
            JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
            WHERE i.asset_type NOT IN ('etf', 'fund')
            """,
        ),
        target_total_rows=_scalar(
            connection,
            "SELECT COUNT(*) FROM us_share.fund_daily_price",
        ),
        target_non_fund_rows=_scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM us_share.fund_daily_price AS p
            JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
            WHERE i.asset_type != 'fund'
            """,
        ),
    )


def copy_fund_daily_prices(
    engine: Engine,
    *,
    backup_file: Path | str | None = None,
    run_id: int | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_chunks: int | None = None,
) -> FundSplitCopyResult:
    """Copy Fund rows into their table with per-chunk transactional checkpoints."""
    _validate_chunk_options(chunk_size=chunk_size, max_chunks=max_chunks)
    if run_id is None:
        if backup_file is None:
            raise ValueError("backup_file is required when starting a Fund split copy")
        backup = validate_backup_file(backup_file)
        with engine.begin() as connection:
            plan = plan_fund_daily_prices(connection)
            _require_copy_ready(plan)
            run_id = _create_split_run(
                connection,
                plan=plan,
                chunk_size=chunk_size,
                backup=backup,
            )
    elif backup_file is not None:
        raise ValueError("backup_file is only accepted when creating a new split run")

    _prepare_target_for_copy(engine)
    chunks_completed = 0
    while max_chunks is None or chunks_completed < max_chunks:
        with engine.begin() as connection:
            run = _load_run(connection, run_id=run_id, for_update=True)
            if run["status"] not in COPYABLE_STATUSES:
                raise ValueError(
                    f"split run {run_id} status {run['status']!r} cannot execute copy"
                )
            last_source_id = int(run["copy_last_source_id"])
            next_source_id = _next_source_id(
                connection,
                after_source_id=last_source_id,
                chunk_size=chunk_size,
            )
            if next_source_id is None:
                connection.execute(
                    update(fund_daily_price_split_run)
                    .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                    .values(status="copied", error_message=None, updated_at=_now_utc())
                )
                return FundSplitCopyResult(
                    fund_split_run_id=run_id,
                    status="copied",
                    chunks_completed=chunks_completed,
                    rows_copied=int(run["rows_copied"]),
                    last_source_id=last_source_id,
                )

            chunk_rows = _copy_source_range(
                connection,
                after_source_id=last_source_id,
                through_source_id=next_source_id,
            )
            connection.execute(
                update(fund_daily_price_split_run)
                .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                .values(
                    status="copying",
                    rows_copied=fund_daily_price_split_run.c.rows_copied + chunk_rows,
                    copy_last_source_id=next_source_id,
                    verification_fingerprint=None,
                    verification_details=None,
                    verified_at=None,
                    error_message=None,
                    updated_at=_now_utc(),
                )
            )
        chunks_completed += 1

    with engine.connect() as connection:
        run = _load_run(connection, run_id=run_id)
    return FundSplitCopyResult(
        fund_split_run_id=run_id,
        status=str(run["status"]),
        chunks_completed=chunks_completed,
        rows_copied=int(run["rows_copied"]),
        last_source_id=int(run["copy_last_source_id"]),
    )


def verify_fund_daily_prices(
    engine: Engine,
    *,
    run_id: int,
) -> FundSplitVerification:
    """Verify pre-finalize copy invariants or post-finalize conservation invariants."""
    _restore_target_indexes(engine)
    _restore_source_indexes(engine)
    with engine.begin() as connection:
        run = _load_run(connection, run_id=run_id, for_update=True)
        if run["status"] == "completed":
            details = _post_finalize_details(connection, run)
            passed = _post_finalize_passed(details, run)
            fingerprint = _fingerprint(details)
            return FundSplitVerification(run_id, "completed", passed, fingerprint, details)
        if run["status"] not in {"copied", "verified", "verification_failed"}:
            raise ValueError(
                f"split run {run_id} status {run['status']!r} must be copied before verify"
            )

        details = _pre_finalize_details(connection)
        passed = _pre_finalize_passed(details, run)
        fingerprint = _fingerprint(details)
        connection.execute(
            update(fund_daily_price_split_run)
            .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
            .values(
                status="verified" if passed else "verification_failed",
                verification_fingerprint=fingerprint,
                verification_details=json.dumps(details, sort_keys=True),
                verified_at=_now_utc() if passed else None,
                error_message=None if passed else "Fund split verification failed",
                updated_at=_now_utc(),
            )
        )
        return FundSplitVerification(
            fund_split_run_id=run_id,
            status="verified" if passed else "verification_failed",
            passed=passed,
            fingerprint=fingerprint,
            details=details,
        )


def finalize_fund_daily_prices(
    engine: Engine,
    *,
    run_id: int,
    chunk_size: int | None = None,
    max_chunks: int | None = None,
) -> FundSplitFinalizeResult:
    """Remove copied Fund rows using chunk delete or a verified compact-table swap."""
    with engine.connect() as connection:
        initial_run = _load_run(connection, run_id=run_id)
    effective_chunk_size = chunk_size or int(initial_run["chunk_size"])
    _validate_chunk_options(chunk_size=effective_chunk_size, max_chunks=max_chunks)
    backup = validate_backup_file(str(initial_run["backup_path"]))
    if (
        backup.size_bytes != int(initial_run["backup_size_bytes"])
        or backup.sha256 != initial_run["backup_sha256"]
    ):
        raise RuntimeError("backup file no longer matches the split-run evidence")

    strategy: str
    with engine.begin() as connection:
        run = _load_run(connection, run_id=run_id, for_update=True)
        if run["status"] not in FINALIZABLE_STATUSES:
            raise ValueError(
                f"split run {run_id} status {run['status']!r} cannot execute finalize"
            )
        if run["status"] == "verified":
            details = _pre_finalize_details(connection)
            fingerprint = _fingerprint(details)
            if not _pre_finalize_passed(details, run):
                raise RuntimeError("current database state no longer passes Fund split verification")
            if fingerprint != run["verification_fingerprint"]:
                raise RuntimeError("Fund split verification fingerprint is stale")
            connection.execute(
                update(fund_daily_price_split_run)
                .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                .values(status="finalizing", error_message=None, updated_at=_now_utc())
            )

        strategy = str(run.get("finalize_strategy") or _select_finalize_strategy(run))
        if strategy not in {CHUNK_DELETE_STRATEGY, COMPACT_SWAP_STRATEGY}:
            raise RuntimeError(f"unknown Fund split finalize strategy: {strategy}")
        if run.get("finalize_strategy") is None:
            connection.execute(
                update(fund_daily_price_split_run)
                .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                .values(finalize_strategy=strategy, updated_at=_now_utc())
            )

    if strategy == COMPACT_SWAP_STRATEGY:
        return _finalize_fund_daily_prices_by_compact_swap(
            engine,
            run_id=run_id,
            chunk_size=effective_chunk_size,
            max_chunks=max_chunks,
        )

    _prepare_source_for_finalize(engine)
    chunks_completed = 0
    terminal_result: FundSplitFinalizeResult | None = None
    while max_chunks is None or chunks_completed < max_chunks:
        with engine.begin() as connection:
            run = _load_run(connection, run_id=run_id, for_update=True)
            if run["status"] != "finalizing":
                raise ValueError(
                    f"split run {run_id} status {run['status']!r} cannot resume finalize"
                )
            last_source_id = int(run["delete_last_source_id"])
            next_source_id = _next_source_id(
                connection,
                after_source_id=last_source_id,
                chunk_size=effective_chunk_size,
            )
            if next_source_id is None:
                details = _post_finalize_details(connection, run)
                passed = _post_finalize_passed(details, run)
                verification = FundSplitVerification(
                    fund_split_run_id=run_id,
                    status="completed" if passed else "finalize_failed",
                    passed=passed,
                    fingerprint=_fingerprint(details),
                    details=details,
                )
                if not passed:
                    connection.execute(
                        update(fund_daily_price_split_run)
                        .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                        .values(
                            status="finalize_failed",
                            error_message="post-finalize Fund split verification failed",
                            verification_details=json.dumps(details, sort_keys=True),
                            updated_at=_now_utc(),
                        )
                    )
                    terminal_result = FundSplitFinalizeResult(
                        run_id,
                        "finalize_failed",
                        chunks_completed,
                        int(run["rows_deleted"]),
                        verification,
                    )
                else:
                    connection.execute(
                        update(fund_daily_price_split_run)
                        .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                        .values(
                            status="completed",
                            completed_at=_now_utc(),
                            error_message=None,
                            updated_at=_now_utc(),
                        )
                    )
                    terminal_result = FundSplitFinalizeResult(
                        run_id,
                        "completed",
                        chunks_completed,
                        int(run["rows_deleted"]),
                        verification,
                    )
                break

            deleted_rows = _delete_source_range(
                connection,
                after_source_id=last_source_id,
                through_source_id=next_source_id,
            )
            connection.execute(
                update(fund_daily_price_split_run)
                .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                .values(
                    rows_deleted=fund_daily_price_split_run.c.rows_deleted + deleted_rows,
                    delete_last_source_id=next_source_id,
                    updated_at=_now_utc(),
                )
            )
        chunks_completed += 1

    if terminal_result is not None:
        _restore_source_indexes(engine)
        return terminal_result

    with engine.connect() as connection:
        run = _load_run(connection, run_id=run_id)
        details = _post_finalize_details(connection, run)
    verification = FundSplitVerification(
        run_id,
        str(run["status"]),
        False,
        _fingerprint(details),
        details,
    )
    return FundSplitFinalizeResult(
        run_id,
        str(run["status"]),
        chunks_completed,
        int(run["rows_deleted"]),
        verification,
    )


def _select_finalize_strategy(run: dict[str, Any]) -> str:
    """Use compact-swap only before any chunk delete has committed."""
    if int(run.get("rows_deleted") or 0) or int(run.get("delete_last_source_id") or 0):
        return CHUNK_DELETE_STRATEGY
    source_total = int(run["source_total_before"])
    if source_total <= 0:
        raise RuntimeError("Fund split source baseline must be positive")
    delete_ratio = int(run["source_fund_rows"]) / source_total
    return (
        COMPACT_SWAP_STRATEGY
        if delete_ratio >= COMPACT_SWAP_DELETE_RATIO
        else CHUNK_DELETE_STRATEGY
    )


def _finalize_fund_daily_prices_by_compact_swap(
    engine: Engine,
    *,
    run_id: int,
    chunk_size: int,
    max_chunks: int | None,
) -> FundSplitFinalizeResult:
    """Copy the minority ETF rows, verify, atomically swap, and retire the mixed table."""
    compact_table, retired_table = _compaction_table_names(run_id)
    _ensure_compact_table(
        engine,
        run_id=run_id,
        compact_table=compact_table,
        retired_table=retired_table,
    )

    chunks_completed = 0
    while max_chunks is None or chunks_completed < max_chunks:
        with engine.begin() as connection:
            run = _load_run(connection, run_id=run_id, for_update=True)
            if run["status"] != "finalizing":
                raise ValueError(
                    f"split run {run_id} status {run['status']!r} cannot resume compact-swap"
                )
            if _compact_swap_already_happened(
                connection,
                run=run,
                compact_table=compact_table,
                retired_table=retired_table,
            ):
                break
            last_source_id = int(run.get("compact_last_source_id") or 0)
            next_source_id = _next_etf_source_id(
                connection,
                after_source_id=last_source_id,
                chunk_size=chunk_size,
            )
            if next_source_id is None:
                break
            compacted_rows = _copy_etf_source_range(
                connection,
                compact_table=compact_table,
                after_source_id=last_source_id,
                through_source_id=next_source_id,
            )
            connection.execute(
                update(fund_daily_price_split_run)
                .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                .values(
                    rows_compacted=fund_daily_price_split_run.c.rows_compacted
                    + compacted_rows,
                    compact_last_source_id=next_source_id,
                    compact_verification_fingerprint=None,
                    compact_verification_details=None,
                    compact_verified_at=None,
                    error_message=None,
                    updated_at=_now_utc(),
                )
            )
        chunks_completed += 1

    with engine.connect() as connection:
        run = _load_run(connection, run_id=run_id)
        already_swapped = _compact_swap_already_happened(
            connection,
            run=run,
            compact_table=compact_table,
            retired_table=retired_table,
        )
        copy_remaining = False
        if not already_swapped:
            copy_remaining = (
                _next_etf_source_id(
                    connection,
                    after_source_id=int(run.get("compact_last_source_id") or 0),
                    chunk_size=1,
                )
                is not None
            )
    if copy_remaining:
        details = {
            "rows_compacted": int(run.get("rows_compacted") or 0),
            "expected_etf_rows": _expected_etf_rows(run),
        }
        verification = FundSplitVerification(
            run_id,
            "finalizing",
            False,
            _fingerprint(details),
            details,
        )
        return FundSplitFinalizeResult(
            run_id,
            "finalizing",
            chunks_completed,
            int(run["rows_deleted"]),
            verification,
        )

    if not already_swapped:
        _restore_named_indexes(engine, compact_table, SOURCE_SECONDARY_INDEXES)
        with engine.begin() as connection:
            run = _load_run(connection, run_id=run_id, for_update=True)
            details = _compact_pre_swap_details(
                connection,
                compact_table=compact_table,
                run=run,
            )
            if not _compact_pre_swap_passed(details, run):
                connection.execute(
                    update(fund_daily_price_split_run)
                    .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                    .values(
                        error_message="ETF compact-table verification failed",
                        compact_verification_details=json.dumps(details, sort_keys=True),
                        updated_at=_now_utc(),
                    )
                )
                raise RuntimeError("ETF compact-table verification failed before atomic swap")
            fingerprint = _fingerprint(details)
            connection.execute(
                update(fund_daily_price_split_run)
                .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                .values(
                    compact_verification_fingerprint=fingerprint,
                    compact_verification_details=json.dumps(details, sort_keys=True),
                    compact_verified_at=_now_utc(),
                    updated_at=_now_utc(),
                )
            )
        _atomic_swap_compact_etf_table(
            engine,
            run_id=run_id,
            compact_table=compact_table,
            retired_table=retired_table,
        )

    with engine.begin() as connection:
        run = _load_run(connection, run_id=run_id, for_update=True)
        details = _compact_post_swap_details(
            connection,
            retired_table=retired_table,
            run=run,
        )
        passed = _compact_post_swap_passed(details, run)
        verification = FundSplitVerification(
            run_id,
            "completed" if passed else "finalize_failed",
            passed,
            _fingerprint(details),
            details,
        )
        if not passed:
            connection.execute(
                update(fund_daily_price_split_run)
                .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
                .values(
                    status="finalize_failed",
                    error_message="post-swap ETF/Fund verification failed",
                    updated_at=_now_utc(),
                )
            )
            return FundSplitFinalizeResult(
                run_id,
                "finalize_failed",
                chunks_completed,
                int(run["rows_deleted"]),
                verification,
            )

    _drop_retired_etf_table(engine, retired_table=retired_table)
    with engine.begin() as connection:
        run = _load_run(connection, run_id=run_id, for_update=True)
        connection.execute(
            update(fund_daily_price_split_run)
            .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
            .values(
                status="completed",
                rows_deleted=int(run["source_fund_rows"]),
                swapped_at=run.get("swapped_at") or _now_utc(),
                completed_at=_now_utc(),
                error_message=None,
                updated_at=_now_utc(),
            )
        )
    return FundSplitFinalizeResult(
        run_id,
        "completed",
        chunks_completed,
        int(run["source_fund_rows"]),
        verification,
    )


def _compaction_table_names(run_id: int) -> tuple[str, str]:
    if run_id <= 0:
        raise ValueError("run_id must be positive")
    return f"etf_daily_price_compact_{run_id}", f"etf_daily_price_retired_{run_id}"


def _expected_etf_rows(run: dict[str, Any]) -> int:
    return int(run["source_total_before"]) - int(run["source_fund_rows"])


def _ensure_compact_table(
    engine: Engine,
    *,
    run_id: int,
    compact_table: str,
    retired_table: str,
) -> None:
    with engine.begin() as connection:
        run = _load_run(connection, run_id=run_id, for_update=True)
        if _compact_swap_already_happened(
            connection,
            run=run,
            compact_table=compact_table,
            retired_table=retired_table,
        ):
            return
        if not _table_exists(connection, compact_table):
            current_rows = _table_row_count(connection, "etf_daily_price")
            if current_rows != int(run["source_total_before"]):
                raise RuntimeError(
                    "canonical ETF table no longer matches the pre-split baseline"
                )
            connection.execute(
                text(
                    f"CREATE TABLE us_share.{compact_table} "
                    "LIKE us_share.etf_daily_price"
                )
            )

    _drop_named_indexes(engine, compact_table, SOURCE_SECONDARY_INDEXES)
    with engine.begin() as connection:
        constraint_name = f"fk_etf_compact_{run_id}_instrument"
        if not _foreign_key_exists(connection, compact_table, constraint_name):
            connection.execute(
                text(
                    f"ALTER TABLE us_share.{compact_table} "
                    f"ADD CONSTRAINT {constraint_name} FOREIGN KEY (instrument_id) "
                    "REFERENCES us_share.instrument (instrument_id)"
                )
            )


def _compact_swap_already_happened(
    connection: Connection,
    *,
    run: dict[str, Any],
    compact_table: str,
    retired_table: str,
) -> bool:
    if _table_exists(connection, retired_table):
        return not _table_exists(connection, compact_table)
    if _table_exists(connection, compact_table):
        return False
    return _table_row_count(connection, "etf_daily_price") == _expected_etf_rows(run)


def _next_etf_source_id(
    connection: Connection,
    *,
    after_source_id: int,
    chunk_size: int,
) -> int | None:
    value = connection.execute(
        text(
            """
            SELECT MAX(chunk.etf_daily_price_id)
            FROM (
              SELECT p.etf_daily_price_id
              FROM us_share.etf_daily_price AS p
              JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
              WHERE i.asset_type = 'etf'
                AND p.etf_daily_price_id > :after_source_id
              ORDER BY p.etf_daily_price_id
              LIMIT :chunk_size
            ) AS chunk
            """
        ),
        {"after_source_id": after_source_id, "chunk_size": chunk_size},
    ).scalar_one()
    return int(value) if value is not None else None


def _copy_etf_source_range(
    connection: Connection,
    *,
    compact_table: str,
    after_source_id: int,
    through_source_id: int,
) -> int:
    rows = _scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM us_share.etf_daily_price AS p
        JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
        WHERE i.asset_type = 'etf'
          AND p.etf_daily_price_id > :after_source_id
          AND p.etf_daily_price_id <= :through_source_id
        """,
        {"after_source_id": after_source_id, "through_source_id": through_source_id},
    )
    columns = ", ".join(ETF_COMPACT_COPY_COLUMNS)
    selected = ", ".join(f"p.{column}" for column in ETF_COMPACT_COPY_COLUMNS)
    updates = ", ".join(f"{column}=VALUES({column})" for column in PRICE_UPDATE_COLUMNS)
    connection.execute(
        text(
            f"""
            INSERT INTO us_share.{compact_table} ({columns})
            SELECT {selected}
            FROM us_share.etf_daily_price AS p
            JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
            WHERE i.asset_type = 'etf'
              AND p.etf_daily_price_id > :after_source_id
              AND p.etf_daily_price_id <= :through_source_id
            ON DUPLICATE KEY UPDATE {updates}
            """
        ),
        {"after_source_id": after_source_id, "through_source_id": through_source_id},
    )
    return rows


def _compact_pre_swap_details(
    connection: Connection,
    *,
    compact_table: str,
    run: dict[str, Any],
) -> dict[str, int]:
    source_sample_rows, source_sample_checksum = _etf_sample_signature(
        connection,
        table_name="etf_daily_price",
        require_asset_type="etf",
    )
    compact_sample_rows, compact_sample_checksum = _etf_sample_signature(
        connection,
        table_name=compact_table,
    )
    return {
        "source_total_rows": _table_row_count(connection, "etf_daily_price"),
        "source_etf_rows": _asset_rows(connection, "etf_daily_price", "etf"),
        "source_fund_rows": _asset_rows(connection, "etf_daily_price", "fund"),
        "compact_total_rows": _table_row_count(connection, compact_table),
        "compact_non_etf_rows": _non_asset_rows(connection, compact_table, "etf"),
        "missing_compact_rows": _missing_compact_rows(connection, compact_table),
        "extra_compact_rows": _extra_compact_rows(connection, compact_table),
        "compact_duplicate_groups": _duplicate_groups(connection, compact_table),
        "target_fund_rows": _table_row_count(connection, "fund_daily_price"),
        "source_sample_rows": source_sample_rows,
        "source_sample_checksum": source_sample_checksum,
        "compact_sample_rows": compact_sample_rows,
        "compact_sample_checksum": compact_sample_checksum,
        "expected_etf_rows": _expected_etf_rows(run),
    }


def _compact_pre_swap_passed(details: dict[str, int], run: dict[str, Any]) -> bool:
    return all(
        (
            details["source_total_rows"] == int(run["source_total_before"]),
            details["source_etf_rows"] == _expected_etf_rows(run),
            details["source_fund_rows"] == int(run["source_fund_rows"]),
            details["compact_total_rows"] == _expected_etf_rows(run),
            details["compact_non_etf_rows"] == 0,
            details["missing_compact_rows"] == 0,
            details["extra_compact_rows"] == 0,
            details["compact_duplicate_groups"] == 0,
            details["target_fund_rows"] == int(run["source_fund_rows"]),
            details["source_sample_rows"] == details["compact_sample_rows"],
            details["source_sample_checksum"] == details["compact_sample_checksum"],
        )
    )


def _atomic_swap_compact_etf_table(
    engine: Engine,
    *,
    run_id: int,
    compact_table: str,
    retired_table: str,
) -> None:
    with engine.begin() as connection:
        run = _load_run(connection, run_id=run_id, for_update=True)
        if _compact_swap_already_happened(
            connection,
            run=run,
            compact_table=compact_table,
            retired_table=retired_table,
        ):
            return
        current_details = _compact_pre_swap_details(
            connection,
            compact_table=compact_table,
            run=run,
        )
        fingerprint = _fingerprint(current_details)
        if not _compact_pre_swap_passed(current_details, run):
            raise RuntimeError("ETF compact-table state changed before atomic swap")
        if fingerprint != run.get("compact_verification_fingerprint"):
            raise RuntimeError("ETF compact-table verification fingerprint is stale")
        connection.execute(
            text(
                "RENAME TABLE "
                f"us_share.etf_daily_price TO us_share.{retired_table}, "
                f"us_share.{compact_table} TO us_share.etf_daily_price"
            )
        )
        connection.execute(
            update(fund_daily_price_split_run)
            .where(fund_daily_price_split_run.c.fund_split_run_id == run_id)
            .values(swapped_at=_now_utc(), updated_at=_now_utc())
        )


def _compact_post_swap_details(
    connection: Connection,
    *,
    retired_table: str,
    run: dict[str, Any],
) -> dict[str, int]:
    stored = json.loads(str(run.get("compact_verification_details") or "{}"))
    canonical_sample_rows, canonical_sample_checksum = _etf_sample_signature(
        connection,
        table_name="etf_daily_price",
    )
    details = {
        "canonical_etf_rows": _table_row_count(connection, "etf_daily_price"),
        "canonical_non_etf_rows": _non_asset_rows(
            connection,
            "etf_daily_price",
            "etf",
        ),
        "canonical_duplicate_groups": _duplicate_groups(connection, "etf_daily_price"),
        "target_fund_rows": _table_row_count(connection, "fund_daily_price"),
        "conserved_total_rows": _table_row_count(connection, "etf_daily_price")
        + _table_row_count(connection, "fund_daily_price"),
        "canonical_sample_rows": canonical_sample_rows,
        "canonical_sample_checksum": canonical_sample_checksum,
        "expected_sample_rows": int(stored.get("compact_sample_rows", -1)),
        "expected_sample_checksum": int(stored.get("compact_sample_checksum", -1)),
    }
    if _table_exists(connection, retired_table):
        details["retired_total_rows"] = _table_row_count(connection, retired_table)
    return details


def _compact_post_swap_passed(details: dict[str, int], run: dict[str, Any]) -> bool:
    return all(
        (
            details["canonical_etf_rows"] == _expected_etf_rows(run),
            details["canonical_non_etf_rows"] == 0,
            details["canonical_duplicate_groups"] == 0,
            details["target_fund_rows"] == int(run["source_fund_rows"]),
            details["conserved_total_rows"] == int(run["source_total_before"]),
            details["canonical_sample_rows"] == details["expected_sample_rows"],
            details["canonical_sample_checksum"] == details["expected_sample_checksum"],
            details.get("retired_total_rows", int(run["source_total_before"]))
            == int(run["source_total_before"]),
        )
    )


def _drop_retired_etf_table(engine: Engine, *, retired_table: str) -> None:
    with engine.begin() as connection:
        if _table_exists(connection, retired_table):
            connection.execute(text(f"DROP TABLE us_share.{retired_table}"))


def _drop_named_indexes(
    engine: Engine,
    table_name: str,
    indexes: dict[str, tuple[str, ...]],
) -> None:
    with engine.begin() as connection:
        for index_name in indexes:
            if _index_exists(connection, table_name, index_name):
                connection.execute(
                    text(f"ALTER TABLE us_share.{table_name} DROP INDEX {index_name}")
                )


def _restore_named_indexes(
    engine: Engine,
    table_name: str,
    indexes: dict[str, tuple[str, ...]],
) -> None:
    with engine.begin() as connection:
        for index_name, columns in indexes.items():
            if _index_exists(connection, table_name, index_name):
                continue
            connection.execute(
                text(
                    f"CREATE INDEX {index_name} ON us_share.{table_name} "
                    f"({', '.join(columns)})"
                )
            )


def _table_exists(connection: Connection, table_name: str) -> bool:
    return bool(
        _scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'us_share' AND table_name = :table_name
            """,
            {"table_name": table_name},
        )
    )


def _foreign_key_exists(
    connection: Connection,
    table_name: str,
    constraint_name: str,
) -> bool:
    return bool(
        _scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM information_schema.referential_constraints
            WHERE constraint_schema = 'us_share'
              AND table_name = :table_name
              AND constraint_name = :constraint_name
            """,
            {"table_name": table_name, "constraint_name": constraint_name},
        )
    )


def _table_row_count(connection: Connection, table_name: str) -> int:
    return _scalar(connection, f"SELECT COUNT(*) FROM us_share.{table_name}")


def _asset_rows(connection: Connection, table_name: str, asset_type: str) -> int:
    return _scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM us_share.{table_name} AS p
        JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
        WHERE i.asset_type = :asset_type
        """,
        {"asset_type": asset_type},
    )


def _non_asset_rows(connection: Connection, table_name: str, asset_type: str) -> int:
    return _scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM us_share.{table_name} AS p
        JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
        WHERE i.asset_type != :asset_type
        """,
        {"asset_type": asset_type},
    )


def _missing_compact_rows(connection: Connection, compact_table: str) -> int:
    return _scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM us_share.etf_daily_price AS s
        JOIN us_share.instrument AS i ON i.instrument_id = s.instrument_id
        LEFT JOIN us_share.{compact_table} AS t
          ON t.etf_daily_price_id = s.etf_daily_price_id
        WHERE i.asset_type = 'etf' AND t.etf_daily_price_id IS NULL
        """,
    )


def _extra_compact_rows(connection: Connection, compact_table: str) -> int:
    return _scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM us_share.{compact_table} AS t
        LEFT JOIN us_share.etf_daily_price AS s
          ON s.etf_daily_price_id = t.etf_daily_price_id
        WHERE s.etf_daily_price_id IS NULL
        """,
    )


def _etf_sample_signature(
    connection: Connection,
    *,
    table_name: str,
    require_asset_type: str | None = None,
) -> tuple[int, int]:
    join_sql = ""
    type_sql = ""
    parameters: dict[str, object] = {}
    if require_asset_type is not None:
        join_sql = "JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id"
        type_sql = "i.asset_type = :asset_type AND"
        parameters["asset_type"] = require_asset_type
    row = connection.execute(
        text(
            f"""
            SELECT COUNT(*) AS sample_rows,
                   COALESCE(BIT_XOR(CAST(CRC32(CONCAT_WS('|',
                     p.instrument_id, p.trade_date, p.open, p.high, p.low, p.close,
                     p.adjusted_close, p.volume, p.currency, p.source
                   )) AS UNSIGNED)), 0) AS sample_checksum
            FROM us_share.{table_name} AS p
            {join_sql}
            WHERE {type_sql}
              MOD(CRC32(CONCAT(p.instrument_id, ':', p.trade_date)),
                  {SAMPLE_MODULUS}) = 0
            """
        ),
        parameters,
    ).mappings().one()
    return int(row["sample_rows"]), int(row["sample_checksum"])


def validate_backup_file(backup_file: Path | str) -> BackupEvidence:
    """Validate an absolute SQL/SQL.GZ backup and hash its uncompressed bytes."""
    path = Path(backup_file).expanduser()
    if not path.is_absolute():
        raise ValueError("backup_file must be an absolute path")
    if not path.is_file():
        raise ValueError(f"backup_file does not exist: {path}")
    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise ValueError("backup_file must not be empty")

    digest = hashlib.sha256()
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    try:
        with opener(path, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except (OSError, EOFError) as exc:
        raise ValueError(f"backup_file failed integrity validation: {path}") from exc
    return BackupEvidence(str(path.resolve()), size_bytes, digest.hexdigest())


def _require_copy_ready(plan: FundSplitPlan) -> None:
    if plan.source_fund_rows <= 0:
        raise RuntimeError("no Fund rows are classified in etf_daily_price; refresh metadata first")
    if plan.source_unexpected_rows:
        raise RuntimeError(
            f"etf_daily_price contains {plan.source_unexpected_rows} non-ETF/non-Fund rows"
        )
    if plan.target_total_rows:
        raise RuntimeError("fund_daily_price must be empty before starting a new split run")
    if plan.target_non_fund_rows:
        raise RuntimeError("fund_daily_price contains non-Fund instruments")


def _prepare_target_for_copy(engine: Engine) -> None:
    """Drop rebuildable non-unique indexes while the maintenance-window copy runs."""
    with engine.begin() as connection:
        for index_name in TARGET_SECONDARY_INDEXES:
            if _index_exists(connection, "fund_daily_price", index_name):
                connection.execute(
                    text(f"ALTER TABLE us_share.fund_daily_price DROP INDEX {index_name}")
                )


def _restore_target_indexes(engine: Engine) -> None:
    """Restore the canonical Fund table indexes before verification can pass."""
    with engine.begin() as connection:
        for index_name, columns in TARGET_SECONDARY_INDEXES.items():
            if _index_exists(connection, "fund_daily_price", index_name):
                continue
            column_sql = ", ".join(columns)
            connection.execute(
                text(
                    f"CREATE INDEX {index_name} "
                    f"ON us_share.fund_daily_price ({column_sql})"
                )
            )


def _prepare_source_for_finalize(engine: Engine) -> None:
    """Drop rebuildable ETF indexes before deleting most rows from the source table."""
    with engine.begin() as connection:
        for index_name in SOURCE_SECONDARY_INDEXES:
            if _index_exists(connection, "etf_daily_price", index_name):
                connection.execute(
                    text(f"ALTER TABLE us_share.etf_daily_price DROP INDEX {index_name}")
                )


def _restore_source_indexes(engine: Engine) -> None:
    """Restore canonical ETF indexes after finalization or completed-run verification."""
    with engine.begin() as connection:
        for index_name, columns in SOURCE_SECONDARY_INDEXES.items():
            if _index_exists(connection, "etf_daily_price", index_name):
                continue
            column_sql = ", ".join(columns)
            connection.execute(
                text(
                    f"CREATE INDEX {index_name} "
                    f"ON us_share.etf_daily_price ({column_sql})"
                )
            )


def _index_exists(connection: Connection, table_name: str, index_name: str) -> bool:
    return bool(
        _scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM information_schema.statistics
            WHERE table_schema = 'us_share'
              AND table_name = :table_name
              AND index_name = :index_name
            """,
            {"table_name": table_name, "index_name": index_name},
        )
    )


def _create_split_run(
    connection: Connection,
    *,
    plan: FundSplitPlan,
    chunk_size: int,
    backup: BackupEvidence,
) -> int:
    result = connection.execute(
        fund_daily_price_split_run.insert().values(
            status="copying",
            source_total_before=plan.source_total_rows,
            source_fund_rows=plan.source_fund_rows,
            target_rows_before=plan.target_total_rows,
            chunk_size=chunk_size,
            backup_path=backup.path,
            backup_size_bytes=backup.size_bytes,
            backup_sha256=backup.sha256,
        )
    )
    return int(result.inserted_primary_key[0])


def _load_run(
    connection: Connection,
    *,
    run_id: int,
    for_update: bool = False,
) -> dict[str, Any]:
    statement = select(fund_daily_price_split_run).where(
        fund_daily_price_split_run.c.fund_split_run_id == run_id
    )
    if for_update:
        statement = statement.with_for_update()
    row = connection.execute(statement).mappings().first()
    if row is None:
        raise ValueError(f"Fund split run {run_id} not found")
    return dict(row)


def _next_source_id(
    connection: Connection,
    *,
    after_source_id: int,
    chunk_size: int,
) -> int | None:
    value = connection.execute(
        text(
            """
            SELECT MAX(chunk.etf_daily_price_id)
            FROM (
              SELECT p.etf_daily_price_id
              FROM us_share.etf_daily_price AS p
              JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
              WHERE i.asset_type = 'fund'
                AND p.etf_daily_price_id > :after_source_id
              ORDER BY p.etf_daily_price_id
              LIMIT :chunk_size
            ) AS chunk
            """
        ),
        {"after_source_id": after_source_id, "chunk_size": chunk_size},
    ).scalar_one()
    return int(value) if value is not None else None


def _copy_source_range(
    connection: Connection,
    *,
    after_source_id: int,
    through_source_id: int,
) -> int:
    rows = _scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM us_share.etf_daily_price AS p
        JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
        WHERE i.asset_type = 'fund'
          AND p.etf_daily_price_id > :after_source_id
          AND p.etf_daily_price_id <= :through_source_id
        """,
        {"after_source_id": after_source_id, "through_source_id": through_source_id},
    )
    columns = ", ".join(PRICE_COPY_COLUMNS)
    selected = ", ".join(f"p.{column}" for column in PRICE_COPY_COLUMNS)
    updates = ", ".join(f"{column}=VALUES({column})" for column in PRICE_UPDATE_COLUMNS)
    connection.execute(
        text(
            f"""
            INSERT INTO us_share.fund_daily_price ({columns})
            SELECT {selected}
            FROM us_share.etf_daily_price AS p
            JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
            WHERE i.asset_type = 'fund'
              AND p.etf_daily_price_id > :after_source_id
              AND p.etf_daily_price_id <= :through_source_id
            ON DUPLICATE KEY UPDATE {updates}
            """
        ),
        {"after_source_id": after_source_id, "through_source_id": through_source_id},
    )
    return rows


def _delete_source_range(
    connection: Connection,
    *,
    after_source_id: int,
    through_source_id: int,
) -> int:
    result = connection.execute(
        text(
            """
            DELETE p
            FROM us_share.etf_daily_price AS p
            JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id
            WHERE i.asset_type = 'fund'
              AND p.etf_daily_price_id > :after_source_id
              AND p.etf_daily_price_id <= :through_source_id
            """
        ),
        {"after_source_id": after_source_id, "through_source_id": through_source_id},
    )
    return int(result.rowcount or 0)


def _pre_finalize_details(connection: Connection) -> dict[str, int]:
    details = _common_verification_details(connection)
    details.update(
        {
            "missing_target_rows": _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM us_share.etf_daily_price AS s
                JOIN us_share.instrument AS i ON i.instrument_id = s.instrument_id
                LEFT JOIN us_share.fund_daily_price AS t
                  ON t.instrument_id = s.instrument_id AND t.trade_date = s.trade_date
                WHERE i.asset_type = 'fund' AND t.fund_daily_price_id IS NULL
                """,
            ),
            "extra_target_rows": _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM us_share.fund_daily_price AS t
                LEFT JOIN us_share.etf_daily_price AS s
                  ON s.instrument_id = t.instrument_id AND s.trade_date = t.trade_date
                WHERE s.etf_daily_price_id IS NULL
                """,
            ),
        }
    )
    source_count, source_checksum = _sample_signature(connection, table_name="etf_daily_price")
    target_count, target_checksum = _sample_signature(connection, table_name="fund_daily_price")
    details.update(
        {
            "source_sample_rows": source_count,
            "source_sample_checksum": source_checksum,
            "target_sample_rows": target_count,
            "target_sample_checksum": target_checksum,
        }
    )
    return details


def _post_finalize_details(connection: Connection, run: dict[str, Any]) -> dict[str, int]:
    details = _common_verification_details(connection)
    target_count, target_checksum = _sample_signature(connection, table_name="fund_daily_price")
    stored = json.loads(str(run["verification_details"] or "{}"))
    details.update(
        {
            "baseline_total_rows": int(run["source_total_before"]),
            "conserved_total_rows": details["source_total_rows"] + details["target_total_rows"],
            "expected_target_rows": int(run["source_fund_rows"]),
            "expected_target_sample_rows": int(stored.get("source_sample_rows", -1)),
            "expected_target_sample_checksum": int(
                stored.get("source_sample_checksum", -1)
            ),
            "target_sample_rows": target_count,
            "target_sample_checksum": target_checksum,
        }
    )
    return details


def _common_verification_details(connection: Connection) -> dict[str, int]:
    plan = plan_fund_daily_prices(connection)
    return {
        "source_total_rows": plan.source_total_rows,
        "source_fund_rows": plan.source_fund_rows,
        "source_unexpected_rows": plan.source_unexpected_rows,
        "target_total_rows": plan.target_total_rows,
        "target_non_fund_rows": plan.target_non_fund_rows,
        "source_duplicate_groups": _duplicate_groups(connection, "etf_daily_price"),
        "target_duplicate_groups": _duplicate_groups(connection, "fund_daily_price"),
    }


def _pre_finalize_passed(details: dict[str, int], run: dict[str, Any]) -> bool:
    return all(
        (
            details["source_total_rows"] == int(run["source_total_before"]),
            details["source_fund_rows"] == int(run["source_fund_rows"]),
            details["source_unexpected_rows"] == 0,
            details["target_total_rows"] == int(run["source_fund_rows"]),
            details["target_non_fund_rows"] == 0,
            details["source_duplicate_groups"] == 0,
            details["target_duplicate_groups"] == 0,
            details["missing_target_rows"] == 0,
            details["extra_target_rows"] == 0,
            details["source_sample_rows"] == details["target_sample_rows"],
            details["source_sample_checksum"] == details["target_sample_checksum"],
        )
    )


def _post_finalize_passed(details: dict[str, int], run: dict[str, Any]) -> bool:
    return all(
        (
            details["source_fund_rows"] == 0,
            details["source_unexpected_rows"] == 0,
            details["source_total_rows"]
            == int(run["source_total_before"]) - int(run["source_fund_rows"]),
            details["target_total_rows"] == int(run["source_fund_rows"]),
            details["target_non_fund_rows"] == 0,
            details["source_duplicate_groups"] == 0,
            details["target_duplicate_groups"] == 0,
            details["conserved_total_rows"] == details["baseline_total_rows"],
            details["target_sample_rows"] == details["expected_target_sample_rows"],
            details["target_sample_checksum"]
            == details["expected_target_sample_checksum"],
        )
    )


def _sample_signature(connection: Connection, *, table_name: str) -> tuple[int, int]:
    id_column = f"{table_name}_id"
    if table_name == "etf_daily_price":
        type_join = (
            "JOIN us_share.instrument AS i ON i.instrument_id = p.instrument_id "
            "WHERE i.asset_type = 'fund' AND "
        )
    else:
        type_join = "WHERE "
    row = connection.execute(
        text(
            f"""
            SELECT COUNT(*) AS sample_rows,
                   COALESCE(BIT_XOR(CAST(CRC32(CONCAT_WS('|',
                     p.instrument_id, p.trade_date, p.open, p.high, p.low, p.close,
                     p.adjusted_close, p.volume, p.currency, p.source
                   )) AS UNSIGNED)), 0) AS sample_checksum
            FROM us_share.{table_name} AS p
            {type_join}MOD(CRC32(CONCAT(p.instrument_id, ':', p.trade_date)),
                            {SAMPLE_MODULUS}) = 0
              AND p.{id_column} > 0
            """
        )
    ).mappings().one()
    return int(row["sample_rows"]), int(row["sample_checksum"])


def _duplicate_groups(connection: Connection, table_name: str) -> int:
    return _scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM (
          SELECT instrument_id, trade_date
          FROM us_share.{table_name}
          GROUP BY instrument_id, trade_date
          HAVING COUNT(*) > 1
        ) AS duplicate_groups
        """,
    )


def _fingerprint(details: dict[str, int]) -> str:
    payload = json.dumps(details, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _scalar(
    connection: Connection,
    sql: str,
    parameters: dict[str, object] | None = None,
) -> int:
    return int(connection.execute(text(sql), parameters or {}).scalar_one())


def _validate_chunk_options(*, chunk_size: int, max_chunks: int | None) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if max_chunks is not None and max_chunks <= 0:
        raise ValueError("max_chunks must be positive")


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
