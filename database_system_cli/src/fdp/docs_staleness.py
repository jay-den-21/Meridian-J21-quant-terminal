"""Validate CLI tutorial coverage and deterministic Markdown/HTML mirrors."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import ModuleType

from click import Command, Group

_COMMAND_TOKEN = r"[a-z0-9][a-z0-9-]*"
_J21_COMMAND = re.compile(
    rf"(?:poetry\s+run\s+)?j21(?:\s+({_COMMAND_TOKEN}(?:\s+{_COMMAND_TOKEN})*))?"
)


@dataclass(frozen=True)
class DocsStalenessReport:
    """One read-only documentation consistency result."""

    documented_leaf_routes: tuple[str, ...]
    actual_leaf_routes: tuple[str, ...]
    missing_routes: tuple[str, ...]
    unknown_routes: tuple[str, ...]
    stale_html_pairs: tuple[str, ...]

    @property
    def is_current(self) -> bool:
        return not (self.missing_routes or self.unknown_routes or self.stale_html_pairs)


def validate_docs_staleness(root: Path, command_tree: Command) -> DocsStalenessReport:
    """Check current Typer leaves and managed HTML mirrors without modifying the repo."""
    repo_root, cli_root = _resolve_roots(root)
    cli_markdown = cli_root / "docs" / "cli_commands.md"
    documented, unknown = _documented_leaf_routes(
        cli_markdown.read_text(encoding="utf-8"),
        command_tree,
    )
    actual = _leaf_routes(command_tree)
    stale_pairs = _stale_html_pairs(repo_root=repo_root, cli_root=cli_root)
    return DocsStalenessReport(
        documented_leaf_routes=tuple(sorted(documented)),
        actual_leaf_routes=tuple(sorted(actual)),
        missing_routes=tuple(sorted(actual - documented)),
        unknown_routes=tuple(sorted(unknown)),
        stale_html_pairs=tuple(sorted(stale_pairs)),
    )


def _resolve_roots(root: Path) -> tuple[Path, Path]:
    resolved = root.expanduser().resolve()
    direct_cli = resolved / "src" / "fdp"
    nested_cli = resolved / "database_system_cli" / "src" / "fdp"
    if direct_cli.is_dir():
        return resolved.parent, resolved
    if nested_cli.is_dir():
        return resolved, resolved / "database_system_cli"
    raise ValueError("root must be the repository or database_system_cli directory")


def _leaf_routes(command: Command, prefix: tuple[str, ...] = ()) -> set[str]:
    if isinstance(command, Group) and command.commands:
        leaves: set[str] = set()
        for name, child in command.commands.items():
            leaves.update(_leaf_routes(child, (*prefix, name)))
        return leaves
    return {" ".join(prefix)} if prefix else set()


def _documented_leaf_routes(markdown: str, command_tree: Command) -> tuple[set[str], set[str]]:
    documented: set[str] = set()
    unknown: set[str] = set()
    for match in _J21_COMMAND.finditer(markdown):
        tokens = (match.group(1) or "").split()
        current = command_tree
        route: list[str] = []
        for token in tokens:
            if not isinstance(current, Group) or token not in current.commands:
                if isinstance(current, Group) and current.commands:
                    unknown.add(" ".join((*route, token)))
                break
            current = current.commands[token]
            route.append(token)
        if route and not (isinstance(current, Group) and current.commands):
            documented.add(" ".join(route))
    return documented, unknown


def _stale_html_pairs(*, repo_root: Path, cli_root: Path) -> set[str]:
    renderer_path = cli_root / "scripts" / "render_markdown_html.py"
    renderer = _load_renderer(renderer_path)
    pairs = [
        (cli_root / "PROJECT.md", cli_root / "PROJECT.html"),
        (cli_root / "docs" / "architecture.md", cli_root / "docs" / "architecture.html"),
        (cli_root / "docs" / "cli_commands.md", cli_root / "docs" / "cli_commands.html"),
        (cli_root / "docs" / "terminal_menu.md", cli_root / "docs" / "terminal_menu.html"),
        (
            cli_root / "docs" / "technical_indicator_parity_report.md",
            cli_root / "docs" / "technical_indicator_parity_report.html",
        ),
        (repo_root / "research_terminal" / "PROJECT.md", repo_root / "research_terminal" / "PROJECT.html"),
    ]
    stale: set[str] = set()
    with TemporaryDirectory(prefix="j21-docs-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        for index, (markdown_path, html_path) in enumerate(pairs):
            relative_html = str(html_path.relative_to(repo_root))
            if not markdown_path.is_file() or not html_path.is_file():
                stale.add(relative_html)
                continue
            rendered_path = temporary_root / f"rendered-{index}.html"
            renderer.render(markdown_path, rendered_path)
            if rendered_path.read_bytes() != html_path.read_bytes():
                stale.add(relative_html)
    return stale


def _load_renderer(path: Path) -> ModuleType:
    spec = spec_from_file_location("j21_render_markdown_html", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load documentation renderer: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
