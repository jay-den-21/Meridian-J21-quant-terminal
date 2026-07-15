"""add ID mapping ingest storage and NULL-safe identifier uniqueness

Revision ID: 0015_id_mapping_ingest
Revises: 0014_fund_compact_swap
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0015_id_mapping_ingest"
down_revision: str | None = "0014_fund_compact_swap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


IDENTIFIER_TABLE = "instrument_identifier_history"
IDENTIFIER_SCHEMA = "us_share"
UNMATCHED_TABLE = "identifier_mapping_unmatched_observation"
UNMATCHED_SCHEMA = "system"
IDENTIFIER_UNIQUE = "uq_identifier_history_identity"
IDENTIFIER_FK_INDEX = "ix_identifier_history_instrument"


def _column_names(bind: sa.Connection, table: str, schema: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns(table, schema=schema)
    }


def _indexes(bind: sa.Connection, table: str, schema: str) -> dict[str, list[str]]:
    return {
        index["name"]: list(index["column_names"])
        for index in sa.inspect(bind).get_indexes(table, schema=schema)
    }


def _has_table(bind: sa.Connection, table: str, schema: str) -> bool:
    return sa.inspect(bind).has_table(table, schema=schema)


def upgrade() -> None:
    bind = op.get_bind()
    conflicting_groups = int(
        bind.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT 1
                    FROM us_share.instrument_identifier_history
                    GROUP BY instrument_id, id_type, id_value, valid_from, source
                    HAVING COUNT(DISTINCT COALESCE(DATE_FORMAT(valid_to, '%Y-%m-%d'), 'NULL')) > 1
                ) AS conflicting_identifier_groups
                """
            )
        ).scalar_one()
    )
    if conflicting_groups:
        raise RuntimeError(
            "refusing identifier-history uniqueness migration: "
            f"{conflicting_groups} duplicate key group(s) have conflicting valid_to values"
        )

    bind.execute(
        sa.text(
            """
            DELETE newer
            FROM us_share.instrument_identifier_history AS newer
            INNER JOIN us_share.instrument_identifier_history AS older
                ON newer.instrument_id = older.instrument_id
               AND newer.id_type = older.id_type
               AND newer.id_value = older.id_value
               AND newer.valid_from <=> older.valid_from
               AND newer.valid_to <=> older.valid_to
               AND newer.source = older.source
               AND newer.identifier_history_id > older.identifier_history_id
            """
        )
    )
    if "valid_from_key" not in _column_names(
        bind,
        IDENTIFIER_TABLE,
        IDENTIFIER_SCHEMA,
    ):
        op.add_column(
            IDENTIFIER_TABLE,
            sa.Column(
                "valid_from_key",
                sa.Date(),
                sa.Computed("coalesce(valid_from, '1000-01-01')", persisted=True),
                nullable=True,
            ),
            schema=IDENTIFIER_SCHEMA,
        )

    indexes = _indexes(bind, IDENTIFIER_TABLE, IDENTIFIER_SCHEMA)
    if IDENTIFIER_FK_INDEX not in indexes:
        # The original composite unique index was also MySQL's implicit support
        # index for the instrument_id foreign key. Give the FK its own index
        # before replacing that unique index so the DDL is safe and resumable.
        op.create_index(
            IDENTIFIER_FK_INDEX,
            IDENTIFIER_TABLE,
            ["instrument_id"],
            schema=IDENTIFIER_SCHEMA,
        )

    indexes = _indexes(bind, IDENTIFIER_TABLE, IDENTIFIER_SCHEMA)
    target_unique_columns = [
        "instrument_id",
        "id_type",
        "id_value",
        "valid_from_key",
        "source",
    ]
    current_unique_columns = indexes.get(IDENTIFIER_UNIQUE)
    if current_unique_columns is not None and current_unique_columns != target_unique_columns:
        op.drop_constraint(
            IDENTIFIER_UNIQUE,
            IDENTIFIER_TABLE,
            schema=IDENTIFIER_SCHEMA,
            type_="unique",
        )
        current_unique_columns = None
    if current_unique_columns is None:
        op.create_unique_constraint(
            IDENTIFIER_UNIQUE,
            IDENTIFIER_TABLE,
            target_unique_columns,
            schema=IDENTIFIER_SCHEMA,
        )

    if not _has_table(bind, UNMATCHED_TABLE, UNMATCHED_SCHEMA):
        op.create_table(
            UNMATCHED_TABLE,
            sa.Column(
                "observation_id",
                sa.BigInteger(),
                autoincrement=True,
                nullable=False,
            ),
            sa.Column("last_run_id", sa.BigInteger(), nullable=False),
            sa.Column("market", sa.String(length=16), nullable=False),
            sa.Column("provider_symbol", sa.String(length=128), nullable=True),
            sa.Column("isin", sa.String(length=128), nullable=True),
            sa.Column("figi", sa.String(length=128), nullable=True),
            sa.Column("lei", sa.String(length=128), nullable=True),
            sa.Column("cusip", sa.String(length=128), nullable=True),
            sa.Column("cik", sa.String(length=128), nullable=True),
            sa.Column("raw_payload", sa.Text(), nullable=False),
            sa.Column("mapping_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("reason", sa.String(length=255), nullable=False),
            sa.Column("candidate_instrument_ids", sa.Text(), nullable=True),
            sa.Column("resolution_status", sa.String(length=32), nullable=False),
            sa.Column("resolved_instrument_id", sa.BigInteger(), nullable=True),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column(
                "first_seen_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "last_seen_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
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
                ["last_run_id"],
                ["system.ingestion_task_run.run_id"],
            ),
            sa.ForeignKeyConstraint(
                ["resolved_instrument_id"],
                ["us_share.instrument.instrument_id"],
            ),
            sa.PrimaryKeyConstraint("observation_id"),
            sa.UniqueConstraint(
                "source",
                "mapping_fingerprint",
                name="uq_identifier_mapping_unmatched_source_fingerprint",
            ),
            schema=UNMATCHED_SCHEMA,
        )
    else:
        expected_columns = {
            "observation_id",
            "last_run_id",
            "market",
            "provider_symbol",
            "isin",
            "figi",
            "lei",
            "cusip",
            "cik",
            "raw_payload",
            "mapping_fingerprint",
            "reason",
            "candidate_instrument_ids",
            "resolution_status",
            "resolved_instrument_id",
            "source",
            "first_seen_at",
            "last_seen_at",
            "resolved_at",
            "created_at",
            "updated_at",
        }
        missing_columns = expected_columns - _column_names(
            bind,
            UNMATCHED_TABLE,
            UNMATCHED_SCHEMA,
        )
        if missing_columns:
            raise RuntimeError(
                "refusing to reuse incomplete identifier mapping unmatched table: "
                f"missing {sorted(missing_columns)}"
            )

    unmatched_indexes = _indexes(bind, UNMATCHED_TABLE, UNMATCHED_SCHEMA)
    if "ix_identifier_mapping_unmatched_status" not in unmatched_indexes:
        op.create_index(
            "ix_identifier_mapping_unmatched_status",
            UNMATCHED_TABLE,
            ["resolution_status", "reason"],
            schema=UNMATCHED_SCHEMA,
        )
    if "ix_identifier_mapping_unmatched_symbol" not in unmatched_indexes:
        op.create_index(
            "ix_identifier_mapping_unmatched_symbol",
            UNMATCHED_TABLE,
            ["provider_symbol"],
            schema=UNMATCHED_SCHEMA,
        )


def downgrade() -> None:
    unmatched_rows = int(
        op.get_bind()
        .execute(
            sa.text("SELECT COUNT(*) FROM `system`.identifier_mapping_unmatched_observation")
        )
        .scalar_one()
    )
    if unmatched_rows:
        raise RuntimeError(
            "refusing downgrade while identifier mapping unmatched evidence exists"
        )

    op.drop_index(
        "ix_identifier_mapping_unmatched_symbol",
        table_name="identifier_mapping_unmatched_observation",
        schema="system",
    )
    op.drop_index(
        "ix_identifier_mapping_unmatched_status",
        table_name="identifier_mapping_unmatched_observation",
        schema="system",
    )
    op.drop_table("identifier_mapping_unmatched_observation", schema="system")

    op.drop_constraint(
        IDENTIFIER_UNIQUE,
        IDENTIFIER_TABLE,
        schema=IDENTIFIER_SCHEMA,
        type_="unique",
    )
    op.drop_column(IDENTIFIER_TABLE, "valid_from_key", schema=IDENTIFIER_SCHEMA)
    op.create_unique_constraint(
        IDENTIFIER_UNIQUE,
        IDENTIFIER_TABLE,
        ["instrument_id", "id_type", "id_value", "valid_from", "source"],
        schema=IDENTIFIER_SCHEMA,
    )
    op.drop_index(
        IDENTIFIER_FK_INDEX,
        table_name=IDENTIFIER_TABLE,
        schema=IDENTIFIER_SCHEMA,
    )
