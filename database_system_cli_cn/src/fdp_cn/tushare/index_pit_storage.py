"""MySQL storage primitives for index source data and PIT tables."""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from fdp_cn.tushare.errors import (
    TushareDataError,
    TusharePostCommitStorageError,
    TushareStorageError,
)
from fdp_cn.tushare.models import EndpointSpec


A_SHARE_SCHEMA = "a_share"
SW_PIT_TABLE = "idx_sw_member_pit"
SW_PIT_STAGE_TABLE = "idx_sw_member_pit__staging"
SW_PIT_BACKUP_TABLE = "idx_sw_member_pit__backup"
STYLE_PIT_TABLE = "idx_style_member_pit"
GENERAL_PIT_TABLE = "idx_member_pit"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SOURCE_UNIQUE_KEYS: Mapping[str, tuple[str, ...]] = {
    "hq_idx_basic": ("ts_code",),
    "hq_idx_sw_classify": ("src", "level", "index_code"),
    "hq_idx_sw_daily": ("trade_date", "ts_code"),
    "hq_idx_sw_member": ("index_code", "con_code", "in_date"),
    "hq_idx_sw_member_all": (
        "ts_code",
        "l1_code",
        "l2_code",
        "l3_code",
        "in_date",
    ),
}


@dataclass(frozen=True)
class IndexMetadata:
    index_code: str
    index_name: str
    index_fullname: str | None
    market: str
    publisher: str
    category: str
    index_type: str | None
    list_date: date | None
    exp_date: date | None


def ensure_source_unique_keys(
    engine: Engine,
    specs: Sequence[EndpointSpec],
) -> None:
    """Add only exact guarded unique keys required by source-page upserts."""
    required = {
        spec.target_table: SOURCE_UNIQUE_KEYS[spec.target_table]
        for spec in specs
        if spec.target_table in SOURCE_UNIQUE_KEYS
    }
    with engine.connect() as connection:
        _require_mysql(connection)
        for table_name, key in required.items():
            _ensure_one_source_unique_key(connection, table_name, key)


def ensure_index_pit_tables(engine: Engine) -> None:
    """Create the three user-facing PIT tables when they do not yet exist."""
    with engine.begin() as connection:
        _require_mysql(connection)
        connection.execute(text(_SW_PIT_DDL.format(table=_quote(SW_PIT_TABLE))))
        connection.execute(text(_WEIGHT_PIT_DDL.format(table=_quote(STYLE_PIT_TABLE))))
        connection.execute(text(_WEIGHT_PIT_DDL.format(table=_quote(GENERAL_PIT_TABLE))))


def prepare_sw_pit_staging(
    engine: Engine,
    *,
    reset: bool,
    owner_run_id: int,
) -> None:
    """Create or resume the fixed SW staging table."""
    if owner_run_id <= 0:
        raise ValueError("owner_run_id must be positive")
    ensure_index_pit_tables(engine)
    with engine.begin() as connection:
        _require_mysql(connection)
        if reset:
            connection.execute(
                text(
                    f"DROP TABLE IF EXISTS `{A_SHARE_SCHEMA}`.{_quote(SW_PIT_STAGE_TABLE)}"
                )
            )
        # Build from the current product DDL rather than cloning an older final
        # table: a prior release may carry retired, multi-gigabyte indexes.
        connection.execute(
            text(_SW_PIT_DDL.format(table=_quote(SW_PIT_STAGE_TABLE)))
        )
        owner = _sw_pit_owner(owner_run_id)
        current_owner = _table_comment(connection, SW_PIT_STAGE_TABLE)
        if not reset and current_owner != owner:
            raise TushareStorageError(
                "SW PIT staging belongs to another run; explicit reset is required"
            )
        connection.execute(
            text(
                f"ALTER TABLE `{A_SHARE_SCHEMA}`.{_quote(SW_PIT_STAGE_TABLE)} "
                "COMMENT=:owner"
            ),
            {"owner": owner},
        )


