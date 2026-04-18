#!/usr/bin/env bash
set -euo pipefail

USER="${1:-itsbigtimetommie}"
OUT_DIR="$(dirname "$0")/games"
UA="chess-coach/1.0 (preston.yadegar@gmail.com)"

mkdir -p "$OUT_DIR"

archives=$(curl -fsS -A "$UA" "https://api.chess.com/pub/player/$USER/games/archives" \
  | python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)["archives"]))')

echo "Found $(echo "$archives" | wc -l | tr -d ' ') monthly archives."

while IFS= read -r url; do
  # url like https://api.chess.com/pub/player/USER/games/YYYY/MM
  ym="${url##*games/}"   # YYYY/MM
  year="${ym%%/*}"
  month="${ym##*/}"
  out="$OUT_DIR/${year}-${month}.pgn"

  if [[ -s "$out" ]]; then
    echo "skip  $year-$month (exists)"
    continue
  fi

  echo "fetch $year-$month"
  curl -fsS -A "$UA" "$url/pgn" -o "$out"
  sleep 0.3
done <<< "$archives"

echo "Done. PGNs in $OUT_DIR"
