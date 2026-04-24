"""Persistent Stockfish singleton + position-keyed engine_lines cache.

All engine analysis in the app routes through `evaluate_position()`.
Never recomputes what is already cached at >= the requested depth/breadth.
"""
import json
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

import chess
import chess.engine

from .constants import DEFAULT_DEPTH, ENGINE_HASH_MB, ENGINE_THREADS
from .db import get_conn

STOCKFISH_PATH = shutil.which("stockfish")
STOCKFISH_NOT_FOUND_MSG = "stockfish not found on PATH. Install it: brew install stockfish"


def open_configured_engine(path: Optional[str] = None) -> chess.engine.SimpleEngine:
    """Spawn a Stockfish engine and apply the shared Threads/Hash config.

    Raises RuntimeError if Stockfish is not on PATH. The configure() call is
    best-effort (some builds reject options), matching prior behavior.
    """
    path = path or STOCKFISH_PATH
    if path is None:
        raise RuntimeError(STOCKFISH_NOT_FOUND_MSG)
    engine = chess.engine.SimpleEngine.popen_uci(path)
    try:
        engine.configure({"Threads": ENGINE_THREADS, "Hash": ENGINE_HASH_MB})
    except chess.engine.EngineError:
        pass
    return engine


# ── Singleton engine ──────────────────────────────────────────────────────────

_engine: Optional[chess.engine.SimpleEngine] = None
_engine_lock = threading.Lock()


def _get_engine() -> chess.engine.SimpleEngine:
    global _engine
    if _engine is not None:
        return _engine
    _engine = open_configured_engine()
    return _engine


def shutdown_engine() -> None:
    """Close the singleton cleanly (call from app shutdown)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            try:
                _engine.quit()
            except Exception:
                pass
            _engine = None


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _read_cache(conn: sqlite3.Connection, fen: str, multipv: int, depth: int):
    """Return cached rows if we have >= multipv ranks at >= depth, else None."""
    rows = conn.execute(
        "SELECT multipv_rank, move_uci, eval_cp, mate, pv, depth"
        " FROM engine_lines WHERE fen = ? ORDER BY multipv_rank",
        (fen,),
    ).fetchall()
    if len(rows) < multipv:
        return None
    # Check all requested ranks have sufficient depth.
    for r in rows[:multipv]:
        if r["depth"] < depth:
            return None
    return rows[:multipv]


def _upsert_lines(conn: sqlite3.Connection, fen: str, infos: list, depth: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for info in infos:
        rank = info.get("multipv", 1)
        pv = info.get("pv", [])
        move_uci = pv[0].uci() if pv else ""
        pv_json = json.dumps([m.uci() for m in pv])
        score = info["score"].white()
        if score.is_mate():
            eval_cp = None
            mate = score.mate()
        else:
            eval_cp = score.score()
            mate = None
        conn.execute(
            """
            INSERT INTO engine_lines (fen, multipv_rank, move_uci, eval_cp, mate, pv, depth, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fen, multipv_rank) DO UPDATE SET
                move_uci   = excluded.move_uci,
                eval_cp    = excluded.eval_cp,
                mate       = excluded.mate,
                pv         = excluded.pv,
                depth      = excluded.depth,
                computed_at = excluded.computed_at
            WHERE excluded.depth >= engine_lines.depth
            """,
            (fen, rank, move_uci, eval_cp, mate, pv_json, depth, now),
        )


# ── Public API ────────────────────────────────────────────────────────────────

def evaluate_position(
    fen: str,
    depth: int = DEFAULT_DEPTH,
    multipv: int = 1,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Return top-`multipv` candidate lines for `fen` at >= `depth`.

    Reads cache first; runs Stockfish only for missing breadth/depth.
    Thread-safe via a single engine lock.

    Returns list of dicts:
        rank, move_uci, eval_cp (white-POV, None on mate),
        mate (signed mate-in-N, None otherwise), pv (UCI list)
    """
    # Validate FEN.
    try:
        board = chess.Board(fen)
    except ValueError as e:
        raise ValueError(f"invalid FEN: {e}") from e

    own_conn = conn is None
    if own_conn:
        conn = get_conn()

    try:
        cached = _read_cache(conn, fen, multipv, depth)
        if cached is not None:
            return [
                {
                    "rank": r["multipv_rank"],
                    "move_uci": r["move_uci"],
                    "eval_cp": r["eval_cp"],
                    "mate": r["mate"],
                    "pv": json.loads(r["pv"]),
                    "depth": r["depth"],
                }
                for r in cached
            ]

        # Need to compute (or extend).
        with _engine_lock:
            engine = _get_engine()
            limit = chess.engine.Limit(depth=depth)
            infos = engine.analyse(board, limit, multipv=multipv)

        _upsert_lines(conn, fen, infos, depth)
        if own_conn:
            conn.commit()

        # Re-read from cache to get consistent format.
        rows = conn.execute(
            "SELECT multipv_rank, move_uci, eval_cp, mate, pv, depth"
            " FROM engine_lines WHERE fen = ? ORDER BY multipv_rank LIMIT ?",
            (fen, multipv),
        ).fetchall()
        return [
            {
                "rank": r["multipv_rank"],
                "move_uci": r["move_uci"],
                "eval_cp": r["eval_cp"],
                "mate": r["mate"],
                "pv": json.loads(r["pv"]),
                "depth": r["depth"],
            }
            for r in rows
        ]
    finally:
        if own_conn:
            conn.close()
