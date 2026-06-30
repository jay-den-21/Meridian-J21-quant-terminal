#!/bin/zsh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$APP_DIR/dist"
APP_BUNDLE="$BUILD_DIR/EODHD Code Generator.app"
MACOS_DIR="$APP_BUNDLE/Contents/MacOS"
RESOURCES_DIR="$APP_BUNDLE/Contents/Resources"
BUNDLED_APP_DIR="$RESOURCES_DIR/database_app"

rm -rf "$APP_BUNDLE"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
mkdir -p "$BUNDLED_APP_DIR"

cp -R "$APP_DIR/src" "$BUNDLED_APP_DIR/src"
cp "$APP_DIR/pyproject.toml" "$BUNDLED_APP_DIR/pyproject.toml"
cp "$APP_DIR/README.md" "$BUNDLED_APP_DIR/README.md"
cp "$APP_DIR/PROJECT.md" "$BUNDLED_APP_DIR/PROJECT.md"
cp "$APP_DIR/PROJECT.html" "$BUNDLED_APP_DIR/PROJECT.html"
cp "$APP_DIR/PROGRESS.md" "$BUNDLED_APP_DIR/PROGRESS.md"
cp -R "$APP_DIR/docs" "$BUNDLED_APP_DIR/docs"
find "$BUNDLED_APP_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$BUNDLED_APP_DIR" -type f -name '*.py[cod]' -delete

cat > "$APP_BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>eodhd-code-generator</string>
  <key>CFBundleIdentifier</key>
  <string>com.financial-data-platform.eodhd-code-generator</string>
  <key>CFBundleName</key>
  <string>EODHD Code Generator</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0.0</string>
</dict>
</plist>
PLIST

cat > "$MACOS_DIR/eodhd-code-generator" <<LAUNCHER
#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="\${0:A:h}"
RESOURCES_DIR="\$(cd "\$SCRIPT_DIR/../Resources" && pwd)"
DB_APP="\$RESOURCES_DIR/database_app"
cd "\$DB_APP"

PYTHON_BIN="\${PYTHON_BIN:-python3}"

export PYTHONPATH=src
unset EODHD_API_KEY
exec "\$PYTHON_BIN" -m eodhd_codegen_app --host 127.0.0.1 --port 0 --open-browser
LAUNCHER

chmod +x "$MACOS_DIR/eodhd-code-generator"
echo "Built $APP_BUNDLE"
