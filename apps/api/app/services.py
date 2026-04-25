"""Repo/service layer: plain functions over a sqlite3 connection.

These hold the DB/business logic shared across the FastAPI app. Callers pass
a connection and decide how to signal errors (HTTPException vs ValueError).
"""
import io
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from .motifs_meta import MOTIF_TO_LICHESS


# ── Player existence ──────────────────────────────────────────────────────────

def require_player(conn: sqlite3.Connection, username: str) -> bool:
    """Return True if a player row exists for `username`.

    Callers raise their own HTTPException(404)/ValueError on a False result.
    """
    return conn.execute(
        "SELECT 1 FROM players WHERE username = ?", (username,)
    ).fetchone() is not None


# ── Time-control classification ───────────────────────────────────────────────
# Single source of truth: the increment-aware (base + 40*inc) logic that used to
# live in main.py as `_classify_time_format`. Returns canonical Titlecase labels.
# `time_class()` exposes a lowercase variant for callers that key on lowercase
# (e.g. analyze.py's TIME_CLASSES priority map).

def classify_time_format(tc: Optional[str]) -> str:
    """Classify a Chess.com time_control string into Bullet/Blitz/Rapid/Classical/Daily."""
    if not tc:
        return "Unknown"
    if "/" in tc:
        return "Daily"
    parts = tc.split("+")
    try:
        base_secs = int(parts[0])
    except ValueError:
        return "Unknown"
    inc = int(parts[1]) if len(parts) > 1 else 0
    # Estimated total seconds for ~40 moves (FIDE formula approximation)
    total = base_secs + 40 * inc
    if total < 179:
        return "Bullet"
    if total < 599:
        return "Blitz"
    if total < 1799:
        return "Rapid"
    return "Classical"


def time_class(tc: Optional[str]) -> str:
    """Lowercase accessor for `classify_time_format` (e.g. "blitz", "daily")."""
    return classify_time_format(tc).lower()


# ── Top mistake patterns ──────────────────────────────────────────────────────

def top_patterns_core(
    conn: sqlite3.Connection, username: str
) -> tuple[dict[str, set[int]], dict[str, list]]:
    """Aggregate the player's mistake motifs across all analyzed games.

    Returns (games_per_motif, examples) where games_per_motif[tag] is the set of
    game ids the tag appeared in, and examples[tag] is up to 3 example FENs (one
    per game, in most-recent-game-first order).

    Note: the main.py /patterns endpoint applies extra per-color and filter logic
    inline and is NOT routed through here.
    """
    rows = conn.execute(
        "SELECT a.game_id, a.fen, a.motif_tags"
        " FROM analyses a JOIN games g ON g.id = a.game_id"
        " WHERE g.player_username = ?"
        "   AND a.classification IN ('blunder', 'mistake', 'inaccuracy')"
        " ORDER BY a.game_id DESC",
        (username,),
    ).fetchall()

    games_per_motif: dict[str, set[int]] = defaultdict(set)
    examples: dict[str, list] = defaultdict(list)

    for r in rows:
        game_id = r["game_id"]
        if not r["motif_tags"]:
            continue
        try:
            tags = json.loads(r["motif_tags"])
        except (json.JSONDecodeError, TypeError):
            continue
        for tag in tags:
            already = game_id in games_per_motif[tag]
            games_per_motif[tag].add(game_id)
            if not already and len(examples[tag]) < 3:
                examples[tag].append(r["fen"])

    return games_per_motif, examples


# ── Drill selection ───────────────────────────────────────────────────────────

def pick_target_motif(
    conn: sqlite3.Connection,
    username: str,
    *,
    own_moves_only: bool,
) -> Optional[str]:
    """Pick the player's most frequent mistake motif (limited to motifs we have
    Lichess themes for), scanning the 500 most recent mistake plies.

    When `own_moves_only` is True, only the player's own moves are counted
    (even ply = White).
    """
    cols = "a.motif_tags, a.ply, g.white" if own_moves_only else "a.motif_tags"
    mistake_rows = conn.execute(
        f"SELECT {cols} FROM analyses a"
        " JOIN games g ON g.id = a.game_id"
        " WHERE g.player_username = ?"
        "   AND a.motif_tags IS NOT NULL"
        "   AND a.classification IN ('blunder', 'mistake', 'inaccuracy')"
        " ORDER BY a.game_id DESC LIMIT 500",
        (username,),
    ).fetchall()
    counts: dict[str, int] = defaultdict(int)
    for mr in mistake_rows:
        if own_moves_only:
            player_is_white = (mr["white"] or "").strip().lower() == username
            if ((mr["ply"] % 2) == 0) != player_is_white:
                continue
        try:
            tags = json.loads(mr["motif_tags"])
        except (json.JSONDecodeError, TypeError):
            continue
        for t in tags:
            if t in MOTIF_TO_LICHESS:
                counts[t] += 1
    return max(counts, key=lambda m: counts[m]) if counts else None


