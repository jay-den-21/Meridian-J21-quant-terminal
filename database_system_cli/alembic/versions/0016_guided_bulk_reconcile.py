"""add resumable Bulk reconcile workflow state and identity audit

Revision ID: 0016_guided_bulk_reconcile
Revises: 0015_id_mapping_ingest
Create Date: 2026-07-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0016_guided_bulk_reconcile"
down_revision: str | None = "0015_id_mapping_ingest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SYSTEM_SCHEMA = "system"
RUN_TABLE = "ingestion_task_run"
UNMATCHED_TABLE = "bulk_unmatched_daily_price_observation"
AUDIT_TABLE = "instrument_identity_resolution_audit"
CLASSIFY_INDEX = "ix_bulk_unmatched_market_status_date_id"
CLASSIFY_INDEX_COLUMNS = [
    "market",
    "classification_status",
    "trade_date",
    "observation_id",
]


def _has_table(bind: sa.Connection, table: str, schema: str = SYSTEM_SCHEMA) -> bool:
    return sa.inspect(bind).has_table(table, schema=schema)


def _column_names(
    bind: sa.Connection,
    table: str,
    schema: str = SYSTEM_SCHEMA,
) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns(table, schema=schema)
    }


def _indexes(
    bind: sa.Connection,
    table: str,
    schema: str = SYSTEM_SCHEMA,
) -> dict[str, list[str]]:
    return {
        index["name"]: list(index["column_names"])
        for index in sa.inspect(bind).get_indexes(table, schema=schema)
    }


def upgrade() -> None:
    bind = op.get_bind()

    if "checkpoint_json" not in _column_names(bind, RUN_TABLE):
        op.add_column(
            RUN_TABLE,
            sa.Column("checkpoint_json", sa.JSON(), nullable=True),
            schema=SYSTEM_SCHEMA,
        )

    if "last_classified_run_id" not in _column_names(bind, UNMATCHED_TABLE):
        op.add_column(
            UNMATCHED_TABLE,
            sa.Column("last_classified_run_id", sa.BigInteger(), nullable=True),
            schema=SYSTEM_SCHEMA,
        )

    if not _has_table(bind, AUDIT_TABLE):
        op.create_table(
            AUDIT_TABLE,
            sa.Column("audit_id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("instrument_id", sa.BigInteger(), nullable=False),
            sa.Column("provider_symbol", sa.String(length=128), nullable=False),
            sa.Column("market", sa.String(length=16), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("match_method", sa.String(length=64), nullable=False),
            sa.Column("confidence", sa.String(length=16), nullable=False),
            sa.Column("evidence_type", sa.String(length=64), nullable=False),
            sa.Column("resolver_version", sa.String(length=32), nullable=False),
            sa.Column("observed_from", sa.Date(), nullable=False),
            sa.Column("observed_to", sa.Date(), nullable=False),
            sa.Column("first_run_id", sa.BigInteger(), nullable=True),
            sa.Column("last_run_id", sa.BigInteger(), nullable=True),
            sa.Column("reason", sa.String(length=512), nullable=True),
            sa.Column("supersedes_audit_id", sa.BigInteger(), nullable=True),
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
                ["instrument_id"],
                ["us_share.instrument.instrument_id"],
            ),
            sa.ForeignKeyConstraint(
                ["first_run_id"],
                ["system.ingestion_task_run.run_id"],
            ),
            sa.ForeignKeyConstraint(
                ["last_run_id"],
                ["system.ingestion_task_run.run_id"],
            ),
            sa.ForeignKeyConstraint(
                ["supersedes_audit_id"],
                ["system.instrument_identity_resolution_audit.audit_id"],
            ),
            sa.PrimaryKeyConstraint("audit_id"),
            sa.UniqueConstraint(
                "instrument_id",
                "provider_symbol",
                "market",
                "source",
                "match_method",
                "confidence",
                "evidence_type",
                "resolver_version",
                name="uq_identity_resolution_decision",
            ),
            schema=SYSTEM_SCHEMA,
        )
    else:
        expected_columns = {
            "audit_id",
            "instrument_id",
            "provider_symbol",
            "market",
            "source",
            "match_method",
            "confidence",
            "evidence_type",
            "resolver_version",
            "observed_from",
            "observed_to",
            "first_run_id",
            "last_run_id",
            "reason",
            "supersedes_audit_id",
            "created_at",
            "updated_at",
        }
        missing = expected_columns - _column_names(bind, AUDIT_TABLE)
        if missing:
            raise RuntimeError(
                "refusing to reuse incomplete identity resolution audit table: "
                f"missing {sorted(missing)}"
            )

    audit_indexes = _indexes(bind, AUDIT_TABLE)
    if "ix_identity_resolution_instrument_symbol" not in audit_indexes:
        op.create_index(
            "ix_identity_resolution_instrument_symbol",
            AUDIT_TABLE,
            ["instrument_id", "provider_symbol"],
            schema=SYSTEM_SCHEMA,
        )
    audit_indexes = _indexes(bind, AUDIT_TABLE)
    if "ix_identity_resolution_last_run" not in audit_indexes:
        op.create_index(
            "ix_identity_resolution_last_run",
            AUDIT_TABLE,
            ["last_run_id"],
            schema=SYSTEM_SCHEMA,
        )

    unmatched_indexes = _indexes(bind, UNMATCHED_TABLE)
    existing_classify_columns = unmatched_indexes.get(CLASSIFY_INDEX)
    if (
        existing_classify_columns is not None
        and existing_classify_columns != CLASSIFY_INDEX_COLUMNS
    ):
        raise RuntimeError(
            f"refusing incompatible {CLASSIFY_INDEX}: "
            f"expected={CLASSIFY_INDEX_COLUMNS} actual={existing_classify_columns}"
        )
    if existing_classify_columns is None:
        bind.execute(
            sa.text(
                "ALTER TABLE `system`.bulk_unmatched_daily_price_observation "
                "ADD INDEX ix_bulk_unmatched_market_status_date_id "
                "(market, classification_status, trade_date, observation_id), "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )
        )
    actual_classify_columns = _indexes(bind, UNMATCHED_TABLE).get(CLASSIFY_INDEX)
    if actual_classify_columns != CLASSIFY_INDEX_COLUMNS:
        raise RuntimeError(
            f"online index creation did not create exact {CLASSIFY_INDEX}: "
            f"expected={CLASSIFY_INDEX_COLUMNS} actual={actual_classify_columns}"
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_table(bind, AUDIT_TABLE):
        audit_rows = int(
            bind.execute(
                sa.text("SELECT COUNT(*) FROM `system`.instrument_identity_resolution_audit")
            ).scalar_one()
        )
        if audit_rows:
            raise RuntimeError(
                "refusing downgrade while identity resolution audit evidence exists"
            )

    if "checkpoint_json" in _column_names(bind, RUN_TABLE):
        checkpoint_rows = int(
            bind.execute(
                sa.text(
                    "SELECT COUNT(*) FROM `system`.ingestion_task_run "
                    "WHERE checkpoint_json IS NOT NULL"
                )
            ).scalar_one()
        )
        if checkpoint_rows:
            raise RuntimeError("refusing downgrade while reconcile checkpoints exist")

    if "last_classified_run_id" in _column_names(bind, UNMATCHED_TABLE):
        classified_rows = int(
            bind.execute(
                sa.text(
                    "SELECT COUNT(*) FROM `system`.bulk_unmatched_daily_price_observation "
                    "WHERE last_classified_run_id IS NOT NULL"
                )
            ).scalar_one()
        )
        if classified_rows:
            raise RuntimeError("refusing downgrade while classify run markers exist")

    if CLASSIFY_INDEX in _indexes(bind, UNMATCHED_TABLE):
        bind.execute(
            sa.text(
                "ALTER TABLE `system`.bulk_unmatched_daily_price_observation "
                "DROP INDEX ix_bulk_unmatched_market_status_date_id, "
                "ALGORITHM=INPLACE, LOCK=NONE"
            )
        )
    if _has_table(bind, AUDIT_TABLE):
        op.drop_table(AUDIT_TABLE, schema=SYSTEM_SCHEMA)
    if "last_classified_run_id" in _column_names(bind, UNMATCHED_TABLE):
        op.drop_column(
            UNMATCHED_TABLE,
            "last_classified_run_id",
            schema=SYSTEM_SCHEMA,
        )
    if "checkpoint_json" in _column_names(bind, RUN_TABLE):
        op.drop_column(RUN_TABLE, "checkpoint_json", schema=SYSTEM_SCHEMA)
