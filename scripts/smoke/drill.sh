#!/usr/bin/env bash
# Smoke test: GET /players/{username}/drill
# Usage: bash scripts/smoke/drill.sh [username]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
USERNAME="${1:-testuser}"
BASE="http://localhost:8000"

echo "=== drill smoke test for '$USERNAME' ==="

# 1. Valid motif
echo "-- fork_missed motif:"
curl -sf "$BASE/players/$USERNAME/drill?motif=fork_missed" \
  | python3 -m json.tool 2>/dev/null || true

# 2. Auto-detect motif (no param)
echo "-- auto motif:"
curl -sf "$BASE/players/$USERNAME/drill" \
  | python3 -m json.tool 2>/dev/null || true

# 3. Unknown motif → 400
echo "-- bad motif (expect 400):"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/players/$USERNAME/drill?motif=bad")
echo "HTTP $STATUS"
[ "$STATUS" = "400" ] && echo "PASS" || { echo "FAIL: expected 400, got $STATUS"; exit 1; }

# 4. Unknown player → 404
echo "-- unknown player (expect 404):"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/players/__nobody__/drill")
echo "HTTP $STATUS"
[ "$STATUS" = "404" ] && echo "PASS" || { echo "FAIL: expected 404, got $STATUS"; exit 1; }

echo "=== all drill checks passed ==="
