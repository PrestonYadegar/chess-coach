#!/usr/bin/env bash
# Import Lichess open puzzle DB into local SQLite.
# Usage: scripts/import-puzzles.sh [--file PATH] [--limit N]
#
# Without --file, streams directly from https://database.lichess.org/lichess_db_puzzle.csv.zst
# (warning: ~350MB download). Pass --limit 50000 for a useful subset.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$ROOT/apps/api/.venv" ]; then
  echo "No venv found — run scripts/run-api.sh first to create it." >&2
  exit 1
fi

source "$ROOT/apps/api/.venv/bin/activate"
cd "$ROOT/apps/api"
python -m app.import_puzzles "$@"
