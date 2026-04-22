"""Stockfish per-ply analysis for a single game."""
import concurrent.futures as cf
import io
import json
import os
import queue as _queue
import shutil
import sqlite3
import threading
from multiprocessing import get_context
from typing import Callable, Iterable, Optional

import chess
import chess.engine
import chess.pgn

from .db import get_conn
from .engine_cache import _read_cache, _upsert_lines
from .motif import compute_phase, encode_tags, tag_motifs_with_details

_PV_MAX_PLIES = 8


STOCKFISH_PATH = shutil.which("stockfish")
DEFAULT_DEPTH = 18

# Time-class buckets, ordered longest → shortest. Used for prioritizing which
# games to analyze first when a player has thousands of games.
TIME_CLASSES = ("classical", "rapid", "blitz", "bullet", "daily", "unknown")
_CLASS_PRIORITY = {tc: i for i, tc in enumerate(TIME_CLASSES)}


def _time_class(tc: Optional[str]) -> str:
    """Map a chess.com `time_control` string ("60", "180+1", "1/259200") to a class."""
    if not tc:
        return "unknown"
    if "/" in tc:
        return "daily"
    base_str = tc.split("+", 1)[0]
    try:
        base = int(base_str)
    except ValueError:
        return "unknown"
    if base < 180:
        return "bullet"
    if base < 600:
        return "blitz"
    if base < 1800:
        return "rapid"
    return "classical"


def _classify(eval_before_cp: Optional[int], eval_after_cp: Optional[int]) -> str:
    if eval_before_cp is None or eval_after_cp is None:
        return "good"
    swing = eval_before_cp - eval_after_cp
    if swing >= 200:
        return "blunder"
    if swing >= 100:
        return "mistake"
    if swing >= 50:
        return "inaccuracy"
    return "good"


def _make_engine() -> chess.engine.SimpleEngine:
    if STOCKFISH_PATH is None:
        raise RuntimeError(
            "stockfish not found on PATH. Install it: brew install stockfish"
        )
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    try:
        engine.configure({"Threads": 1, "Hash": 128})
    except chess.engine.EngineError:
        pass
    return engine


def _row_to_info(r: sqlite3.Row) -> dict:
    """Rebuild an engine.analyse-shaped info dict from a cached engine_lines row.

    Stored scores are white-POV (see engine_cache._upsert_lines), so the PovScore
    is reconstructed relative to WHITE; callers re-derive .white()/.pov(mover).
    """
    if r["mate"] is not None:  # mate 0 (#0) is falsy — must test `is not None`
        score = chess.engine.PovScore(chess.engine.Mate(r["mate"]), chess.WHITE)
    else:
        score = chess.engine.PovScore(chess.engine.Cp(r["eval_cp"]), chess.WHITE)
    pv = [chess.Move.from_uci(u) for u in json.loads(r["pv"])]
    return {"score": score, "pv": pv, "multipv": r["multipv_rank"]}


def _analyse_cached(
    board: chess.Board,
    engine: chess.engine.SimpleEngine,
    depth: int,
    multipv: int,
    conn: Optional[sqlite3.Connection],
) -> list[dict]:
    """engine.analyse with a read-through / write-back engine_lines cache.

    On a cache hit (>= multipv ranks at >= depth) returns reconstructed info
    dicts without touching Stockfish. Falls back to engine.analyse + upsert on a
    miss, or runs uncached when conn is None. Callers commit (`conn`).
    """
    fen = board.fen()
    if conn is not None:
        cached = _read_cache(conn, fen, multipv, depth)
        if cached is not None:
            return [_row_to_info(r) for r in cached]
    infos = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=multipv)
    if conn is not None:
        _upsert_lines(conn, fen, infos, depth)
    return infos


