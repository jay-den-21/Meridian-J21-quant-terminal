#!/bin/zsh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="EODHD Code Generator"
VERSION="${VERSION:-1.0.0}"
BUILD_DIR="${BUILD_DIR:-$APP_DIR/dist}"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
DMG_STAGING="$BUILD_DIR/dmg-root"
DMG_PATH="$BUILD_DIR/EODHD-Code-Generator-$VERSION.dmg"
PKG_PATH="$BUILD_DIR/EODHD-Code-Generator-$VERSION.pkg"
CHECKSUMS_PATH="$BUILD_DIR/SHA256SUMS.txt"
MACOS_DIR="$APP_BUNDLE/Contents/MacOS"
RESOURCES_DIR="$APP_BUNDLE/Contents/Resources"
BUNDLED_APP_DIR="$RESOURCES_DIR/database_app"
VENDOR_DIR="$BUNDLED_APP_DIR/python_lib"
SITE_DOWNLOADS_DIR="$APP_DIR/site/downloads"

PYTHON_BIN="${PYTHON_BIN:-$APP_DIR/../database_system_cli/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN=python3
fi

echo "Using Python: $("$PYTHON_BIN" --version 2>&1)"
mkdir -p "$BUILD_DIR"
rm -rf "$APP_BUNDLE" "$DMG_STAGING"
rm -f "$DMG_PATH" "$PKG_PATH" "$CHECKSUMS_PATH"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$BUNDLED_APP_DIR"

cp -R "$APP_DIR/src" "$BUNDLED_APP_DIR/src"
cp "$APP_DIR/pyproject.toml" "$BUNDLED_APP_DIR/pyproject.toml"
cp "$APP_DIR/README.md" "$BUNDLED_APP_DIR/README.md"
cp "$APP_DIR/PROJECT.md" "$BUNDLED_APP_DIR/PROJECT.md"
cp "$APP_DIR/PROJECT.html" "$BUNDLED_APP_DIR/PROJECT.html"
cp "$APP_DIR/PROGRESS.md" "$BUNDLED_APP_DIR/PROGRESS.md"
cp -R "$APP_DIR/docs" "$BUNDLED_APP_DIR/docs"

mkdir -p "$VENDOR_DIR"
"$PYTHON_BIN" - "$VENDOR_DIR" <<'PY'
from __future__ import annotations

import importlib.metadata as metadata
import importlib.util
import pathlib
import shutil
import sys

dest = pathlib.Path(sys.argv[1])
imports = ("sqlalchemy", "pymysql", "typing_extensions")
distributions = ("SQLAlchemy", "PyMySQL", "typing_extensions")
missing: list[str] = []


def copy_any(src: pathlib.Path, dst: pathlib.Path) -> None:
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


for import_name in imports:
    spec = importlib.util.find_spec(import_name)
    if spec is None:
        missing.append(import_name)
        continue
    if spec.submodule_search_locations:
        src = pathlib.Path(next(iter(spec.submodule_search_locations)))
        copy_any(src, dest / src.name)
    elif spec.origin:
        src = pathlib.Path(spec.origin)
        copy_any(src, dest / src.name)

for distribution_name in distributions:
    try:
        distribution = metadata.distribution(distribution_name)
    except metadata.PackageNotFoundError:
        continue
    dist_path = pathlib.Path(str(distribution._path))
    copy_any(dist_path, dest / dist_path.name)

if missing:
    raise SystemExit(
        "Missing Python package(s) for bundle: "
        + ", ".join(missing)
        + ". Install database_app dependencies or set PYTHON_BIN to the project venv."
    )
PY

find "$BUNDLED_APP_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$BUNDLED_APP_DIR" -type f -name '*.py[cod]' -delete

cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>eodhd-code-generator</string>
  <key>CFBundleIdentifier</key>
  <string>com.financial-data-platform.eodhd-code-generator</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundleDisplayName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$VERSION</string>
  <key>CFBundleVersion</key>
  <string>$VERSION</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
</dict>
</plist>
PLIST

cat > "$MACOS_DIR/eodhd-code-generator" <<'LAUNCHER'
#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
RESOURCES_DIR="$(cd "$SCRIPT_DIR/../Resources" && pwd)"
DB_APP="$RESOURCES_DIR/database_app"
cd "$DB_APP"

