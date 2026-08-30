"""Small CN-owned control-schema bootstrap used by ingest init."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from fdp_cn.tushare.errors import TushareStorageError
from fdp_cn.tushare.system_tables import metadata


SYSTEM_SCHEMA = "system_cn"
CONTROL_TABLES = frozenset(
    {"ingestion_task_run", "api_call_log", "index_weight_stage"}
)


def ensure_control_schema(engine: Engine) -> None:
    """Create only the CN audit/checkpoint schema and verify InnoDB tables."""
    if getattr(engine.dialect, "name", None) not in {"mysql", "mariadb"}:
        raise TushareStorageError("CN control tables require MySQL or MariaDB")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS system_cn"))
        metadata.create_all(engine, checkfirst=True)
        inspector = inspect(engine)
        missing = sorted(
            table
            for table in CONTROL_TABLES
            if not inspector.has_table(table, schema=SYSTEM_SCHEMA)
        )
        if missing:
            raise TushareStorageError(
                "CN control table creation is incomplete: " + ", ".join(missing)
            )
        for table in CONTROL_TABLES:
            options = inspector.get_table_options(table, schema=SYSTEM_SCHEMA)
            if str(options.get("mysql_engine", "")).upper() != "INNODB":
                raise TushareStorageError(f"system_cn.{table} must use InnoDB")
    except TushareStorageError:
        raise
    except Exception as error:
        raise TushareStorageError(
            "Could not initialize the CN control schema"
        ) from error
