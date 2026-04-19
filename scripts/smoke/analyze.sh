#!/usr/bin/env bash
# Smoke test: POST /games/{id}/analyze
# Usage: bash scripts/smoke/analyze.sh [game_id]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GAME_ID="${1:-1}"

bash "$ROOT/scripts/run-api.sh" &
API_PID=$!
trap "kill $API_PID 2>/dev/null; pkill -f 'uvicorn app.main:app' 2>/dev/null || true" EXIT

for i in $(seq 1 15); do
  sleep 1
  curl -sf http://localhost:8000/health > /dev/null && break
done

echo "--- analyzing game $GAME_ID ---"
curl -sf -X POST "http://localhost:8000/games/$GAME_ID/analyze" | python3 -m json.tool

echo "--- idempotency check ---"
curl -sf -X POST "http://localhost:8000/games/$GAME_ID/analyze" | python3 -m json.tool

echo "--- 404 on missing game ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000/games/9999/analyze")
[ "$STATUS" = "404" ] && echo "PASS: got 404" || (echo "FAIL: expected 404, got $STATUS"; exit 1)

echo "SMOKE PASS"