@contextmanager
def sw_pit_workflow_lease(
    engine: Engine,
    *,
    lock_timeout_seconds: int = 0,
) -> Iterator[None]:
    """Prevent two SW staging/reset/publish workflows from interleaving."""
    lock_name = "j21-cn:index-pit:sw-pit-workflow"
    with engine.connect() as connection:
        _require_mysql(connection)
        acquired = False
        body_error: BaseException | None = None
        try:
            acquired_value = connection.execute(
                text("SELECT GET_LOCK(:name, :timeout)"),
                {"name": lock_name, "timeout": lock_timeout_seconds},
            ).scalar()
            if acquired_value not in {1, True}:
                raise TushareStorageError("Another SW PIT workflow is already running")
            acquired = True
            _finish_implicit_transaction(connection, commit=True)
            yield
        except BaseException as error:
            body_error = error
            raise
        finally:
            if acquired:
                try:
                    _finish_implicit_transaction(connection, commit=False)
                    released = connection.execute(
                        text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name}
                    ).scalar()
                    _finish_implicit_transaction(connection, commit=True)
                    if released not in {1, True}:
                        raise TushareStorageError(
                            "SW PIT workflow lock release was not confirmed"
                        )
                except BaseException as cleanup_error:
                    connection.invalidate()
                    if body_error is None:
                        raise TushareStorageError(
                            "SW PIT workflow lock cleanup failed"
                        ) from cleanup_error


@contextmanager
def index_pit_page_transaction(
    engine: Engine,
    table_name: str,
    *,
    lock_timeout_seconds: int = 10,
) -> Iterator[Connection]:
    """Hold one table-scoped MySQL named lock around a page transaction."""
    _quote(table_name)
    lock_name = f"j21-cn:index-pit:{A_SHARE_SCHEMA}:{table_name}"
    if len(lock_name.encode("utf-8")) > 64:
        raise TushareStorageError("Index PIT named lock exceeds MySQL limit")
    with engine.connect() as connection:
        _require_mysql(connection)
        acquired = False
        page_committed = False
        body_error: BaseException | None = None
        try:
            acquired_value = connection.execute(
                text("SELECT GET_LOCK(:name, :timeout)"),
                {"name": lock_name, "timeout": lock_timeout_seconds},
            ).scalar()
            if acquired_value not in {1, True}:
                raise TushareStorageError("Timed out acquiring the index PIT table lock")
            acquired = True
            _finish_implicit_transaction(connection, commit=True)
            with connection.begin():
                yield connection
            page_committed = True
        except BaseException as error:
            body_error = error
            raise
        finally:
            if acquired:
                try:
                    _finish_implicit_transaction(connection, commit=False)
                    released = connection.execute(
                        text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name}
                    ).scalar()
                    _finish_implicit_transaction(connection, commit=True)
                    if released not in {1, True}:
                        raise TushareStorageError(
                            "Index PIT table lock release was not confirmed"
                        )
                except BaseException as cleanup_error:
                    connection.invalidate()
                    if page_committed and body_error is None:
                        raise TusharePostCommitStorageError(
                            "Index PIT page committed, but its table lock cleanup failed"
                        ) from cleanup_error
                    if body_error is None:
                        raise TushareStorageError(
                            "Index PIT table lock cleanup failed"
                        ) from cleanup_error


def sw_pit_table_state(engine: Engine) -> dict[str, object]:
    """Return the final/staging/backup state used to reconcile atomic publish."""
    with engine.connect() as connection:
        _require_mysql(connection)
        return {
            "final": _table_exists(connection, SW_PIT_TABLE),
            "staging": _table_exists(connection, SW_PIT_STAGE_TABLE),
            "backup": _table_exists(connection, SW_PIT_BACKUP_TABLE),
            "final_owner": _table_comment(connection, SW_PIT_TABLE),
            "staging_owner": _table_comment(connection, SW_PIT_STAGE_TABLE),
        }


