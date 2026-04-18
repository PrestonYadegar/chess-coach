#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT/apps/api"
VENV="$API_DIR/.venv"

if [[ ! -d "$VENV" ]]; then
  echo "Creating venv at $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install -r "$API_DIR/requirements.txt"
fi

cd "$API_DIR"
exec "$VENV/bin/uvicorn" app.main:app --reload --host 127.0.0.1 --port 8000
