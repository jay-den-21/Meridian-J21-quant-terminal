from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CODEGEN_SITE = ROOT / "database_app" / "site"


class LocalReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for attribute in ("href", "src"):
            if value := values.get(attribute):
                self.references.append(value)


def test_codegen_site_is_independent() -> None:
    index = (CODEGEN_SITE / "index.html").read_text(encoding="utf-8")
    assert "EODHD API Code Generator" in index
    for forbidden in ("Jayden21", "Meridian", "data-view", "personal_site", "research_terminal", "j21_terminal"):
        assert forbidden not in index
    assert not (CODEGEN_SITE / "app.js").exists()
    assert not (CODEGEN_SITE / "assets/jayden-profile.jpeg").exists()


def test_shipped_static_references_resolve_without_private_siblings() -> None:
    assert (CODEGEN_SITE / "index.html").is_file()
    for html in CODEGEN_SITE.glob("*.html"):
        parser = LocalReferenceParser()
        parser.feed(html.read_text(encoding="utf-8"))
        for reference in parser.references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            if parsed.path.startswith("downloads/"):
                continue  # Developer-built installers are not source artifacts.
            path = (html.parent / unquote(parsed.path)).resolve()
            assert path.is_relative_to(CODEGEN_SITE)
            assert path.exists(), reference
    styles = (CODEGEN_SITE / "styles.css").read_text(encoding="utf-8")
    for reference in re.findall(r'url\(["\']?([^"\')]+)', styles):
        if not reference.startswith(("#", "data:", "http://", "https://")):
            assert (CODEGEN_SITE / reference).is_file()


def test_codegen_packaging_targets_codegen_only() -> None:
    script = (ROOT / "database_app/scripts/package_macos_app.sh").read_text(encoding="utf-8")
    assert 'SITE_DOWNLOADS_DIR="$APP_DIR/site/downloads"' in script
    assert 'cp "$DMG_PATH" "$SITE_DOWNLOADS_DIR/"' in script
    for private_root in ("personal_site", "research_terminal", "j21_terminal", "playground"):
        assert private_root not in script
