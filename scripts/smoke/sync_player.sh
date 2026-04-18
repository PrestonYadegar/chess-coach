#!/usr/bin/env bash
# Smoke test for POST /players/{username}/sync.
# Starts uvicorn against a temp sqlite, calls the endpoint, and prints results.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API_DIR="$ROOT/apps/api"
VENV="$API_DIR/.venv"
USERNAME="${1:-itsbigtimetommie}"
TMP_DB="$(mktemp -t chess_coach_smoke.XXXXXX.sqlite)"
trap 'rm -f "$TMP_DB"' EXIT

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "venv missing; run scripts/run-api.sh once first" >&2
  exit 1
fi

cd "$API_DIR"
CHESS_COACH_DB="$TMP_DB" "$VENV/bin/uvicorn" app.main:app \
  --host 127.0.0.1 --port 8765 --log-level warning &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null; rm -f "$TMP_DB"' EXIT

# wait for /health
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:8765/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.3
done

echo "Calling POST /players/$USERNAME/sync (this may take a while)..."
curl -fsS -X POST "http://127.0.0.1:8765/players/$USERNAME/sync" | tee /tmp/sync_result.json
echo
echo "Row count:"
"$VENV/bin/python" -c "import sqlite3,sys; c=sqlite3.connect('$TMP_DB'); print(c.execute('SELECT COUNT(*) FROM games').fetchone()[0], 'games stored')"

echo "Idempotency check — running sync again..."
curl -fsS -X POST "http://127.0.0.1:8765/players/$USERNAME/sync" | tee /tmp/sync_result2.json
echo
"$VENV/bin/python" -c "import sqlite3; c=sqlite3.connect('$TMP_DB'); print(c.execute('SELECT COUNT(*) FROM games').fetchone()[0], 'games after second sync')"
