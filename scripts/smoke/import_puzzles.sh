#!/usr/bin/env bash
# Smoke-test the puzzle importer using a small synthetic CSV (no network required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

source "$ROOT/apps/api/.venv/bin/activate"

SMOKE_TMP=$(mktemp -d)
trap 'rm -rf "$SMOKE_TMP"' EXIT

PUZZLE_CSV="$SMOKE_TMP/puzzles.csv"

printf 'PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags\n' > "$PUZZLE_CSV"
printf 'abcd1,rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1,e7e5 d1h5,1500,75,90,1000,opening fork,https://lichess.org/abc,\n' >> "$PUZZLE_CSV"
printf 'abcd2,r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3,f1b5,1600,80,85,800,pin discovered_attack,https://lichess.org/def,\n' >> "$PUZZLE_CSV"
printf 'abcd3,rnbqkb1r/pppp1ppp/5n2/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 2 3,d1f3,1700,60,95,1200,fork hanging_piece,https://lichess.org/ghi,\n' >> "$PUZZLE_CSV"

TEST_DB="$SMOKE_TMP/test.db"

echo "Importing 3 synthetic puzzles from $PUZZLE_CSV..."

CHESS_COACH_DB="$TEST_DB" python -c "
import sys, os
sys.path.insert(0, '$ROOT/apps/api')
os.environ['CHESS_COACH_DB'] = '$TEST_DB'

from app.db import init_db
init_db()

from app.import_puzzles import import_puzzles
n = import_puzzles(source='$PUZZLE_CSV', limit=None)
assert n == 3, 'expected 3, got %d' % n

import sqlite3, json
conn = sqlite3.connect('$TEST_DB')
rows = conn.execute('SELECT id, themes FROM puzzles ORDER BY id').fetchall()
assert len(rows) == 3, 'expected 3 rows in DB, got %d' % len(rows)
themes = json.loads(rows[0][1])
assert len(themes) > 0, 'themes should not be empty'
print('OK — 3 puzzles inserted, themes: %s' % themes)
conn.close()
"

echo "Smoke test passed."
