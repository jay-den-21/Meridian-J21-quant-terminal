import pytest

from fdp.storage.schema import ensure_runtime_schemas, missing_runtime_schemas


class FakeInspector:
    def __init__(self, schema_names: list[str]) -> None:
        self.schema_names = schema_names

    def get_schema_names(self) -> list[str]:
        return self.schema_names


def test_missing_runtime_schemas_reports_required_schemas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fdp.storage.schema.inspect",
        lambda connection: FakeInspector(["us_share"]),
    )

    assert missing_runtime_schemas(object()) == ["system"]


def test_ensure_runtime_schemas_raises_with_alembic_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fdp.storage.schema.inspect",
        lambda connection: FakeInspector([]),
    )

    with pytest.raises(RuntimeError, match="poetry run alembic upgrade head"):
        ensure_runtime_schemas(object())


def test_ensure_runtime_schemas_passes_when_required_schemas_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdp.storage.schema.inspect",
        lambda connection: FakeInspector(["us_share", "system", "a_share"]),
    )

    ensure_runtime_schemas(object())

