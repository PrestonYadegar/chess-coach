"""
Import Lichess open puzzle CSV into the puzzles table.

Usage:
    python -m app.import_puzzles [--limit N] [--file PATH]

If --file is omitted the script streams directly from the Lichess URL.
The Lichess file is .csv.zst; a plain .csv is also accepted.
"""

import argparse
import csv
import io
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Iterator

from .db import DB_PATH

LICHESS_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
BATCH_SIZE = 500


def _open_stream(path_or_url: str):
    """Return a binary stream for a local file or URL (handles .zst)."""
    is_zst = path_or_url.endswith(".zst")

    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        req = urllib.request.Request(
            path_or_url, headers={"User-Agent": "chess-coach/1.0"}
        )
        raw = urllib.request.urlopen(req)
    else:
        raw = open(path_or_url, "rb")

    if is_zst:
        try:
            import zstandard as zstd
        except ImportError:
            print(
                "ERROR: zstandard package required for .zst files.\n"
                "Run: pip install zstandard",
                file=sys.stderr,
            )
            sys.exit(1)
        dctx = zstd.ZstdDecompressor()
        return dctx.stream_reader(raw)

    return raw


def _iter_puzzles(stream) -> Iterator[tuple]:
    """Yield (id, fen, solution_moves, themes_json, rating, popularity) rows."""
    text_stream = io.TextIOWrapper(stream, encoding="utf-8", newline="")
    reader = csv.DictReader(text_stream)
    for row in reader:
        puzzle_id = row.get("PuzzleId", "").strip()
        fen = row.get("FEN", "").strip()
        moves = row.get("Moves", "").strip()
        themes_raw = row.get("Themes", "").strip()
        rating_raw = row.get("Rating", "").strip()
        pop_raw = row.get("Popularity", "").strip()

        if not puzzle_id or not fen or not moves:
            continue

        themes = json.dumps(themes_raw.split() if themes_raw else [])
        rating = int(rating_raw) if rating_raw.lstrip("-").isdigit() else None
        popularity = int(pop_raw) if pop_raw.lstrip("-").isdigit() else None

        yield (puzzle_id, fen, moves, themes, rating, popularity)


def import_puzzles(source: str = LICHESS_URL, limit: int | None = None) -> int:
    """Download/open source and upsert puzzles; return count inserted/updated."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        stream = _open_stream(source)
        inserted = 0
        batch: list[tuple] = []

        for row in _iter_puzzles(stream):
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                _flush(conn, batch)
                inserted += len(batch)
                batch = []
                print(f"\r  {inserted:,} puzzles imported…", end="", flush=True)
                if limit and inserted >= limit:
                    break

        if batch and not (limit and inserted >= limit):
            _flush(conn, batch)
            inserted += len(batch)

        conn.commit()
        print(f"\r  {inserted:,} puzzles imported.    ")
        return inserted
    finally:
        conn.close()


def _flush(conn: sqlite3.Connection, batch: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO puzzles (id, source, fen, solution_moves, themes, rating, popularity)
        VALUES (?, 'lichess', ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            fen = excluded.fen,
            solution_moves = excluded.solution_moves,
            themes = excluded.themes,
            rating = excluded.rating,
            popularity = excluded.popularity
        """,
        batch,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Lichess puzzle DB")
    parser.add_argument(
        "--file",
        default=None,
        help="Local path to lichess_db_puzzle.csv or .csv.zst (streams from Lichess URL if omitted)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N puzzles (useful for testing)",
    )
    args = parser.parse_args()

    source = args.file or LICHESS_URL
    print(f"Importing puzzles from: {source}")
    if args.limit:
        print(f"  (limit: {args.limit:,})")

    count = import_puzzles(source=source, limit=args.limit)
    print(f"Done. {count:,} puzzles in DB.")


if __name__ == "__main__":
    main()
