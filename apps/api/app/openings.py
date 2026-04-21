"""Lichess opening-book classifier.

Reads the vendored TSVs in `apps/api/data/openings/` once and builds an
in-memory dict keyed by a tuple of SAN moves. Classification walks a game's
SAN move list and returns the deepest matching entry.
"""

import os
from functools import lru_cache

import chess
import chess.pgn

_OPENINGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "openings"
)
_FILES = ("a.tsv", "b.tsv", "c.tsv", "d.tsv", "e.tsv")


def _pgn_to_san_tuple(pgn_moves: str) -> tuple[str, ...]:
    """`'1. e4 e5 2. Nf3'` -> `('e4', 'e5', 'Nf3')`."""
    out = []
    for tok in pgn_moves.split():
        # Skip move-number tokens like "1." or "12..."
        if tok.endswith("."):
            continue
        # Skip result tokens just in case (TSVs don't include them, but cheap)
        if tok in ("1-0", "0-1", "1/2-1/2", "*"):
            continue
        out.append(tok)
    return tuple(out)


@lru_cache(maxsize=1)
def _book() -> dict[tuple[str, ...], tuple[str, str]]:
    """Returns {san_tuple: (eco, name)}. Cached for process lifetime."""
    book: dict[tuple[str, ...], tuple[str, str]] = {}
    for fname in _FILES:
        path = os.path.join(_OPENINGS_DIR, fname)
        with open(path, encoding="utf-8") as f:
            header = f.readline()
            assert header.startswith("eco\tname\tpgn"), f"unexpected header in {fname}"
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 3:
                    continue
                eco, name, pgn_moves = parts
                key = _pgn_to_san_tuple(pgn_moves)
                if key:
                    book[key] = (eco, name)
    return book


def classify_game(game: chess.pgn.Game) -> tuple[str | None, str | None, int]:
    """Walk the mainline; return (eco, name, ply_depth) of the deepest book hit.

    Returns (None, None, 0) if no opening matches (e.g. an illegal/garbled game,
    or a fairy variant the book doesn't cover).
    """
    book = _book()
    board = game.board()
    sans: list[str] = []
    best: tuple[str | None, str | None, int] = (None, None, 0)
    # The deepest line in the Lichess book is ~30 plies; cap to bound work.
    MAX_PLY = 40
    for move in game.mainline_moves():
        if len(sans) >= MAX_PLY:
            break
        san = board.san(move)
        board.push(move)
        sans.append(san)
        hit = book.get(tuple(sans))
        if hit is not None:
            best = (hit[0], hit[1], len(sans))
    return best
