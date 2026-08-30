from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


ALEMBIC_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0018_protect_external_a_share.py"
)
BASE_MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0001_initial_schema.py"
)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def alembic_migration() -> ModuleType:
    return _load_module("test_a_share_alembic_0018", ALEMBIC_PATH)


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _MigrationBind:
    def __init__(self, object_count: int) -> None:
        self.object_count = object_count
        self.calls: list[tuple[object, object]] = []

    def execute(self, statement: object, parameters: object) -> _ScalarResult:
        self.calls.append((statement, parameters))
        return _ScalarResult(self.object_count)


def test_alembic_revision_guards_any_external_schema_object(
    alembic_migration: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bind = _MigrationBind(object_count=1)
    monkeypatch.setattr(alembic_migration.op, "get_bind", lambda: bind)

    with pytest.raises(RuntimeError, match="externally owned nonempty a_share"):
        alembic_migration.downgrade()

    assert alembic_migration.down_revision == "0017_corporate_actions"
    assert bind.calls[0][1] == {"schema_name": "a_share"}


def test_alembic_revision_allows_an_empty_a_share_boundary(
    alembic_migration: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bind = _MigrationBind(object_count=0)
    monkeypatch.setattr(alembic_migration.op, "get_bind", lambda: bind)

    alembic_migration.downgrade()


def test_base_downgrade_never_drops_the_external_a_share_schema() -> None:
    source = BASE_MIGRATION_PATH.read_text(encoding="utf-8")

    assert "DROP SCHEMA IF EXISTS a_share" not in source