def _fetch_lichess_batch(angle: str, nb: int = 50) -> list[dict]:
    """Fetch up to `nb` puzzles from the Lichess batch API for one theme angle.

    Walks each game's PGN to derive the puzzle FEN at initialPly. Returns an
    empty list on any network or parse error (fail-open so the drill endpoint
    degrades to own-game positions rather than crashing).
    """
    import chess.pgn
    import httpx

    url = f"https://lichess.org/api/puzzle/batch/{angle}?nb={nb}"
    try:
        resp = httpx.get(url, headers={"User-Agent": "chess-coach/1.0"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results: list[dict] = []
    for entry in data.get("puzzles", []):
        puzzle = entry.get("puzzle", {})
        game = entry.get("game", {})
        puzzle_id = puzzle.get("id")
        solution = puzzle.get("solution", [])
        themes = puzzle.get("themes", [])
        rating = puzzle.get("rating")
        initial_ply = puzzle.get("initialPly", 0)
        pgn_str = game.get("pgn", "")
        if not puzzle_id or not solution or not pgn_str:
            continue
        try:
            game_obj = chess.pgn.read_game(io.StringIO(pgn_str))
            if game_obj is None:
                continue
            board = game_obj.board()
            for move in list(game_obj.mainline_moves())[:initial_ply]:
                board.push(move)
            fen = board.fen()
        except Exception:
            continue
        results.append({
            "id": puzzle_id,
            "fen": fen,
            "solution_moves": " ".join(solution),
            "themes_json": json.dumps(themes),
            "rating": rating,
        })
    return results


def ensure_lichess_puzzles(
    conn: sqlite3.Connection,
    username: str,
    motif: str,
    *,
    min_unused: int = 10,
    fetch_per_angle: int = 50,
) -> None:
    """Guarantee at least `min_unused` un-attempted Lichess puzzles for `motif`.

    Counts the puzzles in the DB that `username` has not yet tried. If below the
    threshold, fetches a fresh batch from the Lichess API (one call per theme
    angle) and upserts the results. Already-known puzzle IDs are silently skipped.
    """
    themes = MOTIF_TO_LICHESS.get(motif)
    if not themes:
        return

    like_clauses = " OR ".join("p.themes LIKE ?" for _ in themes)
    like_params = [f"%{t}%" for t in themes]

    unused: int = conn.execute(
        f"SELECT COUNT(*) FROM puzzles p"
        f" WHERE ({like_clauses})"
        f"   AND NOT EXISTS ("
        f"     SELECT 1 FROM puzzle_attempts pa"
        f"     WHERE pa.puzzle_id = p.id AND pa.username = ?"
        f"   )",
        like_params + [username],
    ).fetchone()[0]

    if unused >= min_unused:
        return

    for theme in themes:
        rows = _fetch_lichess_batch(theme, nb=fetch_per_angle)
        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO puzzles"
                " (id, source, fen, solution_moves, themes, rating)"
                " VALUES (?, 'lichess', ?, ?, ?, ?)",
                (row["id"], row["fen"], row["solution_moves"], row["themes_json"], row["rating"]),
            )


def lichess_puzzles_for_motif(
    conn: sqlite3.Connection,
    motif: str,
    limit: int,
    *,
    username: Optional[str] = None,
) -> list[sqlite3.Row]:
    """Random Lichess puzzles whose themes match `motif`'s Lichess keywords.

    When `username` is provided, puzzles the user has already attempted are
    excluded (call `ensure_lichess_puzzles` first to keep the supply topped up).
    """
    themes = MOTIF_TO_LICHESS[motif]
    like_clauses = " OR ".join("p.themes LIKE ?" for _ in themes)
    like_params = [f"%{t}%" for t in themes]

    attempted_filter = ""
    attempted_params: list = []
    if username:
        attempted_filter = (
            " AND NOT EXISTS ("
            "   SELECT 1 FROM puzzle_attempts pa"
            "   WHERE pa.puzzle_id = p.id AND pa.username = ?"
            " )"
        )
        attempted_params = [username]

    return conn.execute(
        f"SELECT p.id, p.fen, p.solution_moves, p.themes FROM puzzles p"
        f" WHERE ({like_clauses}){attempted_filter}"
        f" ORDER BY RANDOM() LIMIT ?",
        like_params + attempted_params + [limit],
    ).fetchall()


def own_game_blunders_filter(
    username: str, motif: Optional[str]
) -> tuple[str, list]:
    """Build the shared WHERE clause + params for own-game pre-blunder selection.

    Returns (where_sql, params). Callers supply their own SELECT/FROM (they need
    different projections — e.g. the web /drill endpoint joins the previous ply
    for eval_cp_before) and append their own ORDER BY / LIMIT params.
    """
    own_where = "g.player_username = ? AND a.classification IN ('blunder', 'mistake')"
    own_params: list = [username]
    if motif:
        own_where += " AND a.motif_tags LIKE ?"
        own_params.append(f"%{motif}%")
    return own_where, own_params


# ── Puzzle attempts ───────────────────────────────────────────────────────────

def record_attempt(
    conn: sqlite3.Connection, puzzle_id: str, username: str, solved: bool
) -> dict:
    """Insert a puzzle attempt and return the created record (incl. timestamp)."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO puzzle_attempts (puzzle_id, username, solved, attempted_at)"
        " VALUES (?, ?, ?, ?)",
        (puzzle_id, username, int(solved), now),
    )
    return {
        "id": cur.lastrowid,
        "puzzle_id": puzzle_id,
        "username": username,
        "solved": solved,
        "attempted_at": now,
    }
