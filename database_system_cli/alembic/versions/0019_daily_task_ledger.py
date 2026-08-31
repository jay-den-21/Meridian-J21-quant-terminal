"""add durable task and work-unit ledger for resumable Daily Bulk jobs

Revision ID: 0019_daily_task_ledger
Revises: 0018_protect_external_a_share
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0019_daily_task_ledger"
down_revision: str | None = "0018_protect_external_a_share"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "system"
RUN_TABLE = "ingestion_task_run"
UNIT_TABLE = "ingestion_task_work_unit"
API_TABLE = "api_call_log"


def _inspector(bind: sa.Connection) -> sa.Inspector:
    return sa.inspect(bind)


def _has_table(bind: sa.Connection, table: str) -> bool:
    return _inspector(bind).has_table(table, schema=SCHEMA)


def _columns(bind: sa.Connection, table: str) -> set[str]:
    return {
        column["name"]
        for column in _inspector(bind).get_columns(table, schema=SCHEMA)
    }


def _indexes(bind: sa.Connection, table: str) -> dict[str, list[str]]:
    return {
        index["name"]: list(index["column_names"])
        for index in _inspector(bind).get_indexes(table, schema=SCHEMA)
    }


def _unique_constraints(bind: sa.Connection, table: str) -> dict[str, list[str]]:
    return {
        constraint["name"]: list(constraint["column_names"])
        for constraint in _inspector(bind).get_unique_constraints(table, schema=SCHEMA)
    }


def _foreign_keys(bind: sa.Connection, table: str) -> set[str]:
    return {
        str(constraint["name"])
        for constraint in _inspector(bind).get_foreign_keys(table, schema=SCHEMA)
        if constraint.get("name")
    }


def _add_run_columns(bind: sa.Connection) -> None:
    existing = _columns(bind, RUN_TABLE)
    additions = {
        "task_fingerprint": sa.Column("task_fingerprint", sa.String(length=64)),
        "active_resume_key": sa.Column("active_resume_key", sa.String(length=64)),
        "workflow_version": sa.Column("workflow_version", sa.Integer()),
        "supersedes_run_id": sa.Column("supersedes_run_id", sa.BigInteger()),
        "lease_owner": sa.Column("lease_owner", sa.String(length=128)),
        "lease_expires_at": sa.Column("lease_expires_at", sa.DateTime()),
        "heartbeat_at": sa.Column("heartbeat_at", sa.DateTime()),
    }
    for name, column in additions.items():
        if name not in existing:
            op.add_column(RUN_TABLE, column, schema=SCHEMA)

    foreign_keys = _foreign_keys(bind, RUN_TABLE)
    if "fk_ingestion_task_supersedes" not in foreign_keys:
        op.create_foreign_key(
            "fk_ingestion_task_supersedes",
            RUN_TABLE,
            RUN_TABLE,
            ["supersedes_run_id"],
            ["run_id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
        )

    uniques = _unique_constraints(bind, RUN_TABLE)
    actual_unique = uniques.get("uq_ingestion_task_active_resume_key")
    if actual_unique is not None and actual_unique != ["active_resume_key"]:
        raise RuntimeError(
            "refusing incompatible uq_ingestion_task_active_resume_key: "
            f"actual={actual_unique}"
        )
    if actual_unique is None:
        op.create_unique_constraint(
            "uq_ingestion_task_active_resume_key",
            RUN_TABLE,
            ["active_resume_key"],
            schema=SCHEMA,
        )

    expected_indexes = {
        "ix_ingestion_task_fingerprint_status": ["task_fingerprint", "status"],
        "ix_ingestion_task_lease_expires": ["lease_expires_at"],
    }
    indexes = _indexes(bind, RUN_TABLE)
    for name, columns in expected_indexes.items():
        actual = indexes.get(name)
        if actual is not None and actual != columns:
            raise RuntimeError(f"refusing incompatible {name}: actual={actual}")
        if actual is None:
            op.create_index(name, RUN_TABLE, columns, schema=SCHEMA)


def _create_work_unit_table() -> None:
    op.create_table(
        UNIT_TABLE,
        sa.Column("work_unit_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("unit_type", sa.String(length=32), nullable=False),
        sa.Column("unit_key", sa.String(length=128), nullable=False),
        sa.Column("unit_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("series_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reused_from_work_unit_id", sa.BigInteger()),
        sa.Column("evidence_run_id", sa.BigInteger()),
        sa.Column("rows_fetched", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("rows_published", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("rows_pending", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("rows_rejected", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("api_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("api_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("response_hash", sa.String(length=64)),
        sa.Column("quality_status", sa.String(length=32)),
        sa.Column("metrics_json", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["system.ingestion_task_run.run_id"],
            name="fk_ingestion_work_unit_run",
        ),
        sa.ForeignKeyConstraint(
            ["reused_from_work_unit_id"],
            ["system.ingestion_task_work_unit.work_unit_id"],
            name="fk_ingestion_work_unit_reused_from",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_run_id"],
            ["system.ingestion_task_run.run_id"],
            name="fk_ingestion_work_unit_evidence_run",
        ),
        sa.PrimaryKeyConstraint("work_unit_id"),
        sa.UniqueConstraint(
            "run_id",
            "unit_key",
            name="uq_ingestion_work_unit_run_key",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ingestion_work_unit_fingerprint_status",
        UNIT_TABLE,
        ["unit_fingerprint", "status"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ingestion_work_unit_series_status_key",
        UNIT_TABLE,
        ["series_fingerprint", "status", "unit_key"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ingestion_work_unit_run_status",
        UNIT_TABLE,
        ["run_id", "status"],
        schema=SCHEMA,
    )


def _validate_work_unit_table(bind: sa.Connection) -> None:
    expected = {
        "work_unit_id",
        "run_id",
        "unit_type",
        "unit_key",
        "unit_fingerprint",
        "series_fingerprint",
        "status",
        "attempt_count",
        "reused_from_work_unit_id",
        "evidence_run_id",
        "rows_fetched",
        "rows_published",
        "rows_pending",
        "rows_rejected",
        "api_calls",
        "api_units",
        "response_hash",
        "quality_status",
        "metrics_json",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    }
    missing = expected - _columns(bind, UNIT_TABLE)
    if missing:
        raise RuntimeError(
            "refusing to adopt incomplete ingestion_task_work_unit table: "
            f"missing={sorted(missing)}"
        )
    expected_indexes = {
        "ix_ingestion_work_unit_fingerprint_status": ["unit_fingerprint", "status"],
        "ix_ingestion_work_unit_series_status_key": [
            "series_fingerprint",
            "status",
            "unit_key",
        ],
        "ix_ingestion_work_unit_run_status": ["run_id", "status"],
    }
    indexes = _indexes(bind, UNIT_TABLE)
    for name, columns in expected_indexes.items():
        actual = indexes.get(name)
        if actual is not None and actual != columns:
            raise RuntimeError(f"refusing incompatible {name}: actual={actual}")
        if actual is None:
            op.create_index(name, UNIT_TABLE, columns, schema=SCHEMA)


def _add_api_work_unit_link(bind: sa.Connection) -> None:
    if "work_unit_id" not in _columns(bind, API_TABLE):
        op.add_column(
            API_TABLE,
            sa.Column("work_unit_id", sa.BigInteger()),
            schema=SCHEMA,
        )
    if "fk_api_call_work_unit" not in _foreign_keys(bind, API_TABLE):
        op.create_foreign_key(
            "fk_api_call_work_unit",
            API_TABLE,
            UNIT_TABLE,
            ["work_unit_id"],
            ["work_unit_id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
        )
    indexes = _indexes(bind, API_TABLE)
    actual = indexes.get("ix_api_call_log_work_unit_id")
    if actual is not None and actual != ["work_unit_id"]:
        raise RuntimeError(
            "refusing incompatible ix_api_call_log_work_unit_id: "
            f"actual={actual}"
        )
    if actual is None:
        op.create_index(
            "ix_api_call_log_work_unit_id",
            API_TABLE,
            ["work_unit_id"],
            schema=SCHEMA,
        )


def upgrade() -> None:
    bind = op.get_bind()
    _add_run_columns(bind)
    if not _has_table(bind, UNIT_TABLE):
        _create_work_unit_table()
    else:
        _validate_work_unit_table(bind)
    _add_api_work_unit_link(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, UNIT_TABLE):
        rows = int(
            bind.execute(
                sa.text("SELECT COUNT(*) FROM `system`.ingestion_task_work_unit")
            ).scalar_one()
        )
        if rows:
            raise RuntimeError("refusing downgrade while durable work-unit evidence exists")

    adopted_runs = int(
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM `system`.ingestion_task_run "
                "WHERE task_fingerprint IS NOT NULL OR active_resume_key IS NOT NULL"
            )
        ).scalar_one()
    )
    if adopted_runs:
        raise RuntimeError("refusing downgrade while resumable task evidence exists")

    if "work_unit_id" in _columns(bind, API_TABLE):
        if "ix_api_call_log_work_unit_id" in _indexes(bind, API_TABLE):
            op.drop_index("ix_api_call_log_work_unit_id", table_name=API_TABLE, schema=SCHEMA)
        if "fk_api_call_work_unit" in _foreign_keys(bind, API_TABLE):
            op.drop_constraint(
                "fk_api_call_work_unit",
                API_TABLE,
                type_="foreignkey",
                schema=SCHEMA,
            )
        op.drop_column(API_TABLE, "work_unit_id", schema=SCHEMA)

    if _has_table(bind, UNIT_TABLE):
        op.drop_table(UNIT_TABLE, schema=SCHEMA)

    indexes = _indexes(bind, RUN_TABLE)
    for name in (
        "ix_ingestion_task_fingerprint_status",
        "ix_ingestion_task_lease_expires",
    ):
        if name in indexes:
            op.drop_index(name, table_name=RUN_TABLE, schema=SCHEMA)
    if "uq_ingestion_task_active_resume_key" in _unique_constraints(bind, RUN_TABLE):
        op.drop_constraint(
            "uq_ingestion_task_active_resume_key",
            RUN_TABLE,
            type_="unique",
            schema=SCHEMA,
        )
    if "fk_ingestion_task_supersedes" in _foreign_keys(bind, RUN_TABLE):
        op.drop_constraint(
            "fk_ingestion_task_supersedes",
            RUN_TABLE,
            type_="foreignkey",
            schema=SCHEMA,
        )
    for name in (
        "heartbeat_at",
        "lease_expires_at",
        "lease_owner",
        "supersedes_run_id",
        "workflow_version",
        "active_resume_key",
        "task_fingerprint",
    ):
        if name in _columns(bind, RUN_TABLE):
            op.drop_column(RUN_TABLE, name, schema=SCHEMA)
