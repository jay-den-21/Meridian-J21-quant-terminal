"""add intraday Parquet file manifest

Revision ID: 0020_intraday_manifest
Revises: 0019_daily_task_ledger
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0020_intraday_manifest"
down_revision: str | None = "0019_daily_task_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "system"
TABLE = "intraday_file_manifest"

EXPECTED_COLUMNS: dict[str, tuple[type[sa.types.TypeEngine], int | None]] = {
    "manifest_id": (sa.BigInteger, None),
    "run_id": (sa.BigInteger, None),
    "dataset_kind": (sa.String, 32),
    "source": (sa.String, 32),
    "market": (sa.String, 16),
    "asset_type": (sa.String, 32),
    "interval": (sa.String, 16),
    "instrument_id": (sa.BigInteger, None),
    "provider_symbol": (sa.String, 128),
    "trade_date": (sa.Date, None),
    "bucket": (sa.Integer, None),
    "storage_path": (sa.String, 512),
    "content_hash": (sa.String, 64),
    "file_sha256": (sa.String, 64),
    "row_count": (sa.BigInteger, None),
    "file_size_bytes": (sa.BigInteger, None),
    "timestamp_min_utc": (sa.DateTime, None),
    "timestamp_max_utc": (sa.DateTime, None),
    "schema_version": (sa.Integer, None),
    "status": (sa.String, 32),
    "created_at": (sa.DateTime, None),
    "updated_at": (sa.DateTime, None),
}


def _validate_existing_table(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    columns = {
        column["name"]: column
        for column in inspector.get_columns(TABLE, schema=SCHEMA)
    }
    if set(columns) != set(EXPECTED_COLUMNS):
        raise RuntimeError(
            f"refusing incompatible system.{TABLE} columns: "
            f"actual={sorted(columns)}"
        )
    for name, (expected_type, expected_length) in EXPECTED_COLUMNS.items():
        actual = columns[name]
        if not isinstance(actual["type"], expected_type):
            raise RuntimeError(
                f"refusing incompatible system.{TABLE}.{name} type: actual={actual['type']}"
            )
        if expected_length is not None and actual["type"].length != expected_length:
            raise RuntimeError(
                f"refusing incompatible system.{TABLE}.{name} length: "
                f"actual={actual['type'].length}"
            )
        if actual["nullable"]:
            raise RuntimeError(f"refusing nullable system.{TABLE}.{name}")
    if columns["manifest_id"].get("autoincrement") is not True:
        raise RuntimeError(
            f"refusing non-autoincrement system.{TABLE}.manifest_id: "
            f"actual={columns['manifest_id'].get('autoincrement')}"
        )
    for name in ("created_at", "updated_at"):
        default = str(columns[name].get("default") or "").lower()
        if "current_timestamp" not in default:
            raise RuntimeError(
                f"refusing system.{TABLE}.{name} without CURRENT_TIMESTAMP default"
            )

    primary_key = inspector.get_pk_constraint(TABLE, schema=SCHEMA)
    if list(primary_key.get("constrained_columns") or []) != ["manifest_id"]:
        raise RuntimeError(
            f"refusing incompatible system.{TABLE} primary key: actual={primary_key}"
        )

    uniques = {
        constraint["name"]: list(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(TABLE, schema=SCHEMA)
    }
    expected_uniques = {
        "uq_intraday_manifest_identity": [
            "dataset_kind",
            "source",
            "instrument_id",
            "interval",
            "trade_date",
        ],
        "uq_intraday_manifest_storage_path": ["storage_path"],
    }
    for name, expected in expected_uniques.items():
        if uniques.get(name) != expected:
            raise RuntimeError(
                f"refusing incompatible system.{TABLE} constraint {name}: "
                f"actual={uniques.get(name)}"
            )

    foreign_keys = {
        foreign_key["name"]: (
            list(foreign_key["constrained_columns"]),
            foreign_key["referred_schema"],
            foreign_key["referred_table"],
            list(foreign_key["referred_columns"]),
        )
        for foreign_key in inspector.get_foreign_keys(TABLE, schema=SCHEMA)
    }
    expected_foreign_keys = {
        "fk_intraday_manifest_run": (["run_id"], "system", "ingestion_task_run", ["run_id"]),
        "fk_intraday_manifest_instrument": (
            ["instrument_id"],
            "us_share",
            "instrument",
            ["instrument_id"],
        ),
    }
    for name, expected in expected_foreign_keys.items():
        if foreign_keys.get(name) != expected:
            raise RuntimeError(
                f"refusing incompatible system.{TABLE} foreign key {name}: "
                f"actual={foreign_keys.get(name)}"
            )


def _ensure_indexes(bind: sa.Connection) -> None:
    indexes = {
        index["name"]: list(index["column_names"])
        for index in sa.inspect(bind).get_indexes(TABLE, schema=SCHEMA)
    }
    expected = {
        "ix_intraday_manifest_run_id": ["run_id"],
        "ix_intraday_manifest_symbol_date": ["provider_symbol", "trade_date"],
    }
    for name, columns in expected.items():
        actual = indexes.get(name)
        if actual is not None and actual != columns:
            raise RuntimeError(f"refusing incompatible {name}: actual={actual}")
        if actual is None:
            op.create_index(name, TABLE, columns, schema=SCHEMA)


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        _validate_existing_table(bind)
        _ensure_indexes(bind)
        return

    op.create_table(
        TABLE,
        sa.Column("manifest_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_kind", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.String(length=16), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_symbol", sa.String(length=128), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("bucket", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("timestamp_min_utc", sa.DateTime(), nullable=False),
        sa.Column("timestamp_max_utc", sa.DateTime(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
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
            name="fk_intraday_manifest_run",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["us_share.instrument.instrument_id"],
            name="fk_intraday_manifest_instrument",
        ),
        sa.PrimaryKeyConstraint("manifest_id"),
        sa.UniqueConstraint(
            "dataset_kind",
            "source",
            "instrument_id",
            "interval",
            "trade_date",
            name="uq_intraday_manifest_identity",
        ),
        sa.UniqueConstraint(
            "storage_path",
            name="uq_intraday_manifest_storage_path",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_intraday_manifest_run_id",
        TABLE,
        ["run_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_intraday_manifest_symbol_date",
        TABLE,
        ["provider_symbol", "trade_date"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        return
    row_count = int(
        bind.execute(
            sa.text("SELECT COUNT(*) FROM `system`.intraday_file_manifest")
        ).scalar_one()
    )
    if row_count:
        raise RuntimeError("refusing downgrade while intraday manifest evidence exists")
    op.drop_table(TABLE, schema=SCHEMA)
