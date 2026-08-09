#!/usr/bin/env python3
"""Render the project's simple governance Markdown into standalone HTML.

The project docs intentionally use headings, paragraphs, flat lists, links, tables,
and fenced code blocks. Keeping this renderer dependency-free lets documentation
be updated without adding a web stack to the database CLI runtime.
"""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import re


STYLE = """
:root { --bg:#f6f7f9; --paper:#fff; --text:#20242a; --muted:#667085;
  --border:#d9dee7; --accent:#1769aa; --code:#f1f4f8; --nav:#15191e; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; background:var(--bg); color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
  "Microsoft YaHei",sans-serif; line-height:1.7; }
.layout { display:grid; grid-template-columns:280px minmax(0,1fr); min-height:100vh; }
nav { position:sticky; top:0; height:100vh; overflow:auto; padding:28px 20px;
  background:var(--nav); color:#d9e2ec; border-right:1px solid #0b1118; }
nav h2 { margin:0 0 16px; color:#fff; font-size:15px; }
nav a { display:block; padding:6px 0; color:#c9d2dc; text-decoration:none;
  border-bottom:1px solid rgba(255,255,255,.06); font-size:13px; line-height:1.35; }
nav a:hover { color:#fff; }
.toc-1 { font-weight:700; } .toc-2 { padding-left:10px; }
.toc-3 { padding-left:22px; color:#aebccc; }
main { padding:42px 24px 64px; }
article { max-width:980px; margin:0 auto; padding:44px 54px; background:var(--paper);
  border:1px solid var(--border); border-radius:8px; box-shadow:0 12px 30px rgba(16,24,32,.06); }
h1,h2,h3 { line-height:1.3; letter-spacing:0; }
h1 { margin:0 0 24px; font-size:34px; }
h2 { margin:42px 0 14px; padding-top:8px; font-size:25px; border-top:1px solid var(--border); }
h3 { margin:28px 0 10px; font-size:20px; }
p { margin:12px 0; } ul,ol { margin:10px 0 16px 22px; padding:0; }
li { margin:6px 0; }
table { width:100%; border-collapse:collapse; min-width:620px; font-size:14px; }
.table-wrap { overflow-x:auto; margin:16px 0 22px; border:1px solid var(--border);
  border-radius:6px; }
th,td { padding:11px 13px; border-right:1px solid var(--border);
  border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }
th:last-child,td:last-child { border-right:0; }
thead th { background:#edf2f7; color:#344054; font-weight:700; }
tbody tr:last-child td { border-bottom:0; }
tbody tr:nth-child(even) { background:#fafbfc; }
code { padding:1px 5px; background:var(--code); border:1px solid #e1e6ef;
  border-radius:5px; font-family:"SFMono-Regular",Consolas,monospace; font-size:.92em; }
pre { overflow:auto; margin:16px 0 20px; padding:16px 18px; background:#101820;
  color:#e6edf3; border-radius:8px; line-height:1.5; }
pre code { padding:0; background:transparent; color:inherit; border:0; font-size:13px; }
.mermaid { overflow:auto; margin:18px 0 24px; padding:22px 16px; background:#fbfcfe;
  border:1px solid var(--border); border-radius:8px; text-align:center; }
a { color:var(--accent); } .meta { margin-bottom:26px; padding-bottom:18px;
  color:var(--muted); border-bottom:1px solid var(--border); font-size:13px; }
@media (max-width:900px) { .layout { display:block; } nav { position:relative; height:auto;
  max-height:42vh; } main { padding:18px 12px 40px; } article { padding:28px 22px; }
  h1 { font-size:28px; } h2 { font-size:22px; } }
@media print { body { background:#fff; } .layout { display:block; } nav { display:none; }
  main { padding:0; } article { max-width:none; padding:0; border:0; box-shadow:none; } }
"""


def _plain_text(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", value)
    return value.replace("**", "").strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^\w\u3400-\u9fff]+", "-", _plain_text(value).lower(), flags=re.UNICODE)
    return slug.strip("-") or "section"


def _inline(value: str) -> str:
    rendered = escape(value)
    rendered = re.sub(r"`([^`]+)`", r"<code>\1</code>", rendered)
    rendered = re.sub(
        r"\[([^]]+)]\((https?://[^)]+)\)",
        r'<a href="\2">\1</a>',
        rendered,
    )
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    return rendered