def insert_sw_pit_partition(
    connection: Connection,
    *,
    version: str,
    date_from: date,
    date_to: date,
) -> int:
    """Materialize one open-trading-day SW membership partition."""
    if date_to < date_from:
        raise ValueError("date_to must not be before date_from")
    if version == "SW2014":
        statement = _SW2014_INSERT
    elif version == "SW2021":
        statement = _SW2021_INSERT
    else:
        raise ValueError("version must be SW2014 or SW2021")
    result = connection.execute(
        text(statement),
        {"date_from": date_from, "date_to": date_to},
    )
    return max(int(result.rowcount or 0), 0)


def validate_sw_pit_staging(
    engine: Engine,
    *,
    date_from: date,
    date_to: date,
) -> dict[str, object]:
    """Reject empty levels, duplicate stock/day levels, and date leakage."""
    return _validate_sw_pit_table(
        engine,
        table_name=SW_PIT_STAGE_TABLE,
        date_from=date_from,
        date_to=date_to,
    )


def validate_sw_pit_final(
    engine: Engine,
    *,
    date_from: date,
    date_to: date,
) -> dict[str, object]:
    """Recompute the published table fingerprint before crash recovery."""
    return _validate_sw_pit_table(
        engine,
        table_name=SW_PIT_TABLE,
        date_from=date_from,
        date_to=date_to,
    )


def _validate_sw_pit_table(
    engine: Engine,
    *,
    table_name: str,
    date_from: date,
    date_to: date,
) -> dict[str, object]:
    with engine.connect() as connection:
        _require_mysql(connection)
        table = f"`{A_SHARE_SCHEMA}`.{_quote(table_name)}"
        summary = connection.execute(
            text(
                f"SELECT COUNT(*) AS row_count, MIN(trade_date) AS min_date, "
                f"MAX(trade_date) AS max_date FROM {table}"
            )
        ).mappings().one()
        total = int(summary["row_count"] or 0)
        if total <= 0:
            raise TushareDataError(f"{table_name} is empty")
        leaked = int(
            connection.execute(
                text(
                    f"SELECT COUNT(*) FROM {table} "
                    "WHERE trade_date < :date_from OR trade_date > :date_to"
                ),
                {"date_from": date_from, "date_to": date_to},
            ).scalar()
        )
        if leaked:
            raise TushareDataError(f"{table_name} contains rows outside its plan")
        overlap = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    f"SELECT 1 FROM {table} "
                    "GROUP BY trade_date, industry_version, level, con_code "
                    "HAVING COUNT(*) > 1 LIMIT 1) AS duplicate_assignment"
                )
            ).scalar()
        )
        if overlap:
            raise TushareDataError(
                f"{table_name} assigns one stock to multiple industries at one level/day"
            )
        counts = {
            f"{row.industry_version}_{row.level}": int(row.row_count)
            for row in connection.execute(
                text(
                    f"SELECT industry_version, level, COUNT(*) AS row_count FROM {table} "
                    "GROUP BY industry_version, level"
                )
            )
        }
        expected = set()
        if date_from <= date(2021, 12, 10):
            expected.update({"SW2014_L1", "SW2014_L2", "SW2014_L3"})
        if date_to >= date(2021, 12, 13):
            expected.update({"SW2021_L1", "SW2021_L2", "SW2021_L3"})
        missing = sorted(expected - set(counts))
        if missing:
            raise TushareDataError(
                f"{table_name} is missing version/level rows: " + ", ".join(missing)
            )
        min_date = summary["min_date"]
        max_date = summary["max_date"]
        return {
            "rows": total,
            "min_date": min_date.isoformat() if min_date is not None else None,
            "max_date": max_date.isoformat() if max_date is not None else None,
            **counts,
        }


