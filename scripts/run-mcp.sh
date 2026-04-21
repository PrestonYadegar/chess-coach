#!/usr/bin/env bash
# Run the chess-coach MCP server (stdio transport).
# Claude Desktop / Cursor should invoke this script as the MCP command.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/apps/api/.venv"

if [ ! -d "$VENV" ]; then
  echo "venv not found at $VENV — run scripts/run-api.sh first to create it" >&2
  exit 1
fi

cd "$ROOT/apps/api"
exec "$VENV/bin/python" -m app.mcp_server
