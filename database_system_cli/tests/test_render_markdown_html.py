from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def _load_renderer() -> ModuleType:
    script_path = Path(__file__).parents[1] / "scripts" / "render_markdown_html.py"
    spec = spec_from_file_location("render_markdown_html", script_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_render_body = _load_renderer()._render_body


def test_render_body_converts_markdown_table_to_html() -> None:
    body, headings = _render_body(
        """# Architecture

| Path | Responsibility | Forbidden |
| --- | :---: | ---: |
| `src/fdp/get_data/` | Shared jobs | UI logic |
| `src/fdp/storage/` | Upserts | Parsing |

After table.
"""
    )

    assert headings == [(1, "architecture", "Architecture")]
    assert '<div class="table-wrap"><table>' in body
    assert '<th scope="col" style="text-align:left">Path</th>' in body
    assert '<th scope="col" style="text-align:center">Responsibility</th>' in body
    assert '<td style="text-align:right">UI logic</td>' in body
    assert "| --- |" not in body
    assert "<p>After table.</p>" in body


def test_render_body_converts_mermaid_fence_to_renderable_container() -> None:
    body, _ = _render_body(
        """# Flow

```mermaid
flowchart LR
    A[Input] --> B[Published]
```
"""
    )

    assert '<div class="mermaid">flowchart LR' in body
    assert "A[Input] --&gt; B[Published]" in body
    assert 'class="language-mermaid"' not in body