def swap_sw_pit_staging(engine: Engine, *, owner_run_id: int) -> None:
    """Atomically publish the validated staging table and remove the old copy."""
    with engine.connect() as connection:
        _require_mysql(connection)
        stage_exists = _table_exists(connection, SW_PIT_STAGE_TABLE)
        final_exists = _table_exists(connection, SW_PIT_TABLE)
        backup_exists = _table_exists(connection, SW_PIT_BACKUP_TABLE)
        if not stage_exists:
            if final_exists and _table_comment(connection, SW_PIT_TABLE) == _sw_pit_owner(
                owner_run_id
            ):
                if backup_exists:
                    connection.execute(
                        text(
                            f"DROP TABLE `{A_SHARE_SCHEMA}`."
                            f"{_quote(SW_PIT_BACKUP_TABLE)}"
                        )
                    )
                return
            raise TushareStorageError("SW PIT staging and final tables are both missing")
        if _table_comment(connection, SW_PIT_STAGE_TABLE) != _sw_pit_owner(owner_run_id):
            raise TushareStorageError("SW PIT staging belongs to another run")
        if backup_exists:
            connection.execute(
                text(
                    f"DROP TABLE `{A_SHARE_SCHEMA}`.{_quote(SW_PIT_BACKUP_TABLE)}"
                )
            )
        if final_exists:
            connection.execute(
                text(
                    f"RENAME TABLE `{A_SHARE_SCHEMA}`.{_quote(SW_PIT_TABLE)} "
                    f"TO `{A_SHARE_SCHEMA}`.{_quote(SW_PIT_BACKUP_TABLE)}, "
                    f"`{A_SHARE_SCHEMA}`.{_quote(SW_PIT_STAGE_TABLE)} "
                    f"TO `{A_SHARE_SCHEMA}`.{_quote(SW_PIT_TABLE)}"
                )
            )
            connection.execute(
                text(
                    f"DROP TABLE `{A_SHARE_SCHEMA}`.{_quote(SW_PIT_BACKUP_TABLE)}"
                )
            )
        else:
            connection.execute(
                text(
                    f"RENAME TABLE `{A_SHARE_SCHEMA}`.{_quote(SW_PIT_STAGE_TABLE)} "
                    f"TO `{A_SHARE_SCHEMA}`.{_quote(SW_PIT_TABLE)}"
                )
            )


def load_index_metadata(engine: Engine) -> tuple[IndexMetadata, ...]:
    """Read one exact metadata row per index from the refreshed source table."""
    sql = text(
        "SELECT ts_code, name, fullname, market, publisher, category, index_type, "
        "list_date, exp_date FROM a_share.hq_idx_basic ORDER BY ts_code"
    )
    with engine.connect() as connection:
        _require_mysql(connection)
        rows = connection.execute(sql).mappings().all()
    result: list[IndexMetadata] = []
    seen: set[str] = set()
    for row in rows:
        code = str(row["ts_code"] or "").strip().upper()
        if not code:
            raise TushareDataError("hq_idx_basic contains an empty ts_code")
        if code in seen:
            raise TushareDataError(f"hq_idx_basic contains duplicate ts_code {code}")
        seen.add(code)
        result.append(
            IndexMetadata(
                index_code=code,
                index_name=str(row["name"] or "").strip(),
                index_fullname=_optional_text(row["fullname"]),
                market=str(row["market"] or "").strip(),
                publisher=str(row["publisher"] or "").strip(),
                category=str(row["category"] or "").strip(),
                index_type=_optional_text(row["index_type"]),
                list_date=_optional_date(row["list_date"], label="list_date"),
                exp_date=_optional_date(row["exp_date"], label="exp_date"),
            )
        )
    return tuple(result)


def load_sw_codes(engine: Engine) -> tuple[tuple[str, str], ...]:
    """Return SW2014 all-level codes and SW2021 L1 query roots."""
    sql = text(
        "SELECT src, level, index_code FROM a_share.hq_idx_sw_classify "
        "WHERE (src='SW2014' AND level IN ('L1','L2','L3')) "
        "OR (src='SW2021' AND level='L1') "
        "ORDER BY src, level, index_code"
    )
    with engine.connect() as connection:
        _require_mysql(connection)
        rows = connection.execute(sql).mappings().all()
    values = tuple((str(row["src"]), str(row["index_code"])) for row in rows)
    if not any(src == "SW2014" for src, _code in values):
        raise TushareDataError("hq_idx_sw_classify has no SW2014 codes")
    if not any(src == "SW2021" for src, _code in values):
        raise TushareDataError("hq_idx_sw_classify has no SW2021 L1 codes")
    return values


