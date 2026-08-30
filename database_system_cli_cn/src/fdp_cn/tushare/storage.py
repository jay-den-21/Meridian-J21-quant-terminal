"""Safe page writes into CN-owned ``a_share.hq_*`` tables."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import inspect, text

from fdp_cn.tushare.errors import (
    TushareDataError,
    TusharePostCommitStorageError,
    TushareRunLeaseCleanupError,
    TushareStorageError,
)
from fdp_cn.tushare.models import (
    EndpointSpec,
    ExternalTableContract,
    TusharePageWriteResult,
)


A_SHARE_SCHEMA = "a_share"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LOCK_INFO_KEY = "j21_cn_tushare_table_lock"
_RUN_LOCK_PREFIX = "j21-cn:tushare:run:"


@contextmanager
def tushare_run_lease(
    engine: Any,
    run_id: int,
    *,
    lock_timeout_seconds: int = 0,
):
    """Hold one dedicated MySQL named-lock connection for a Tushare run."""
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("run_id must be a positive integer")
    if (
        isinstance(lock_timeout_seconds, bool)
        or not isinstance(lock_timeout_seconds, int)
        or not 0 <= lock_timeout_seconds <= 60
    ):
        raise ValueError("lock_timeout_seconds must be an integer between 0 and 60")

    lock_name = _run_lock_name(run_id)
    try:
        connection_context = engine.connect()
    except Exception as error:
        raise TushareStorageError(
            "Could not open the Tushare run-lease connection"
        ) from error

    with connection_context as connection:
        _require_mysql(connection)
        acquired = False
        body_failure: BaseException | None = None
        try:
            _acquire_named_lock(
                connection,
                lock_name=lock_name,
                timeout_seconds=lock_timeout_seconds,
            )
            acquired = True
            _finish_implicit_transaction(connection, commit=True)
            yield
        except BaseException as error:
            body_failure = error
            raise
        finally:
            if acquired:
                try:
                    _finish_implicit_transaction(connection, commit=False)
                    _release_named_lock(connection, lock_name=lock_name)
                    _finish_implicit_transaction(connection, commit=True)
                except BaseException as cleanup_error:
                    _discard_connection(connection)
                    if body_failure is None:
                        raise TushareRunLeaseCleanupError(
                            "Tushare run lease cleanup failed"
                        ) from cleanup_error


@contextmanager
def external_table_page_transaction(
    engine: Any,
    spec: EndpointSpec,
    *,
    lock_timeout_seconds: int = 10,
):
    """Hold a MySQL named lock across one complete page transaction.

    The yielded transaction must contain the business rows, API audit, task
    counters, and checkpoint.  The lock is released only after commit or
    rollback, on the same physical connection.
    """
    if (
        isinstance(lock_timeout_seconds, bool)
        or not isinstance(lock_timeout_seconds, int)
        or not 0 <= lock_timeout_seconds <= 60
    ):
        raise ValueError("lock_timeout_seconds must be an integer between 0 and 60")
    lock_name = _lock_name(spec)
    with engine.connect() as connection:
        _require_mysql(connection)
        acquired = False
        page_committed = False
        transaction_failure: BaseException | None = None
        try:
            _acquire_named_lock(
                connection,
                lock_name=lock_name,
                timeout_seconds=lock_timeout_seconds,
            )
            acquired = True
            _finish_implicit_transaction(connection, commit=True)
            info = getattr(connection, "info", None)
            if not isinstance(info, dict):
                raise TushareStorageError(
                    "Database connection cannot track the Tushare lock"
                )
            if info.get(_LOCK_INFO_KEY) is not None:
                raise TushareStorageError(
                    "Database connection already owns a Tushare table lock"
                )
            info[_LOCK_INFO_KEY] = lock_name
            with connection.begin():
                yield connection
            page_committed = True
        except BaseException as error:
            transaction_failure = error
            raise
        finally:
            info = getattr(connection, "info", None)
            if isinstance(info, dict):
                info.pop(_LOCK_INFO_KEY, None)
            if acquired:
                try:
                    _finish_implicit_transaction(connection, commit=False)
                    _release_named_lock(connection, lock_name=lock_name)
                    _finish_implicit_transaction(connection, commit=True)
                except BaseException as cleanup_error:
                    _discard_connection(connection)
                    if page_committed and transaction_failure is None:
                        raise TusharePostCommitStorageError(
                            "Tushare page committed, but its external-table lock cleanup failed"
                        ) from cleanup_error


def verify_external_table(connection: Any, spec: EndpointSpec) -> ExternalTableContract:
    """Verify target, writable columns, and an exact unique business-key index."""
    _require_mysql(connection)
    if not spec.target_table.startswith("hq_") or not _IDENTIFIER.fullmatch(
        spec.target_table
    ):
        raise TushareStorageError(f"Invalid external table for {spec.key}")
    try:
        inspector = inspect(connection)
        if not inspector.has_table(spec.target_table, schema=A_SHARE_SCHEMA):
            raise TushareStorageError(
                f"Required external table {A_SHARE_SCHEMA}.{spec.target_table} does not exist"
            )
        raw_columns = inspector.get_columns(spec.target_table, schema=A_SHARE_SCHEMA)
        table_options = inspector.get_table_options(
            spec.target_table, schema=A_SHARE_SCHEMA
        )
        primary = (
            inspector.get_pk_constraint(spec.target_table, schema=A_SHARE_SCHEMA) or {}
        )
        indexes = list(inspector.get_indexes(spec.target_table, schema=A_SHARE_SCHEMA))
        for constraint in (
            inspector.get_unique_constraints(spec.target_table, schema=A_SHARE_SCHEMA)
            or []
        ):
            indexes.append({**constraint, "unique": True})
    except TushareStorageError:
        raise
    except Exception as error:
        raise TushareStorageError(
            f"Could not inspect external table {A_SHARE_SCHEMA}.{spec.target_table}"
        ) from error

    column_by_name = {
        column.get("name"): column
        for column in raw_columns
        if isinstance(column, dict) and isinstance(column.get("name"), str)
    }
    missing = sorted(set(spec.fields) - set(column_by_name))
    if missing:
        raise TushareStorageError(
            f"External table {spec.target_table} is missing columns: {', '.join(missing)}"
        )
    engine = str((table_options or {}).get("mysql_engine", "")).upper()
    if engine != "INNODB":
        raise TushareStorageError(
            f"External table {spec.target_table} must use InnoDB for atomic page writes"
        )
    _validate_column_types(spec, column_by_name, table_options or {})
    primary_columns = tuple(primary.get("constrained_columns") or ())
    if len(primary_columns) != 1 or primary_columns[0] in spec.fields:
        raise TushareStorageError(
            f"External table {spec.target_table} requires one separate identity primary key"
        )
    identity_column = primary_columns[0]
    if identity_column not in column_by_name:
        raise TushareStorageError(
            f"External table {spec.target_table} primary key metadata is inconsistent"
        )
    identity_metadata = column_by_name[identity_column]
    if identity_metadata.get("autoincrement") not in {True, "auto"}:
        raise TushareStorageError(
            f"External table {spec.target_table} identity key must auto-increment"
        )

    for name, metadata in column_by_name.items():
        if name in spec.fields or name == identity_column:
            continue
        has_default = metadata.get("default") is not None
        nullable = bool(metadata.get("nullable"))
        auto = metadata.get("autoincrement") in {True, "auto"}
        if not (has_default or nullable or auto):
            raise TushareStorageError(
                f"External table {spec.target_table} has required unmanaged column {name}"
            )

    supporting_index = _find_unique_business_index(spec.business_key, indexes)
    if supporting_index is None:
        raise TushareStorageError(
            f"External table {spec.target_table} lacks an exact unique business-key index"
        )
    return ExternalTableContract(
        schema=A_SHARE_SCHEMA,
        table=spec.target_table,
        columns=tuple(column_by_name),
        identity_column=identity_column,
        business_key=spec.business_key,
        supporting_index=supporting_index,
    )


def ensure_tushare_runtime_objects(
    connection: Any,
    specs: Sequence[EndpointSpec],
) -> tuple[ExternalTableContract, ...]:
    """Verify existing ``a_share`` tables; direct ingest never invents legacy DDL."""
    return tuple(verify_external_table(connection, spec) for spec in specs)


def write_business_rows(
    connection: Any,
    spec: EndpointSpec,
    rows: Sequence[Mapping[str, object]],
    *,
    contract: ExternalTableContract | None = None,
) -> TusharePageWriteResult:
    """Lock matching keys, update existing identities, and insert new rows atomically.

    The caller must own the transaction that also commits page audit and checkpoint
    state.  This helper never commits and never performs post-hoc duplicate cleanup.
    """
    _require_mysql(connection)
    _require_transaction(connection)
    _require_named_lock(connection, spec)
    verified = contract or verify_external_table(connection, spec)
    _validate_contract(verified, spec)
    normalized_rows = _validate_rows(spec, rows)
    if not normalized_rows:
        return TusharePageWriteResult(input_rows=0, inserted_rows=0, updated_rows=0)

    quoted_schema = _quote(verified.schema)
    quoted_table = _quote(verified.table)
    identity = _quote(verified.identity_column)
    key_columns = tuple(_quote(name) for name in spec.business_key)
    key_bindings: dict[str, object] = {}
    tuples: list[str] = []
    for row_number, row in enumerate(normalized_rows):
        bindings = []
        for key_number, name in enumerate(spec.business_key):
            binding = f"key_{row_number}_{key_number}"
            bindings.append(f":{binding}")
            key_bindings[binding] = row[name]
        tuples.append(f"({', '.join(bindings)})")
    select_sql = text(
        f"SELECT {identity}, {', '.join(key_columns)} "
        f"FROM {quoted_schema}.{quoted_table} "
        f"WHERE ({', '.join(key_columns)}) IN ({', '.join(tuples)}) FOR UPDATE"
    )

    try:
        selected = connection.execute(select_sql, key_bindings)
        existing_rows = _mapping_rows(selected)
        existing: dict[tuple[object, ...], object] = {}
        for selected_row in existing_rows:
            key = tuple(selected_row[name] for name in spec.business_key)
            if key in existing:
                raise TushareStorageError(
                    f"External table {spec.target_table} already contains duplicate business keys"
                )
            existing[key] = selected_row[verified.identity_column]

        update_values: list[dict[str, object]] = []
        insert_values: list[dict[str, object]] = []
        for row in normalized_rows:
            key = tuple(row[name] for name in spec.business_key)
            identity_value = existing.get(key)
            values = {f"value_{name}": row[name] for name in spec.fields}
            if identity_value is None:
                insert_values.append(values)
            else:
                update_values.append({**values, "identity_value": identity_value})

        if update_values:
            assignments = ", ".join(
                f"{_quote(name)} = :value_{name}" for name in spec.fields
            )
            update_sql = text(
                f"UPDATE {quoted_schema}.{quoted_table} SET {assignments} "
                f"WHERE {identity} = :identity_value"
            )
            connection.execute(update_sql, update_values)
        if insert_values:
            columns = ", ".join(_quote(name) for name in spec.fields)
            bindings = ", ".join(f":value_{name}" for name in spec.fields)
            insert_sql = text(
                f"INSERT INTO {quoted_schema}.{quoted_table} ({columns}) VALUES ({bindings})"
            )
            connection.execute(insert_sql, insert_values)
    except (TushareStorageError, TushareDataError):
        raise
    except Exception as error:
        raise TushareStorageError(
            f"Atomic Tushare page write failed for {spec.target_table}"
        ) from error

    return TusharePageWriteResult(
        input_rows=len(normalized_rows),
        inserted_rows=len(insert_values),
        updated_rows=len(update_values),
    )


def _find_unique_business_index(
    business_key: tuple[str, ...],
    indexes: Sequence[Mapping[str, object]],
) -> tuple[str, ...] | None:
    for index in indexes:
        raw_columns = (
            index.get("column_names") or index.get("constrained_columns") or ()
        )
        columns = tuple(name for name in raw_columns if isinstance(name, str))
        if columns == business_key and index.get("unique") is True:
            return columns
    return None


def _validate_column_types(
    spec: EndpointSpec,
    column_by_name: Mapping[str, Mapping[str, object]],
    table_options: Mapping[str, object],
) -> None:
    families = {
        "text": frozenset(
            {
                "char",
                "nchar",
                "nvarchar",
                "varchar",
                "string",
                "unicode",
                "unicode_text",
                "text",
                "unicodetext",
                "tinytext",
                "mediumtext",
                "longtext",
            }
        ),
        "date": frozenset({"date"}),
        "decimal": frozenset({"decimal", "numeric"}),
        "integer": frozenset(
            {"tinyint", "smallint", "mediumint", "int", "integer", "bigint"}
        ),
    }
    for name in spec.fields:
        expected = spec.column_types[name]
        sql_type = column_by_name[name].get("type")
        type_name = str(
            getattr(sql_type, "__visit_name__", None) or type(sql_type).__name__
        ).casefold()
        if type_name not in families[expected]:
            raise TushareStorageError(
                f"External table {spec.target_table} column {name} has an incompatible SQL type"
            )
        if column_by_name[name].get("computed"):
            raise TushareStorageError(
                f"External table {spec.target_table} column {name} must be directly writable"
            )
        if expected == "text":
            charset = getattr(sql_type, "charset", None) or table_options.get(
                "mysql_default charset"
            )
            if not isinstance(charset, str) or charset.casefold() not in {
                "utf8",
                "utf8mb3",
                "utf8mb4",
            }:
                raise TushareStorageError(
                    f"External table {spec.target_table} column {name} must use a Unicode charset"
                )
            length = getattr(sql_type, "length", None)
            bounded_text = type_name in {
                "char",
                "nchar",
                "nvarchar",
                "string",
                "unicode",
                "varchar",
            }
            if bounded_text:
                capacity = length
            else:
                max_bytes = {
                    "tinytext": 255,
                    "text": 65_535,
                    "unicode_text": 65_535,
                    "unicodetext": 65_535,
                    "mediumtext": 16_777_215,
                    "longtext": 4_294_967_295,
                }.get(type_name)
                bytes_per_character = 4 if charset.casefold() == "utf8mb4" else 3
                capacity = (
                    max_bytes // bytes_per_character if max_bytes is not None else None
                )
            if (
                isinstance(capacity, bool)
                or not isinstance(capacity, int)
                or capacity < spec.text_min_lengths[name]
            ):
                raise TushareStorageError(
                    f"External table {spec.target_table} column {name} is too short"
                )
        if expected == "decimal":
            precision = getattr(sql_type, "precision", None)
            scale = getattr(sql_type, "scale", None)
            if (
                isinstance(precision, bool)
                or not isinstance(precision, int)
                or isinstance(scale, bool)
                or not isinstance(scale, int)
                or scale < 4
                or precision - scale < 21
            ):
                raise TushareStorageError(
                    f"External table {spec.target_table} column {name} "
                    "must support DECIMAL(25,4) values"
                )


def _validate_contract(contract: ExternalTableContract, spec: EndpointSpec) -> None:
    if (
        contract.schema != A_SHARE_SCHEMA
        or contract.table != spec.target_table
        or contract.business_key != spec.business_key
        or not set(spec.fields).issubset(contract.columns)
        or not contract.identity_column
    ):
        raise TushareStorageError(
            "External table contract does not match endpoint spec"
        )


def _validate_rows(
    spec: EndpointSpec,
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    expected = set(spec.fields)
    result: list[dict[str, object]] = []
    seen: dict[tuple[object, ...], dict[str, object]] = {}
    for row_number, raw_row in enumerate(rows):
        if set(raw_row) != expected:
            raise TushareDataError(
                f"Tushare storage row {row_number} does not match {spec.key} fields"
            )
        row = {name: raw_row[name] for name in spec.fields}
        key = tuple(row[name] for name in spec.business_key)
        if any(value is None or value == "" for value in key):
            raise TushareDataError(
                f"Tushare storage row {row_number} has an empty business key"
            )
        previous = seen.get(key)
        if previous is not None:
            if previous != row:
                raise TushareDataError(
                    f"Conflicting Tushare storage rows share a business key in {spec.key}"
                )
            continue
        seen[key] = row
        result.append(row)
    return tuple(result)


def _mapping_rows(result: Any) -> list[Mapping[str, object]]:
    mappings = getattr(result, "mappings", None)
    if callable(mappings):
        mapped = mappings()
        all_rows = getattr(mapped, "all", None)
        return list(all_rows() if callable(all_rows) else mapped)
    return list(result)


def _require_mysql(connection: Any) -> None:
    dialect = getattr(getattr(connection, "dialect", None), "name", None)
    if dialect not in {"mysql", "mariadb"}:
        raise TushareStorageError("Tushare external-table writes require MySQL")


def _require_transaction(connection: Any) -> None:
    checker = getattr(connection, "in_transaction", None)
    if callable(checker) and not checker():
        raise TushareStorageError("Tushare page writes require an active transaction")


def _require_named_lock(connection: Any, spec: EndpointSpec) -> None:
    lock_name = _lock_name(spec)
    info = getattr(connection, "info", None)
    if not isinstance(info, dict) or info.get(_LOCK_INFO_KEY) != lock_name:
        raise TushareStorageError(
            "Tushare page writes require external_table_page_transaction"
        )
    try:
        held = _scalar_result(
            connection.execute(
                text(
                    "SELECT IS_USED_LOCK(:lock_name) = CONNECTION_ID() AS lock_status"
                ),
                {"lock_name": lock_name},
            )
        )
    except Exception as error:
        raise TushareStorageError(
            "Could not verify the Tushare external-table lock"
        ) from error
    if held not in {1, True}:
        raise TushareStorageError(
            "Tushare external-table lock is not held by this connection"
        )


def _acquire_named_lock(
    connection: Any, *, lock_name: str, timeout_seconds: int
) -> None:
    try:
        acquired = _scalar_result(
            connection.execute(
                text("SELECT GET_LOCK(:lock_name, :lock_timeout) AS lock_status"),
                {"lock_name": lock_name, "lock_timeout": timeout_seconds},
            )
        )
    except Exception as error:
        raise TushareStorageError(
            "Could not acquire the Tushare external-table lock"
        ) from error
    if acquired not in {1, True}:
        raise TushareStorageError("Timed out acquiring the Tushare external-table lock")


def _release_named_lock(connection: Any, *, lock_name: str) -> None:
    try:
        released = _scalar_result(
            connection.execute(
                text("SELECT RELEASE_LOCK(:lock_name) AS lock_status"),
                {"lock_name": lock_name},
            )
        )
    except Exception as error:
        raise TushareStorageError(
            "Could not release the Tushare external-table lock"
        ) from error
    if released not in {1, True}:
        raise TushareStorageError(
            "Tushare external-table lock release was not confirmed"
        )


def _finish_implicit_transaction(connection: Any, *, commit: bool) -> None:
    checker = getattr(connection, "in_transaction", None)
    active = callable(checker) and checker()
    if not active:
        return
    action = getattr(connection, "commit" if commit else "rollback", None)
    if not callable(action):
        raise TushareStorageError(
            "Database connection cannot finish its lock statement"
        )
    action()


def _discard_connection(connection: Any) -> None:
    """Force a failed named-lock connection out of the pool without masking errors."""
    for action_name in ("invalidate", "close"):
        action = getattr(connection, action_name, None)
        if callable(action):
            try:
                action()
            except Exception:
                pass


def _scalar_result(result: Any) -> object:
    scalar_one = getattr(result, "scalar_one", None)
    if callable(scalar_one):
        return scalar_one()
    scalar = getattr(result, "scalar", None)
    if callable(scalar):
        return scalar()
    rows = list(result)
    if len(rows) != 1:
        raise TushareStorageError("Named-lock query returned an invalid result")
    row = rows[0]
    if isinstance(row, Mapping):
        return next(iter(row.values()))
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
        return row[0]
    return row


def _lock_name(spec: EndpointSpec) -> str:
    if not _IDENTIFIER.fullmatch(spec.target_table):
        raise TushareStorageError("Unsafe table name in Tushare lock")
    name = f"j21-cn:tushare:{A_SHARE_SCHEMA}:{spec.target_table}"
    if len(name.encode("utf-8")) > 64:
        raise TushareStorageError("Tushare named lock exceeds MySQL's 64-byte limit")
    return name


def _run_lock_name(run_id: int) -> str:
    name = f"{_RUN_LOCK_PREFIX}{run_id}"
    if len(name.encode("utf-8")) > 64:
        raise TushareStorageError("Tushare run lock exceeds MySQL's 64-byte limit")
    return name


def _quote(identifier: str) -> str:
    if not _IDENTIFIER.fullmatch(identifier):
        raise TushareStorageError("Unsafe SQL identifier in Tushare catalog")
    return f"`{identifier}`"
