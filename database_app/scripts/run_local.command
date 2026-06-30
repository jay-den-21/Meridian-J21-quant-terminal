#!/bin/zsh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

PYTHON_BIN="${PYTHON_BIN:-../database_system_cli/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN=python3
fi

export PYTHONPATH=src
unset EODHD_API_KEY
exec "$PYTHON_BIN" -m eodhd_codegen_app --host 127.0.0.1 --port 0 --open-browser