def upsert_weight_stage(
    connection: Connection,
    *,
    run_id: int,
    unit_key: str,
    rows: Sequence[Mapping[str, object]],
) -> int:
    if not rows:
        return 0
    seen: dict[tuple[object, object, object], object] = {}
    for row in rows:
        key = (row["trade_date"], row["index_code"], row["con_code"])
        previous = seen.get(key)
        if previous is not None and previous != row["weight"]:
            raise TushareDataError(
                "index_weight page contains conflicting weights for one business key"
            )
        seen[key] = row["weight"]
    for key_chunk in _chunks(tuple(seen), 500):
        clauses: list[str] = []
        bindings: dict[str, object] = {"run_id": run_id, "unit_key": unit_key}
        for number, (trade_date, index_code, con_code) in enumerate(key_chunk):
            clauses.append(
                f"(trade_date=:trade_date_{number} AND "
                f"index_code=:index_code_{number} AND con_code=:con_code_{number})"
            )
            bindings[f"trade_date_{number}"] = trade_date
            bindings[f"index_code_{number}"] = index_code
            bindings[f"con_code_{number}"] = con_code
        existing = connection.execute(
            text(
                "SELECT trade_date, index_code, con_code, weight "
                "FROM system_cn.index_weight_stage "
                "WHERE run_id=:run_id AND unit_key=:unit_key AND ("
                + " OR ".join(clauses)
                + ")"
            ),
            bindings,
        ).mappings()
        for row in existing:
            key = (row["trade_date"], row["index_code"], row["con_code"])
            if Decimal(str(row["weight"])) != Decimal(str(seen[key])):
                raise TushareDataError(
                    "index_weight pages conflict on one staged business key"
                )
    values = [
        {
            "run_id": run_id,
            "unit_key": unit_key,
            "trade_date": row["trade_date"],
            "index_code": row["index_code"],
            "con_code": row["con_code"],
            "weight": row["weight"],
        }
        for row in rows
    ]
    connection.execute(
        text(
            "INSERT INTO system_cn.index_weight_stage "
            "(run_id, unit_key, trade_date, index_code, con_code, weight) "
            "VALUES (:run_id, :unit_key, :trade_date, :index_code, :con_code, :weight) "
            "ON DUPLICATE KEY UPDATE weight=VALUES(weight)"
        ),
        values,
    )
    return len(values)