export PYTHONPATH="$DB_APP/src:$DB_APP/python_lib${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
unset EODHD_API_KEY

PYTHON_CANDIDATES=()
if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_CANDIDATES+=("$PYTHON_BIN")
fi
PYTHON_CANDIDATES+=(
  "$DB_APP/python_runtime/bin/python3"
  /opt/homebrew/opt/python@3.14/bin/python3.14
  /opt/homebrew/opt/python@3.13/bin/python3.13
  /opt/homebrew/opt/python@3.12/bin/python3.12
  /opt/homebrew/opt/python@3.11/bin/python3.11
  /opt/homebrew/bin/python3
  /usr/local/opt/python@3.14/bin/python3.14
  /usr/local/opt/python@3.13/bin/python3.13
  /usr/local/opt/python@3.12/bin/python3.12
  /usr/local/opt/python@3.11/bin/python3.11
  /usr/local/bin/python3
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3
  python3
)

SELECTED_PYTHON=""
for candidate in "${PYTHON_CANDIDATES[@]}"; do
  if ! command -v "$candidate" >/dev/null 2>&1; then
    continue
  fi
  if "$candidate" - <<'PY' >/dev/null 2>&1
import importlib.util
import sys

missing = [name for name in ("sqlalchemy", "pymysql") if importlib.util.find_spec(name) is None]
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required.")
if missing:
    raise SystemExit("Missing bundled dependency: " + ", ".join(missing))
PY
  then
    SELECTED_PYTHON="$candidate"
    break
  fi
done

if [[ -z "$SELECTED_PYTHON" ]]; then
  if command -v osascript >/dev/null 2>&1; then
    osascript -e 'display alert "EODHD Code Generator could not start" message "Install Python 3.11+ or launch with PYTHON_BIN pointing to a compatible Python. The app also checks common Homebrew and python.org install paths."'
  fi
  exit 1
fi

exec "$SELECTED_PYTHON" -m eodhd_codegen_app --host 127.0.0.1 --port 0 --open-browser
LAUNCHER

chmod +x "$MACOS_DIR/eodhd-code-generator"

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP_BUNDLE" >/dev/null 2>&1 || echo "Ad-hoc codesign skipped"
fi

mkdir -p "$DMG_STAGING"
cp -R "$APP_BUNDLE" "$DMG_STAGING/$APP_NAME.app"
ln -s /Applications "$DMG_STAGING/Applications"

if command -v hdiutil >/dev/null 2>&1; then
  hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_STAGING" -ov -format UDZO "$DMG_PATH" >/dev/null
  echo "Built $DMG_PATH"
else
  echo "hdiutil not found; skipped DMG build"
fi

if command -v pkgbuild >/dev/null 2>&1; then
  pkgbuild --install-location /Applications --component "$APP_BUNDLE" "$PKG_PATH" >/dev/null
  echo "Built $PKG_PATH"
else
  echo "pkgbuild not found; skipped PKG build"
fi

checksum_files=()
[[ -f "$DMG_PATH" ]] && checksum_files+=("$(basename "$DMG_PATH")")
[[ -f "$PKG_PATH" ]] && checksum_files+=("$(basename "$PKG_PATH")")
if (( ${#checksum_files[@]} )); then
  (
    cd "$BUILD_DIR"
    shasum -a 256 "${checksum_files[@]}" > "$CHECKSUMS_PATH"
  )
  echo "Built $CHECKSUMS_PATH"
fi

if [[ -d "$APP_DIR/site" ]]; then
  mkdir -p "$SITE_DOWNLOADS_DIR"
  [[ -f "$DMG_PATH" ]] && cp "$DMG_PATH" "$SITE_DOWNLOADS_DIR/"
  [[ -f "$PKG_PATH" ]] && cp "$PKG_PATH" "$SITE_DOWNLOADS_DIR/"
  [[ -f "$CHECKSUMS_PATH" ]] && cp "$CHECKSUMS_PATH" "$SITE_DOWNLOADS_DIR/"
  echo "Copied release artifacts to $SITE_DOWNLOADS_DIR"
fi

echo "Built $APP_BUNDLE"
