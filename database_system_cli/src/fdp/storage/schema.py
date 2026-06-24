from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from fdp.storage.tables import SYSTEM_SCHEMA, US_SHARE_SCHEMA


REQUIRED_RUNTIME_SCHEMAS = (US_SHARE_SCHEMA, SYSTEM_SCHEMA)


def missing_runtime_schemas(connection: Connection) -> list[str]:
    inspector = inspect(connection)
    existing_schemas = set(inspector.get_schema_names())
    return [schema for schema in REQUIRED_RUNTIME_SCHEMAS if schema not in existing_schemas]


def ensure_runtime_schemas(connection: Connection) -> None:
    missing_schemas = missing_runtime_schemas(connection)
    if missing_schemas:
        joined = ", ".join(missing_schemas)
        raise RuntimeError(
            f"missing required database schema(s): {joined}. "
            "Run `poetry run alembic upgrade head` before ingestion."
        )

