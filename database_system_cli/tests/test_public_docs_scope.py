"""CLI docs checks must work without unpublished sibling applications."""

from pathlib import Path
from types import SimpleNamespace

from fdp import docs_staleness


def test_html_pairs_only_belong_to_the_cli(tmp_path: Path, monkeypatch) -> None:
    cli = tmp_path / "database_system_cli"
    documents = (
        "PROJECT",
        "docs/architecture",
        "docs/cli_commands",
        "docs/terminal_menu",
        "docs/system_tables",
        "docs/technical_indicator_parity_report",
    )
    rendered = []
    for relative in documents:
        path = cli / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".md").write_text("source", encoding="utf-8")
        path.with_suffix(".html").write_text("rendered", encoding="utf-8")

    def render(source: Path, destination: Path) -> None:
        rendered.append(source)
        destination.write_text("rendered", encoding="utf-8")

    monkeypatch.setattr(docs_staleness, "_load_renderer", lambda _: SimpleNamespace(render=render))
    assert docs_staleness._stale_html_pairs(repo_root=tmp_path, cli_root=cli) == set()
    assert len(rendered) == len(documents)
    assert all(path.is_relative_to(cli) for path in rendered)

    (cli / "docs/architecture.html").unlink()
    assert docs_staleness._stale_html_pairs(repo_root=tmp_path, cli_root=cli) == {
        "database_system_cli/docs/architecture.html"
    }