def publish_weight_unit(
    connection: Connection,
    *,
    run_id: int,
    unit_key: str,
    table_name: str,
    metadata: IndexMetadata,
    month_start: date,
    month_end: date,
) -> int:
    """Replace one index-month snapshot atomically from the durable stage."""
    if table_name not in {STYLE_PIT_TABLE, GENERAL_PIT_TABLE}:
        raise TushareStorageError("Invalid index weight PIT table")
    stage_metrics = weight_unit_metrics(
        connection,
        run_id=run_id,
        unit_key=unit_key,
    )
    staged_rows = int(stage_metrics["row_count"] or 0)
    if staged_rows <= 0:
        raise TushareDataError("index_weight stage is empty")
    if (
        int(stage_metrics["index_codes"] or 0) != 1
        or stage_metrics["min_index_code"] != metadata.index_code
        or stage_metrics["max_index_code"] != metadata.index_code
        or stage_metrics["min_date"] < month_start
        or stage_metrics["max_date"] > month_end
    ):
        raise TushareDataError("index_weight stage contains rows outside its unit scope")
    table = f"`{A_SHARE_SCHEMA}`.{_quote(table_name)}"
    connection.execute(
        text(
            f"DELETE FROM {table} WHERE index_code=:index_code "
            "AND trade_date BETWEEN :month_start AND :month_end"
        ),
        {
            "index_code": metadata.index_code,
            "month_start": month_start,
            "month_end": month_end,
        },
    )
    result = connection.execute(
        text(
            f"INSERT INTO {table} "
            "(trade_date, index_code, con_code, weight, index_name, index_fullname, "
            "market, publisher, category, index_type, list_date, exp_date) "
            "SELECT trade_date, index_code, con_code, weight, :index_name, "
            ":index_fullname, :market, :publisher, :category, :index_type, "
            ":list_date, :exp_date FROM system_cn.index_weight_stage "
            "WHERE run_id=:run_id AND unit_key=:unit_key "
            "AND index_code=:index_code "
            "AND trade_date BETWEEN :month_start AND :month_end "
            "ON DUPLICATE KEY UPDATE weight=VALUES(weight), "
            "index_name=VALUES(index_name), index_fullname=VALUES(index_fullname), "
            "market=VALUES(market), publisher=VALUES(publisher), "
            "category=VALUES(category), index_type=VALUES(index_type), "
            "list_date=VALUES(list_date), exp_date=VALUES(exp_date)"
        ),
        {
            "run_id": run_id,
            "unit_key": unit_key,
            "index_code": metadata.index_code,
            "month_start": month_start,
            "month_end": month_end,
            "index_name": metadata.index_name,
            "index_fullname": metadata.index_fullname,
            "market": metadata.market,
            "publisher": metadata.publisher,
            "category": metadata.category,
            "index_type": metadata.index_type,
            "list_date": metadata.list_date,
            "exp_date": metadata.exp_date,
        },
    )
    published = max(int(result.rowcount or 0), 0)
    target_rows = int(
        connection.execute(
            text(
                f"SELECT COUNT(*) FROM {table} WHERE index_code=:index_code "
                "AND trade_date BETWEEN :month_start AND :month_end"
            ),
            {
                "index_code": metadata.index_code,
                "month_start": month_start,
                "month_end": month_end,
            },
        ).scalar()
    )
    if published != staged_rows or target_rows != staged_rows:
        raise TushareStorageError(
            "index_weight published row count does not match its validated stage"
        )
    connection.execute(
        text(
            "DELETE FROM system_cn.index_weight_stage "
            "WHERE run_id=:run_id AND unit_key=:unit_key"
        ),
        {"run_id": run_id, "unit_key": unit_key},
    )
    return published


def weight_unit_metrics(
    connection: Connection,
    *,
    run_id: int,
    unit_key: str,
) -> dict[str, object]:
    row = connection.execute(
        text(
            "SELECT COALESCE(SUM(row_count), 0) AS row_count, "
            "COUNT(*) AS snapshots, MIN(weight_sum) AS min_weight_sum, "
            "MAX(weight_sum) AS max_weight_sum "
            "FROM (SELECT trade_date, COUNT(*) AS row_count, SUM(weight) AS weight_sum "
            "FROM system_cn.index_weight_stage "
            "WHERE run_id=:run_id AND unit_key=:unit_key GROUP BY trade_date) AS totals"
        ),
        {"run_id": run_id, "unit_key": unit_key},
    ).mappings().one()
    scope = connection.execute(
        text(
            "SELECT COUNT(DISTINCT index_code) AS index_codes, "
            "MIN(index_code) AS min_index_code, MAX(index_code) AS max_index_code, "
            "MIN(trade_date) AS min_date, MAX(trade_date) AS max_date "
            "FROM system_cn.index_weight_stage "
            "WHERE run_id=:run_id AND unit_key=:unit_key"
        ),
        {"run_id": run_id, "unit_key": unit_key},
    ).mappings().one()
    return {
        "row_count": int(row["row_count"] or 0),
        "snapshots": int(row["snapshots"] or 0),
        "min_weight_sum": _decimal_or_none(row["min_weight_sum"]),
        "max_weight_sum": _decimal_or_none(row["max_weight_sum"]),
        "index_codes": int(scope["index_codes"] or 0),
        "min_index_code": scope["min_index_code"],
        "max_index_code": scope["max_index_code"],
        "min_date": scope["min_date"],
        "max_date": scope["max_date"],
    }


def clear_weight_stage(connection: Connection, *, run_id: int, unit_key: str) -> None:
    connection.execute(
        text(
            "DELETE FROM system_cn.index_weight_stage "
            "WHERE run_id=:run_id AND unit_key=:unit_key"
        ),
        {"run_id": run_id, "unit_key": unit_key},
    )


