from pathlib import Path
from types import SimpleNamespace

import pytest

import fdp.migrate.corporate_action_identity as migration_module


def test_corporate_action_migration_adopts_legacy_table_without_dropping_rows() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0017_corporate_actions.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | None = "0016_guided_bulk_reconcile"' in migration
    assert "has_table(TABLE, schema=SCHEMA)" in migration
    assert "refusing to adopt incomplete corporate_action table" in migration
    assert "uq_corporate_action_identity" in migration
    assert "ix_corporate_action_provider_symbol_date" in migration
    assert "refusing downgrade while corporate action rows exist" in migration


class _BeginContext:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, traceback):
        return False


class _FakeEngine:
    def begin(self):
        return _BeginContext()


def test_stock_only_reconcile_marks_check_failed_when_execution_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = RuntimeError("write failed")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        migration_module,
        "CorporateActionIdentityResolver",
        SimpleNamespace(from_connection=lambda *args, **kwargs: object()),
    )
    monkeypatch.setattr(migration_module, "_instrument_asset_types", lambda connection: {})
    monkeypatch.setattr(migration_module, "_create_check_run", lambda connection: 17)
    monkeypatch.setattr(
        migration_module,
        "_execute_corporate_action_identity_reconcile",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )
    monkeypatch.setattr(
        migration_module,
        "_mark_check_run_failed",
        lambda engine, *, check_run_id, error: captured.update(
            check_run_id=check_run_id,
            error=error,
        ),
    )

    with pytest.raises(RuntimeError, match="write failed"):
        migration_module.reconcile_corporate_action_identities(_FakeEngine())

    assert captured == {"check_run_id": 17, "error": failure}