def _analyze_pgn_rows(
    game_id: int,
    pgn_text: str,
    engine: chess.engine.SimpleEngine,
    depth: int,
    conn: Optional[sqlite3.Connection] = None,
    progress_cb: Optional[Callable[[int, int, int], None]] = None,
) -> list[tuple]:
    """Analysis: PGN → list of analysis row tuples.

    Engine calls route through the engine_lines cache when `conn` is given.
    `progress_cb(game_id, ply_index, total_plies)` fires after each ply.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError(f"could not parse PGN for game {game_id}")

    board = game.board()
    moves = list(game.mainline_moves())

    # multipv=2 gives us the second-best line, needed for the "only-move missed"
    # detector. Adds ~1.5–2× engine cost per ply but enables sharper tagging.
    infos_before = _analyse_cached(board, engine, depth, 2, conn)

    rows: list[tuple] = []

    for ply_index, move in enumerate(moves):
        fen_before = board.fen()
        played_move_uci = move.uci()
        mover = board.turn

        best_info = infos_before[0]
        score_before_white = best_info["score"].white()
        score_before_mover = best_info["score"].pov(mover)
        second_info = infos_before[1] if len(infos_before) > 1 else None
        second_score_mover = (
            second_info["score"].pov(mover) if second_info is not None else None
        )

        if score_before_white.is_mate():
            eval_before_cp = None
            is_mate_before = True
        else:
            eval_before_cp = score_before_white.score()
            is_mate_before = False

        pv = best_info.get("pv")
        best_move_uci = pv[0].uci() if pv else played_move_uci
        pv_uci_json = json.dumps([m.uci() for m in (pv or [])[:_PV_MAX_PLIES]])

        phase = compute_phase(board)
        board.push(move)

        infos_after = _analyse_cached(board, engine, depth, 2, conn)
        best_after = infos_after[0]
        score_after_white = best_after["score"].white()
        # Mover's POV after the move: opponent is to move, so flip back.
        score_after_mover = best_after["score"].pov(mover)

        if score_after_white.is_mate():
            eval_after_cp = None
            is_mate_after = True
        else:
            eval_after_cp = score_after_white.score()
            is_mate_after = False

        is_white_move = (mover == chess.WHITE)
        if is_white_move:
            before_player = eval_before_cp
            after_player = eval_after_cp
        else:
            before_player = (-eval_before_cp) if eval_before_cp is not None else None
            after_player = (-eval_after_cp) if eval_after_cp is not None else None

        if is_mate_before != is_mate_after or (
            is_mate_before and is_mate_after and before_player != after_player
        ):
            classification = "blunder"
        else:
            classification = _classify(before_player, after_player)

        best_move_obj = chess.Move.from_uci(best_move_uci) if best_move_uci else None
        board_for_tags = chess.Board(fen_before)
        motif_list, motif_details = tag_motifs_with_details(
            board_for_tags,
            move,
            best_move_obj,
            classification,
            score_before=score_before_mover,
            score_after=score_after_mover,
            second_pv_score=second_score_mover,
            phase=phase,
        )
        motif_tags_json = encode_tags(motif_list)
        motif_details_json = json.dumps(motif_details) if motif_details else None

        rows.append((
            game_id,
            ply_index,
            fen_before,
            best_move_uci,
            played_move_uci,
            eval_after_cp,
            classification,
            motif_tags_json,
            phase,
            pv_uci_json,
            motif_details_json,
        ))

        # Carry forward: the eval/pv we just computed for the resulting position
        # IS the "before" state for the next ply.
        infos_before = infos_after

        if progress_cb is not None:
            progress_cb(game_id, ply_index, len(moves))

    return rows


def _write_rows(conn: sqlite3.Connection, game_id: int, rows: list[tuple]) -> int:
    conn.execute("DELETE FROM analyses WHERE game_id = ?", (game_id,))
    conn.executemany(
        "INSERT OR REPLACE INTO analyses"
        " (game_id, ply, fen, best_move, played_move, eval_cp, classification,"
        "  motif_tags, phase, pv, motif_details)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def analyze_game(game_id: int, conn: sqlite3.Connection, depth: int = DEFAULT_DEPTH) -> dict:
    row = conn.execute("SELECT pgn FROM games WHERE id = ?", (game_id,)).fetchone()
    if not row:
        raise ValueError(f"game {game_id} not found")

    with _make_engine() as engine:
        rows = _analyze_pgn_rows(game_id, row["pgn"], engine, depth, conn=conn)

    plies = _write_rows(conn, game_id, rows)
    return {"game_id": game_id, "plies_analyzed": plies}


# ── Parallel worker plumbing ─────────────────────────────────────────────────
# Each worker process holds its own long-lived Stockfish engine in a module
# global, initialized once on pool startup. Spawn start method is used so the
# initializer runs in a clean interpreter (asyncio + fork is fragile on macOS).

_WORKER_ENGINE: Optional[chess.engine.SimpleEngine] = None


def _worker_init(stockfish_path: str) -> None:
    global _WORKER_ENGINE
    _WORKER_ENGINE = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    try:
        _WORKER_ENGINE.configure({"Threads": 1, "Hash": 128})
    except chess.engine.EngineError:
        pass


def _worker_analyze(game_id: int, pgn_text: str, depth: int, progress_q=None):
    conn = None
    try:
        conn = get_conn()

        def cb(gid: int, ply: int, total: int) -> None:
            if progress_q is not None:
                try:
                    progress_q.put_nowait((gid, ply, total))
                except Exception:
                    pass  # never let progress reporting break analysis

        rows = _analyze_pgn_rows(
            game_id, pgn_text, _WORKER_ENGINE, depth, conn=conn, progress_cb=cb
        )
        conn.commit()  # flush this game's engine_lines cache writes
        return ("ok", game_id, rows)
    except Exception as e:
        return ("err", game_id, str(e))
    finally:
        if conn is not None:
            conn.close()


def _select_games(
    conn: sqlite3.Connection,
    username: str,
    only_unanalyzed: bool,
    time_classes: Optional[Iterable[str]],
    limit: int,
) -> list[sqlite3.Row]:
    """Return games to analyze, ordered longest-time-control first then most-recent."""
    if only_unanalyzed:
        sql = (
            "SELECT g.id, g.white, g.black, g.time_control, g.pgn, g.played_at"
            " FROM games g"
            " LEFT JOIN (SELECT DISTINCT game_id FROM analyses) a ON a.game_id = g.id"
            " WHERE g.player_username = ? AND a.game_id IS NULL"
        )
    else:
        sql = (
            "SELECT id, white, black, time_control, pgn, played_at"
            " FROM games g WHERE player_username = ?"
        )
    rows = conn.execute(sql, (username,)).fetchall()

    allowed = set(time_classes) if time_classes else None
    decorated = []
    for r in rows:
        cls = _time_class(r["time_control"])
        if allowed and cls not in allowed:
            continue
        decorated.append((_CLASS_PRIORITY.get(cls, 99), r["played_at"] or "", r, cls))

    # Stable two-pass: within each class, most recent first; then class priority.
    decorated.sort(key=lambda t: t[1], reverse=True)
    decorated.sort(key=lambda t: t[0])

    return [d[2] for d in decorated[:limit]]


def analyze_player_games_events(
    username: str,
    conn: sqlite3.Connection,
    depth: int = 14,
    limit: int = 50,
    only_unanalyzed: bool = True,
    workers: int = 1,
    time_classes: Optional[Iterable[str]] = None,
):
    """Generator yielding SSE-shaped progress events while analyzing a batch.

    workers > 1 fans out across processes, each with its own Stockfish instance.
    Games are ordered by time-class priority (classical → rapid → blitz → bullet
    → daily) and then by most recent first.
    """
    if STOCKFISH_PATH is None:
        yield {
            "type": "error",
            "message": "stockfish not found on PATH. Install it: brew install stockfish",
        }
        return

    player_row = conn.execute(
        "SELECT username FROM players WHERE username = ?", (username,)
    ).fetchone()
    if not player_row:
        yield {"type": "error", "message": f"player not found: {username}"}
        return

    rows = _select_games(conn, username, only_unanalyzed, time_classes, limit)
    total = len(rows)
    yield {
        "type": "start",
        "username": username,
        "games": total,
        "depth": depth,
        "workers": workers,
    }

    if total == 0:
        yield {"type": "done", "analyzed": 0, "total": 0}
        return

    labels = {r["id"]: f"{r['white']} vs {r['black']}" for r in rows}
    analyzed = 0
    plies_total = 0
    plies_done = 0  # live counter for per-ply progress (workers > 1)

    def _ply_event(game_id: int, ply: int, game_plies: int):
        return {
            "type": "ply_progress",
            "game_id": game_id,
            "ply": ply,
            "game_plies": game_plies,
            "plies_done": plies_done,
            "games_total": total,
            "label": labels.get(game_id, ""),
        }

    def _emit_done(game_id: int, plies: int, i: int):
        nonlocal analyzed, plies_total
        analyzed += 1
        plies_total += plies
        return {
            "type": "game_done",
            "index": i,
            "games_total": total,
            "game_id": game_id,
            "label": labels.get(game_id, ""),
            "plies": plies,
            "analyzed": analyzed,
            "plies_total": plies_total,
        }

    if workers <= 1:
        # Single-process path: cache-enabled, per-game progress (no per-ply, since
        # a callback can't yield from this synchronous loop). The default batch
        # uses workers > 1, which streams per-ply below.
        with _make_engine() as engine:
            for i, r in enumerate(rows):
                gid = r["id"]
                try:
                    analysis_rows = _analyze_pgn_rows(gid, r["pgn"], engine, depth, conn=conn)
                    plies = _write_rows(conn, gid, analysis_rows)
                    conn.commit()
                    yield _emit_done(gid, plies, i)
                except Exception as e:
                    yield {
                        "type": "game_error",
                        "index": i,
                        "games_total": total,
                        "game_id": gid,
                        "message": str(e),
                    }
    else:
        ctx = get_context("spawn")
        # Cap workers at min(requested, cores, games).
        max_w = max(1, min(workers, (os.cpu_count() or 2), total))
        manager = ctx.Manager()
        progress_q = manager.Queue()
        pool = cf.ProcessPoolExecutor(
            max_workers=max_w,
            mp_context=ctx,
            initializer=_worker_init,
            initargs=(STOCKFISH_PATH,),
        )
        futures = {
            pool.submit(_worker_analyze, r["id"], r["pgn"], depth, progress_q): (i, r["id"])
            for i, r in enumerate(rows)
        }

        def _drain_progress():
            """Yield a ply_progress event for every queued ply update (non-blocking)."""
            nonlocal plies_done
            while True:
                try:
                    gid, ply, game_plies = progress_q.get_nowait()
                except _queue.Empty:
                    return
                except (EOFError, OSError):
                    return  # manager torn down
                plies_done += 1
                yield _ply_event(gid, ply, game_plies)

        try:
            pending = set(futures)
            while pending:
                yield from _drain_progress()
                done, pending = cf.wait(
                    pending, timeout=0.25, return_when=cf.FIRST_COMPLETED
                )
                for fut in done:
                    i, gid = futures[fut]
                    try:
                        status, ret_gid, payload = fut.result()
                    except Exception as e:
                        yield {
                            "type": "game_error",
                            "index": i,
                            "games_total": total,
                            "game_id": gid,
                            "message": str(e),
                        }
                        continue
                    if status == "ok":
                        plies = _write_rows(conn, ret_gid, payload)
                        conn.commit()
                        yield _emit_done(ret_gid, plies, i)
                    else:
                        yield {
                            "type": "game_error",
                            "index": i,
                            "games_total": total,
                            "game_id": ret_gid,
                            "message": str(payload),
                        }
            # Final drain for plies enqueued after the last wait() returned.
            yield from _drain_progress()
        finally:
            try:
                manager.shutdown()
            except Exception:
                pass
            # On client disconnect (GeneratorExit) or normal completion, drop any
            # queued work AND terminate the worker processes so Stockfish doesn't
            # keep burning CPU. Default shutdown(wait=True) would block for every
            # running future to finish — useless if the user clicked Stop.
            for f in futures:
                f.cancel()
            for p in list(pool._processes.values()):
                try:
                    p.terminate()
                except Exception:
                    pass
            pool.shutdown(wait=False, cancel_futures=True)

    yield {
        "type": "done",
        "analyzed": analyzed,
        "total": total,
        "plies_total": plies_total,
    }