def _ensure_one_source_unique_key(
    connection: Connection,
    table_name: str,
    key: tuple[str, ...],
) -> None:
    table = _quote(table_name)
    if not _table_exists(connection, table_name):
        raise TushareStorageError(f"Required source table a_share.{table_name} is missing")
    rows = connection.execute(
        text(
            "SELECT INDEX_NAME AS index_name, NON_UNIQUE AS non_unique, "
            "GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns_csv "
            "FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA=:schema AND TABLE_NAME=:table "
            "GROUP BY INDEX_NAME, NON_UNIQUE"
        ),
        {"schema": A_SHARE_SCHEMA, "table": table_name},
    ).mappings()
    indexes = {
        str(row["index_name"]): (
            int(row["non_unique"]),
            tuple(str(row["columns_csv"]).split(",")),
        )
        for row in rows
    }
    if any(non_unique == 0 and columns == key for non_unique, columns in indexes.values()):
        return
    null_condition = " OR ".join(f"{_quote(name)} IS NULL" for name in key)
    null_count = int(
        connection.execute(
            text(
                f"SELECT COUNT(*) FROM `{A_SHARE_SCHEMA}`.{table} "
                f"WHERE {null_condition}"
            )
        ).scalar()
    )
    if null_count:
        raise TushareStorageError(
            f"a_share.{table_name} has {null_count} null source business keys"
        )
    grouped = ", ".join(_quote(name) for name in key)
    duplicate = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM ("
                f"SELECT 1 FROM `{A_SHARE_SCHEMA}`.{table} GROUP BY {grouped} "
                "HAVING COUNT(*) > 1 LIMIT 1) AS duplicate_key"
            )
        ).scalar()
    )
    if duplicate:
        raise TushareStorageError(
            f"a_share.{table_name} has duplicate source business keys"
        )
    index_name = f"j21_uq_{table_name}_business_key"
    existing = indexes.get(index_name)
    if existing is not None:
        connection.execute(
            text(
                f"ALTER TABLE `{A_SHARE_SCHEMA}`.{table} "
                f"DROP INDEX {_quote(index_name)}"
            )
        )
    connection.execute(
        text(
            f"ALTER TABLE `{A_SHARE_SCHEMA}`.{table} ADD UNIQUE INDEX "
            f"{_quote(index_name)} ({grouped})"
        )
    )


def _table_exists(connection: Connection, table_name: str) -> bool:
    return bool(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=:schema AND TABLE_NAME=:table"
            ),
            {"schema": A_SHARE_SCHEMA, "table": table_name},
        ).scalar()
    )


def _table_comment(connection: Connection, table_name: str) -> str | None:
    value = connection.execute(
        text(
            "SELECT TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=:schema AND TABLE_NAME=:table"
        ),
        {"schema": A_SHARE_SCHEMA, "table": table_name},
    ).scalar()
    return str(value) if value is not None else None


def _sw_pit_owner(run_id: int) -> str:
    if run_id <= 0:
        raise ValueError("run_id must be positive")
    return f"j21_sw_pit_run:{run_id}"