def _split_table_row(line: str) -> list[str]:
    """Split one Markdown table row while preserving escaped pipe characters."""
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith(r"\|"):
        value = value[:-1]
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", value)]


def _table_alignments(separator: str, columns: int) -> list[str] | None:
    cells = _split_table_row(separator)
    if len(cells) != columns:
        return None

    alignments: list[str] = []
    for cell in cells:
        marker = re.sub(r"\s+", "", cell)
        if not re.fullmatch(r":?-{3,}:?", marker):
            return None
        if marker.startswith(":") and marker.endswith(":"):
            alignments.append("center")
        elif marker.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")
    return alignments


def _render_table(
    headers: list[str],
    rows: list[list[str]],
    alignments: list[str],
) -> str:
    header_html = "".join(
        f'<th scope="col" style="text-align:{alignment}">{_inline(value)}</th>'
        for value, alignment in zip(headers, alignments, strict=True)
    )
    rows_html = "".join(
        "<tr>"
        + "".join(
            f'<td style="text-align:{alignment}">{_inline(value)}</td>'
            for value, alignment in zip(row, alignments, strict=True)
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        f"{header_html}</tr></thead><tbody>{rows_html}</tbody></table></div>"
    )


def _render_body(markdown: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = markdown.splitlines()
    output: list[str] = []
    headings: list[tuple[int, str, str]] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None
    code_lines: list[str] = []
    code_language = ""
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_items and list_tag:
            items = "".join(f"<li>{_inline(item)}</li>" for item in list_items)
            output.append(f"<{list_tag}>{items}</{list_tag}>")
        list_items.clear()
        list_tag = None

    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1

        if in_code:
            if line.startswith("```"):
                code = escape(chr(10).join(code_lines))
                if code_language == "mermaid":
                    output.append(f'<div class="mermaid">{code}</div>')
                else:
                    language = (
                        f' class="language-{escape(code_language)}"' if code_language else ""
                    )
                    output.append(f"<pre><code{language}>{code}</code></pre>")
                code_lines.clear()
                code_language = ""
                in_code = False
            else:
                code_lines.append(line)
            continue

        if "|" in line and index < len(lines):
            headers = _split_table_row(line)
            alignments = _table_alignments(lines[index], len(headers))
            if alignments is not None:
                flush_paragraph()
                flush_list()
                index += 1
                table_rows: list[list[str]] = []
                while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                    cells = _split_table_row(lines[index])
                    if len(cells) != len(headers):
                        break
                    table_rows.append(cells)
                    index += 1
                output.append(_render_table(headers, table_rows, alignments))
                continue

        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            in_code = True
            code_language = line[3:].strip()
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            label = heading.group(2).strip()
            anchor = _slug(label)
            headings.append((level, anchor, label))
            output.append(f'<h{level} id="{anchor}">{_inline(label)}</h{level}>')
            continue

        unordered = re.match(r"^-\s+(.+)$", line)
        ordered = re.match(r"^\d+\.\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            tag = "ul" if unordered else "ol"
            if list_tag not in {None, tag}:
                flush_list()
            list_tag = tag
            list_items.append((unordered or ordered).group(1))
            continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            continue

        flush_list()
        paragraph.append(line.strip())

    if in_code:
        output.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
    flush_paragraph()
    flush_list()
    return "".join(output), headings


def render(markdown_path: Path, html_path: Path) -> None:
    markdown = markdown_path.read_text(encoding="utf-8")
    body, headings = _render_body(markdown)
    title = _plain_text(headings[0][2]) if headings else markdown_path.stem
    toc = "".join(
        f'<a class="toc-{level}" href="#{anchor}">{_inline(label)}</a>'
        for level, anchor, label in headings
    )
    mermaid_script = ""
    if '<div class="mermaid">' in body:
        mermaid_script = """<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.12.0/+esm";
mermaid.initialize({ startOnLoad: true, theme: "neutral", securityLevel: "strict" });
</script>"""
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><style>{STYLE}</style></head>
<body><div class="layout"><nav><h2>目录 / Contents</h2>{toc}</nav>
<main><article><div class="meta">Generated from {escape(markdown_path.name)}. Markdown remains the source of truth.</div>
{body}</article></main></div>{mermaid_script}</body></html>
"""
    html_path.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown", type=Path)
    parser.add_argument("html", type=Path)
    args = parser.parse_args()
    render(args.markdown, args.html)


if __name__ == "__main__":
    main()