def _chunks(values: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_date(value: object, *, label: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    raise TushareDataError(f"hq_idx_basic {label} is not a valid date: {raw}")


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _finish_implicit_transaction(connection: Connection, *, commit: bool) -> None:
    if not connection.in_transaction():
        return
    if commit:
        connection.commit()
    else:
        connection.rollback()


def _require_mysql(connection: Connection) -> None:
    if connection.dialect.name not in {"mysql", "mariadb"}:
        raise TushareStorageError("Index PIT storage requires MySQL or MariaDB")


def _quote(identifier: str) -> str:
    if not _IDENTIFIER.fullmatch(identifier):
        raise TushareStorageError("Unsafe index PIT SQL identifier")
    return f"`{identifier}`"


_SW_PIT_DDL = """
CREATE TABLE IF NOT EXISTS `a_share`.{table} (
    trade_date DATE NOT NULL,
    industry_version VARCHAR(8) NOT NULL,
    level VARCHAR(2) NOT NULL,
    index_code VARCHAR(20) NOT NULL,
    con_code VARCHAR(20) NOT NULL,
    in_date DATE NOT NULL,
    out_date DATE NULL,
    is_new VARCHAR(2) NOT NULL,
    source_endpoint VARCHAR(32) NOT NULL,
    PRIMARY KEY (trade_date, industry_version, level, index_code, con_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_WEIGHT_PIT_DDL = """
CREATE TABLE IF NOT EXISTS `a_share`.{table} (
    trade_date DATE NOT NULL,
    index_code VARCHAR(20) NOT NULL,
    con_code VARCHAR(20) NOT NULL,
    weight DECIMAL(25,8) NOT NULL,
    index_name VARCHAR(250) NOT NULL,
    index_fullname TEXT NULL,
    market VARCHAR(20) NOT NULL,
    publisher VARCHAR(250) NOT NULL,
    category VARCHAR(50) NOT NULL,
    index_type TEXT NULL,
    list_date DATE NULL,
    exp_date DATE NULL,
    PRIMARY KEY (trade_date, index_code, con_code),
    KEY ix_idx_member_pit_index_date (index_code, trade_date, con_code),
    KEY ix_idx_member_pit_stock_date (con_code, trade_date, index_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_SW2014_INSERT = f"""
INSERT INTO `a_share`.`{SW_PIT_STAGE_TABLE}`
    (trade_date, industry_version, level, index_code, con_code,
     in_date, out_date, is_new, source_endpoint)
SELECT cal.cal_date, 'SW2014', cls.level, member.index_code, member.con_code,
       MIN(member.in_date),
       CASE WHEN SUM(member.out_date IS NULL) > 0 THEN NULL ELSE MAX(member.out_date) END,
       MAX(member.is_new), 'index_member'
FROM `a_share`.`hq_trade_cal` AS cal
JOIN `a_share`.`hq_idx_sw_member` AS member
  ON cal.cal_date BETWEEN member.in_date AND COALESCE(member.out_date, '2021-12-10')
JOIN `a_share`.`hq_idx_sw_classify` AS cls
  ON cls.src='SW2014' AND cls.index_code=member.index_code
 AND cls.level IN ('L1','L2','L3')
WHERE cal.exchange='SSE' AND cal.is_open='1'
  AND cal.cal_date BETWEEN :date_from AND :date_to
  AND cal.cal_date BETWEEN '2014-02-21' AND '2021-12-10'
GROUP BY cal.cal_date, cls.level, member.index_code, member.con_code
"""

_SW2021_INSERT = f"""
INSERT INTO `a_share`.`{SW_PIT_STAGE_TABLE}`
    (trade_date, industry_version, level, index_code, con_code,
     in_date, out_date, is_new, source_endpoint)
SELECT cal.cal_date, 'SW2021', expanded.level, expanded.index_code,
       member.ts_code, MIN(member.in_date),
       CASE WHEN SUM(member.out_date IS NULL) > 0 THEN NULL ELSE MAX(member.out_date) END,
       MAX(member.is_new),
       'index_member_all'
FROM `a_share`.`hq_trade_cal` AS cal
JOIN `a_share`.`hq_idx_sw_member_all` AS member
  ON cal.cal_date BETWEEN member.in_date AND COALESCE(member.out_date, :date_to)
JOIN (
    SELECT id, 'L1' AS level, l1_code AS index_code
      FROM `a_share`.`hq_idx_sw_member_all`
    UNION ALL
    SELECT id, 'L2' AS level, l2_code AS index_code
      FROM `a_share`.`hq_idx_sw_member_all`
    UNION ALL
    SELECT id, 'L3' AS level, l3_code AS index_code
      FROM `a_share`.`hq_idx_sw_member_all`
) AS expanded ON expanded.id=member.id
WHERE cal.exchange='SSE' AND cal.is_open='1'
  AND cal.cal_date BETWEEN :date_from AND :date_to
  AND cal.cal_date >= '2021-12-13'
GROUP BY cal.cal_date, expanded.level, expanded.index_code, member.ts_code
"""
