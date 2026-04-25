import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import chess
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx

from .analyze import analyze_game
from .chess_utils import format_lines, uci_to_san
from .chesscom import sync_player_games, sync_player_games_events
from .constants import CHAT_DEPTH, DEFAULT_DEPTH, JOB_DEFAULT_DEPTH
from .db import conn_ctx, init_db
from .engine_cache import evaluate_position, shutdown_engine
from .jobs import active_job, active_job_for, get_job, start_job, stream as stream_job
from .llm import chat as llm_chat, narrative as llm_narrative, get_llm_settings, save_llm_settings
from .motifs_meta import MOTIF_TO_LICHESS as _MOTIF_TO_LICHESS
from .openings import line_for_name
from .services import (
    classify_time_format as _classify_time_format,
    ensure_lichess_puzzles,
    lichess_puzzles_for_motif,
    own_game_blunders_filter,
    pick_target_motif,
    record_attempt,
    require_player,
)


def _get_settings(conn, username: str) -> dict:
    """Per-player auto-analyze settings, with defaults if no row exists."""
    row = conn.execute(
        "SELECT auto_analyze, auto_depth, auto_workers, auto_batch, auto_time_format"
        " FROM player_settings WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None:
        return {"auto_analyze": True, "auto_depth": 14, "auto_workers": 4, "auto_batch": 0, "auto_time_format": None}
    return {
        "auto_analyze": bool(row["auto_analyze"]),
        "auto_depth": int(row["auto_depth"]),
        "auto_workers": int(row["auto_workers"]),
        "auto_batch": int(row["auto_batch"]) if row["auto_batch"] is not None else 0,
        "auto_time_format": row["auto_time_format"],
    }


def _count_unanalyzed(conn, username: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM games g"
        " WHERE g.player_username = ?"
        "   AND NOT EXISTS (SELECT 1 FROM analyses a WHERE a.game_id = g.id)",
        (username,),
    ).fetchone()[0]


def _maybe_autostart_analyze(username: str) -> Optional[dict]:
    """After a sync, kick off background analysis if the player has it enabled,
    there are unanalyzed games, and no job is already running. Returns the job
    snapshot if one was started, else None. Never raises into the caller."""
    try:
        with conn_ctx() as conn:
            settings = _get_settings(conn, username)
            if not settings["auto_analyze"]:
                return None
            if _count_unanalyzed(conn, username) == 0:
                return None
        if active_job_for(username):
            return None
        job_params: dict = {
            "depth": settings["auto_depth"],
            "limit": None if settings["auto_batch"] == 0 else settings["auto_batch"],
            "only_unanalyzed": True,
            "workers": settings["auto_workers"],
        }
        if settings.get("auto_time_format"):
            job_params["time_classes"] = [settings["auto_time_format"]]
        job = start_job(username, job_params)
        return job.snapshot
    except Exception:
        return None

app = FastAPI(title="chess-coach api", version="0.0.0")

# Local-first app: web at :3000 talks to api at :8000 cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.on_event("shutdown")
def _shutdown() -> None:
    shutdown_engine()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/players")
def list_players() -> dict:
    """All players that have been synced, with game + analysis counts."""
    with conn_ctx() as conn:
        rows = conn.execute(
            "SELECT p.username, p.last_synced_at,"
            "       COUNT(DISTINCT g.id) AS games,"
            "       COUNT(DISTINCT a.game_id) AS analyzed"
            " FROM players p"
            " LEFT JOIN games g ON g.player_username = p.username"
            " LEFT JOIN analyses a ON a.game_id = g.id"
            " GROUP BY p.username"
            " ORDER BY p.last_synced_at DESC NULLS LAST, p.username"
        ).fetchall()
    return {"players": [dict(r) for r in rows]}


@app.post("/players/{username}/sync")
def sync_player(username: str) -> dict:
    username = username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    try:
        with conn_ctx() as conn:
            result = sync_player_games(username, conn)
        job = _maybe_autostart_analyze(username)
        if job:
            result["analyze_job"] = {"id": job["id"], "status": job["status"]}
        return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"chess.com error: {e.response.text[:200]}",
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"chess.com fetch failed: {e}")


@app.get("/players/{username}/sync/stream")
def sync_player_stream(username: str, full: bool = False) -> StreamingResponse:
    """Server-Sent Events: one event per archive ingested.

    By default this is incremental — only months at/after the last sync are
    re-fetched. Pass `?full=1` to re-ingest every archive."""
    username = username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="username required")

    def event_source():
        try:
            synced_ok = False
            with conn_ctx() as conn:
                for event in sync_player_games_events(username, conn, full=full):
                    if event.get("type") == "done":
                        synced_ok = True
                    yield f"data: {json.dumps(event)}\n\n"
            # After a successful sync, optionally kick off background analysis
            # and tell the client so its job widget can attach immediately.
            if synced_ok:
                job = _maybe_autostart_analyze(username)
                if job:
                    yield f"data: {json.dumps({'type': 'analyze_started', 'job_id': job['id'], 'username': username})}\n\n"
        except httpx.HTTPStatusError as e:
            payload = {
                "type": "error",
                "status": e.response.status_code,
                "message": f"chess.com error: {e.response.text[:200]}",
            }
            yield f"data: {json.dumps(payload)}\n\n"
        except httpx.HTTPError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'chess.com fetch failed: {e}'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering if any
        },
    )


class AnalyzeJobIn(BaseModel):
    depth: int = JOB_DEFAULT_DEPTH
    limit: Optional[int] = None   # None = all unanalyzed games
    only_unanalyzed: bool = True
    workers: int = 1
    time_classes: Optional[list[str]] = None


@app.post("/players/{username}/analyze", status_code=201)
def start_analyze_job(username: str, body: AnalyzeJobIn) -> dict:
    """Kick off a background analysis job. Returns the job snapshot.

    The job runs detached from this request; clients can poll /jobs/{id} or
    tail /jobs/{id}/stream. Closing the client does NOT stop the job.
    """
    username = username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    with conn_ctx() as conn:
        if not require_player(conn, username):
            raise HTTPException(status_code=404, detail="player not found")
    params = {
        "depth": body.depth,
        "limit": body.limit,
        "only_unanalyzed": body.only_unanalyzed,
        "workers": body.workers,
        "time_classes": body.time_classes,
    }
    try:
        job = start_job(username, params)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return job.snapshot


@app.get("/jobs/active")
def get_active_job() -> dict:
    """The most recent running job across all players (powers the global
    floating progress widget). 404 when nothing is running."""
    job = active_job()
    if not job:
        raise HTTPException(status_code=404, detail="no active job")
    return job.snapshot


@app.get("/jobs/{job_id}")
def get_job_snapshot(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job.snapshot


@app.post("/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    job.cancel.set()
    return {"id": job.id, "status": "stopping"}


@app.get("/jobs/{job_id}/stream")
def stream_job_endpoint(job_id: str) -> StreamingResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    def event_source():
        for event in stream_job(job):
            if event.get("type") == "heartbeat":
                yield ": heartbeat\n\n"
            else:
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/players/{username}/jobs/active")
def get_active_job_for_player(username: str) -> dict:
    username = username.strip().lower()
    job = active_job_for(username)
    if not job:
        raise HTTPException(status_code=404, detail="no active job")
    return job.snapshot


class PlayerSettingsIn(BaseModel):
    auto_analyze: Optional[bool] = None
    auto_depth: Optional[int] = None
    auto_workers: Optional[int] = None
    auto_batch: Optional[int] = None
    auto_time_format: Optional[str] = None


@app.get("/players/{username}/settings")
def get_player_settings(username: str) -> dict:
    username = username.strip().lower()
    with conn_ctx() as conn:
        return _get_settings(conn, username)


@app.put("/players/{username}/settings")
def update_player_settings(username: str, body: PlayerSettingsIn) -> dict:
    username = username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    with conn_ctx() as conn:
        cur = _get_settings(conn, username)
        auto_analyze = cur["auto_analyze"] if body.auto_analyze is None else body.auto_analyze
        auto_depth = cur["auto_depth"] if body.auto_depth is None else body.auto_depth
        auto_workers = cur["auto_workers"] if body.auto_workers is None else body.auto_workers
        auto_batch = cur["auto_batch"] if body.auto_batch is None else body.auto_batch
        auto_time_format = cur["auto_time_format"] if body.auto_time_format is None else body.auto_time_format
        # sentinel "" means "clear"
        if auto_time_format == "":
            auto_time_format = None
        auto_depth = max(1, min(30, int(auto_depth)))
        auto_workers = max(1, min(16, int(auto_workers)))
        auto_batch = max(0, min(1000, int(auto_batch)))
        conn.execute(
            "INSERT INTO player_settings (username, auto_analyze, auto_depth, auto_workers, auto_batch, auto_time_format)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(username) DO UPDATE SET"
            "   auto_analyze = excluded.auto_analyze,"
            "   auto_depth = excluded.auto_depth,"
            "   auto_workers = excluded.auto_workers,"
            "   auto_batch = excluded.auto_batch,"
            "   auto_time_format = excluded.auto_time_format",
            (username, 1 if auto_analyze else 0, auto_depth, auto_workers, auto_batch, auto_time_format),
        )
        return {
            "auto_analyze": bool(auto_analyze),
            "auto_depth": auto_depth,
            "auto_workers": auto_workers,
            "auto_batch": auto_batch,
            "auto_time_format": auto_time_format,
        }


@app.get("/players/{username}/analyze/status")
def analyze_player_status(username: str) -> dict:
    username = username.strip().lower()
    with conn_ctx() as conn:
        if not require_player(conn, username):
            raise HTTPException(status_code=404, detail="player not found")
        total = conn.execute(
            "SELECT COUNT(*) FROM games WHERE player_username = ?", (username,)
        ).fetchone()[0]
        analyzed = conn.execute(
            "SELECT COUNT(DISTINCT a.game_id) FROM analyses a"
            " JOIN games g ON g.id = a.game_id WHERE g.player_username = ?",
            (username,),
        ).fetchone()[0]
    return {"username": username, "games": total, "analyzed": analyzed}


@app.post("/games/{game_id}/analyze")
def analyze(game_id: int, depth: int = Query(default=DEFAULT_DEPTH, ge=1, le=30)) -> dict:
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT g.id, g.player_username FROM games g WHERE g.id = ?", (game_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="game not found")
        username = row["player_username"]
        already_analyzed = conn.execute(
            "SELECT 1 FROM analyses WHERE game_id = ? LIMIT 1", (game_id,)
        ).fetchone() is not None

    # If a job is running for this player and the game hasn't been analyzed yet,
    # let the job do it (avoid lock contention) by adding it to the priority queue.
    job = active_job_for(username)
    if job and job.snapshot["status"] == "running" and not already_analyzed:
        evt = job.prioritize(game_id)
        evt.wait(timeout=300)  # wait up to 5 min for the job to analyze it

    # Re-analyze directly (either no job, game already done, or post-job re-analysis).
    try:
        with conn_ctx() as conn:
            return analyze_game(game_id, conn, depth=depth)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/games/{game_id}/analysis")
def get_game_analysis(game_id: int) -> dict:
    with conn_ctx() as conn:
        game_row = conn.execute("SELECT id FROM games WHERE id = ?", (game_id,)).fetchone()
        if not game_row:
            raise HTTPException(status_code=404, detail="game not found")
        rows = conn.execute(
            "SELECT ply, fen, best_move, played_move, eval_cp, classification,"
            " motif_tags, phase, pv, motif_details"
            " FROM analyses WHERE game_id = ? ORDER BY ply",
            (game_id,),
        ).fetchall()
    return {
        "game_id": game_id,
        "plies": [dict(r) for r in rows],
    }


@app.get("/games/{game_id}")
def get_game(game_id: int) -> dict:
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT id, player_username, chesscom_id, played_at, time_control,"
            " white, black, result, eco, opening_name, opening_ply, pgn"
            " FROM games WHERE id = ?",
            (game_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="game not found")
    return dict(row)


@app.get("/players/{username}/patterns")
def get_player_patterns(
    username: str,
    opening: Optional[str] = Query(default=None),
    color: Optional[str] = Query(default=None),
    time_format: Optional[str] = Query(default=None),
) -> dict:
    username = username.strip().lower()
    with conn_ctx() as conn:
        if not require_player(conn, username):
            raise HTTPException(status_code=404, detail="player not found")

        # Fetch all games for filter-value discovery
        all_games = conn.execute(
            "SELECT id, white, black, time_control, eco, opening_name FROM games WHERE player_username = ?",
            (username,),
        ).fetchall()

        # Compute available filter values from all games (unfiltered)
        opening_counts: dict[str, int] = defaultdict(int)
        avail_time_formats: set[str] = set()
        avail_colors: set[str] = set()
        valid_game_ids: set[int] = set()
        for g in all_games:
            is_white = (g["white"] or "").strip().lower() == username
            player_color = "white" if is_white else "black"
            tf = _classify_time_format(g["time_control"])
            op_name = g["opening_name"] or g["eco"] or ""
            eco = g["eco"] or ""
            avail_time_formats.add(tf)
            avail_colors.add(player_color)
            # Opening dropdown counts/ordering reflect the OTHER active filters
            # (color + time format) but not the opening filter itself, so the list
            # narrows to what's relevant under the current selection.
            if op_name:
                if (not color or player_color == color.lower()) and (
                    not time_format or tf == time_format
                ):
                    opening_counts[op_name] += 1
            # Games feeding the motif/phase aggregates respect all three filters.
            if color and player_color != color.lower():
                continue
            if time_format and tf != time_format:
                continue
            if opening and op_name and op_name != opening and eco != opening:
                continue
            valid_game_ids.add(g["id"])

        # Openings sorted by how often the player has played them (desc), with a
        # representative move line for hover snippets in the UI.
        avail_openings = [
            {"name": name, "games": cnt, "moves": line_for_name(name)}
            for name, cnt in sorted(
                opening_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ]
        available_filters = {
            "openings": avail_openings,
            "time_formats": sorted(avail_time_formats),
            "colors": sorted(avail_colors),
        }

        if not valid_game_ids:
            return {
                "username": username,
                "patterns": [],
                "phase_counts": {},
                "available_filters": available_filters,
            }

        placeholders = ",".join("?" * len(valid_game_ids))
        rows = conn.execute(
            f"SELECT a.game_id, a.ply, a.fen, a.motif_tags, a.phase, g.white, g.black"
            f" FROM analyses a"
            f" JOIN games g ON g.id = a.game_id"
            f" WHERE g.id IN ({placeholders})"
            f"   AND a.classification IN ('blunder', 'mistake', 'inaccuracy')"
            f" ORDER BY a.game_id DESC, a.ply ASC",
            list(valid_game_ids),
        ).fetchall()

    # Per-game dedup: each motif counted at most once per game. Density signal
    # (how many times in a single game) is lost on purpose — for now this gives
    # the more interpretable "how often does this pattern come up" number.
    games_per_motif: dict[str, set[int]] = defaultdict(set)
    last_game: dict[str, int] = {}
    last_ply: dict[str, int] = {}
    examples: dict[str, list] = defaultdict(list)
    phase_counts: dict[str, int] = defaultdict(int)

    # rows are ORDER BY game_id DESC, ply ASC: the first time we see a tag is its
    # earliest occurrence in the most recent game it appeared in.
    for r in rows:
        # Only count motifs on the analyzed player's OWN moves. analyses holds a
        # row per ply for both sides; ply is 0-indexed so even = White, odd =
        # Black. Attributing the opponent's mistakes to this player inflated the
        # counts and pointed "Last seen" at the wrong move.
        player_is_white = (r["white"] or "").strip().lower() == username
        mover_is_white = (r["ply"] % 2) == 0
        if mover_is_white != player_is_white:
            continue

        game_id = r["game_id"]
        fen = r["fen"]
        phase = r["phase"] or "middlegame"
        phase_counts[phase] += 1

        if not r["motif_tags"]:
            continue
        try:
            tags = json.loads(r["motif_tags"])
        except (json.JSONDecodeError, TypeError):
            continue

        for tag in tags:
            already_seen_in_game = game_id in games_per_motif[tag]
            games_per_motif[tag].add(game_id)
            if tag not in last_game:
                last_game[tag] = game_id
                last_ply[tag] = r["ply"]
            if not already_seen_in_game and len(examples[tag]) < 3:
                examples[tag].append(fen)

    patterns = [
        {
            "motif": motif,
            "count": len(games_per_motif[motif]),
            "last_seen_game_id": last_game.get(motif),
            "last_seen_ply": last_ply.get(motif),
            "example_fens": examples[motif],
        }
        for motif in sorted(
            games_per_motif, key=lambda m: len(games_per_motif[m]), reverse=True
        )
    ]

    return {
        "username": username,
        "patterns": patterns,
        "phase_counts": dict(phase_counts),
        "available_filters": available_filters,
    }


@app.get("/players/{username}/drill")
def get_player_drill(
    username: str,
    motif: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    """Return a mixed puzzle queue for the player.

    Mixes (a) Lichess puzzles whose themes match the player's top mistake motifs
    and (b) positions from the player's own games just before a blunder/mistake.
    """
    username = username.strip().lower()
    with conn_ctx() as conn:
        if not require_player(conn, username):
            raise HTTPException(status_code=404, detail="player not found")

        # ── Determine target motif ────────────────────────────────────────────
        target_motif: Optional[str] = motif
        if target_motif and target_motif not in _MOTIF_TO_LICHESS:
            raise HTTPException(status_code=400, detail=f"unknown motif: {target_motif}")

        if not target_motif:
            # Pick the user's most frequent mistake motif automatically (own moves).
            target_motif = pick_target_motif(conn, username, own_moves_only=True)

        items: list[dict] = []

        # ── (a) Lichess puzzles matching the motif ────────────────────────────
        if target_motif:
            ensure_lichess_puzzles(conn, username, target_motif)
            puzzle_rows = lichess_puzzles_for_motif(conn, target_motif, limit, username=username)
            for pr in puzzle_rows:
                try:
                    themes_list = json.loads(pr["themes"])
                except (json.JSONDecodeError, TypeError):
                    themes_list = []
                items.append(
                    {
                        "type": "lichess_puzzle",
                        "puzzle_id": pr["id"],
                        "fen": pr["fen"],
                        "solution_moves": pr["solution_moves"].split(),
                        "themes": themes_list,
                        "motif": target_motif,
                    }
                )

        # ── (b) Own-game pre-blunder positions ───────────────────────────────
        own_where, own_params = own_game_blunders_filter(username, target_motif)

        own_rows = conn.execute(
            f"SELECT a.game_id, a.ply, a.fen, a.best_move, a.played_move,"
            f"       a.classification, a.motif_tags, a.motif_details, a.eval_cp,"
            f"       prev.eval_cp AS eval_cp_before"
            f" FROM analyses a JOIN games g ON g.id = a.game_id"
            f" LEFT JOIN analyses prev ON prev.game_id = a.game_id AND prev.ply = a.ply - 1"
            f" WHERE {own_where}"
            f" ORDER BY RANDOM() LIMIT ?",
            own_params + [max(1, limit // 3)],
        ).fetchall()
        for or_ in own_rows:
            try:
                tags = json.loads(or_["motif_tags"] or "[]")
            except (json.JSONDecodeError, TypeError):
                tags = []
            try:
                motif_details = json.loads(or_["motif_details"] or "{}")
            except (json.JSONDecodeError, TypeError):
                motif_details = {}
            fen = or_["fen"]
            board = chess.Board(fen)

            def _san1(uci: str | None) -> str | None:
                if not uci:
                    return None
                try:
                    return board.san(chess.Move.from_uci(uci))
                except Exception:
                    return uci

            items.append(
                {
                    "type": "own_game",
                    "game_id": or_["game_id"],
                    "ply": or_["ply"],
                    "fen": fen,
                    "best_move": _san1(or_["best_move"]),
                    "played_move": _san1(or_["played_move"]),
                    "classification": or_["classification"],
                    "motif_tags": tags,
                    "motif_details": motif_details,
                    "motif": target_motif,
                    "eval_cp": or_["eval_cp"],
                    "eval_cp_before": or_["eval_cp_before"],
                    "player_color": "white" if (or_["ply"] % 2 == 0) else "black",
                }
            )

        random.shuffle(items)

    return {
        "username": username,
        "motif": target_motif,
        "count": len(items),
        "items": items,
    }


class PuzzleAttemptIn(BaseModel):
    puzzle_id: str
    username: str
    solved: bool


@app.post("/puzzle_attempts", status_code=201)
def record_puzzle_attempt(body: PuzzleAttemptIn) -> dict:
    username = body.username.strip().lower()
    with conn_ctx() as conn:
        if not require_player(conn, username):
            raise HTTPException(status_code=404, detail="player not found")

        puzzle_row = conn.execute(
            "SELECT id FROM puzzles WHERE id = ?", (body.puzzle_id,)
        ).fetchone()
        if not puzzle_row:
            raise HTTPException(status_code=404, detail="puzzle not found")

        return record_attempt(conn, body.puzzle_id, username, body.solved)


class EvaluatePositionIn(BaseModel):
    fen: str
    depth: int = DEFAULT_DEPTH
    multipv: int = 1


@app.post("/positions/evaluate")
def evaluate_position_endpoint(body: EvaluatePositionIn) -> dict:
    """Evaluate a FEN position and return the top candidate lines.

    Response: {lines: [{rank, move_uci, move_san, eval_cp, mate, pv_uci, pv_san}], depth}
    eval_cp is white-POV (null on mate). mate is signed mate-in-N (null otherwise).
    pv contains >= 5 plies when available.
    Returns 400 on invalid FEN.
    """
    try:
        board = chess.Board(body.fen)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid FEN: {e}")

    if body.depth < 1 or body.depth > 30:
        raise HTTPException(status_code=400, detail="depth must be 1–30")
    if body.multipv < 1 or body.multipv > 10:
        raise HTTPException(status_code=400, detail="multipv must be 1–10")

    try:
        raw_lines = evaluate_position(body.fen, depth=body.depth, multipv=body.multipv)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    lines = format_lines(board, raw_lines)

    actual_depth = raw_lines[0]["depth"] if raw_lines else body.depth
    return {"lines": lines, "depth": actual_depth}


@app.get("/players/{username}/games")
def list_player_games(
    username: str,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    result: Optional[str] = Query(default=None),
    time_control: Optional[str] = Query(default=None),
    opening: Optional[str] = Query(default=None),
    color: Optional[str] = Query(default=None),
    time_format: Optional[str] = Query(default=None),
) -> dict:
    username = username.strip().lower()
    with conn_ctx() as conn:
        if not require_player(conn, username):
            raise HTTPException(status_code=404, detail="player not found")

        conditions = ["player_username = ?"]
        params: list = [username]
        if result:
            conditions.append("result = ?")
            params.append(result)
        if time_control:
            conditions.append("time_control = ?")
            params.append(time_control)
        if opening:
            conditions.append("(opening_name = ? OR eco = ?)")
            params.extend([opening, opening])
        if color == "white":
            conditions.append("LOWER(white) = ?")
            params.append(username)
        elif color == "black":
            conditions.append("LOWER(black) = ?")
            params.append(username)

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT id, chesscom_id, played_at, time_control, white, black, result, eco, opening_name, num_moves"
            f" FROM games WHERE {where} ORDER BY played_at DESC",
            params,
        ).fetchall()

        # time_format is derived from the raw time_control string, so it can't be
        # expressed in SQL — filter in Python, then paginate the filtered set.
        if time_format:
            rows = [r for r in rows if _classify_time_format(r["time_control"]) == time_format]

        total = len(rows)
        page_rows = rows[offset : offset + limit]
        game_ids = [r["id"] for r in page_rows]
        summaries = _eval_summaries(conn, username, game_ids)

    games = []
    for r in page_rows:
        g = dict(r)
        g["summary"] = summaries.get(r["id"])
        games.append(g)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "games": games,
    }


def _wld(result: str, is_white: bool) -> str:
    if result == "1/2-1/2":
        return "draws"
    if (result == "1-0" and is_white) or (result == "0-1" and not is_white):
        return "wins"
    return "losses"


def _win_pct(wins: int, total: int) -> float:
    return round(wins / total * 100, 1) if total else 0.0


def _stats_shape(wins: int, losses: int, draws: int) -> dict:
    total = wins + losses + draws
    return {"wins": wins, "losses": losses, "draws": draws, "total": total, "win_pct": _win_pct(wins, total)}


@app.get("/players/{username}/stats")
def get_player_stats(
    username: str,
    opening: Optional[str] = Query(default=None),
    color: Optional[str] = Query(default=None),
    time_format: Optional[str] = Query(default=None),
) -> dict:
    username = username.strip().lower()
    with conn_ctx() as conn:
        if not require_player(conn, username):
            raise HTTPException(status_code=404, detail="player not found")

        rows = conn.execute(
            "SELECT id, white, black, result, time_control, eco, opening_name FROM games WHERE player_username = ?",
            (username,),
        ).fetchall()

    overall = {"wins": 0, "losses": 0, "draws": 0}
    by_color: dict[str, dict] = {"white": {"wins": 0, "losses": 0, "draws": 0}, "black": {"wins": 0, "losses": 0, "draws": 0}}
    by_time_format: dict[str, dict] = {}
    # opening stats: color -> opening_key -> {wins, losses, draws, opening_name, eco}
    opening_stats: dict[str, dict] = {"white": {}, "black": {}}

    for r in rows:
        is_white = (r["white"] or "").strip().lower() == username
        player_color = "white" if is_white else "black"
        tf = _classify_time_format(r["time_control"])
        op_name = r["opening_name"] or r["eco"] or ""
        eco = r["eco"] or ""

        # Opening + time-format filters mask every aggregate. The COLOR filter is
        # deliberately NOT applied to the color-centric cards (Overall, By Color,
        # Best Openings) — those always show the full White-vs-Black picture so the
        # comparison stays meaningful. Color only narrows By Format (and the
        # patterns/phase/motif sections handled by the patterns endpoint).
        if time_format and tf != time_format:
            continue
        if opening and op_name and op_name != opening and eco != opening:
            continue

        outcome = _wld(r["result"], is_white)

        def inc(d: dict) -> None:
            d[outcome] = d.get(outcome, 0) + 1

        inc(overall)
        inc(by_color[player_color])

        if op_name:
            key = op_name
            if key not in opening_stats[player_color]:
                opening_stats[player_color][key] = {"wins": 0, "losses": 0, "draws": 0, "opening_name": op_name, "eco": eco}
            inc(opening_stats[player_color][key])

        # By Format respects the color filter.
        if color and player_color != color.lower():
            continue
        if tf not in by_time_format:
            by_time_format[tf] = {"wins": 0, "losses": 0, "draws": 0}
        inc(by_time_format[tf])

    def opening_entries(color_key: str) -> list:
        entries = []
        for op_data in opening_stats[color_key].values():
            total = op_data["wins"] + op_data["losses"] + op_data["draws"]
            if total < 3:
                continue
            wp = _win_pct(op_data["wins"], total)
            entries.append({
                "opening_name": op_data["opening_name"],
                "eco": op_data["eco"],
                "moves": line_for_name(op_data["opening_name"]),
                "games": total,
                "wins": op_data["wins"],
                "losses": op_data["losses"],
                "draws": op_data["draws"],
                "win_pct": wp,
            })
        return entries

    def top_openings(color_key: str) -> list:
        entries = opening_entries(color_key)
        entries.sort(key=lambda x: (-x["win_pct"], -x["games"]))
        return entries[:5]

    def most_common_openings(color_key: str) -> list:
        entries = opening_entries(color_key)
        entries.sort(key=lambda x: (-x["games"], -x["win_pct"]))
        return entries[:5]

    return {
        "username": username,
        "overall": _stats_shape(overall.get("wins", 0), overall.get("losses", 0), overall.get("draws", 0)),
        "by_color": {
            "white": _stats_shape(by_color["white"].get("wins", 0), by_color["white"].get("losses", 0), by_color["white"].get("draws", 0)),
            "black": _stats_shape(by_color["black"].get("wins", 0), by_color["black"].get("losses", 0), by_color["black"].get("draws", 0)),
        },
        "by_time_format": {
            tf: _stats_shape(v.get("wins", 0), v.get("losses", 0), v.get("draws", 0))
            for tf, v in sorted(
                by_time_format.items(),
                key=lambda kv: ["Daily", "Classical", "Rapid", "Blitz", "Bullet", "Unknown"].index(kv[0])
                if kv[0] in ["Daily", "Classical", "Rapid", "Blitz", "Bullet", "Unknown"] else 99,
            )
        },
        "best_openings": {
            "white": top_openings("white"),
            "black": top_openings("black"),
        },
        "most_common_openings": {
            "white": most_common_openings("white"),
            "black": most_common_openings("black"),
        },
    }


def _eval_summaries(conn, username: str, game_ids: list[int]) -> dict[int, dict]:
    """Per-game eval summary for a set of games: the analyzed player's ACPL and
    blunder/mistake counts, plus a coarse eval sparkline (white-POV cp by ply,
    clamped to ±1000). Returns {} for games with no analysis."""
    if not game_ids:
        return {}
    placeholders = ",".join("?" for _ in game_ids)
    # White player per game (to know which plies belong to the analyzed user).
    white_of = {
        r["id"]: (r["white"] or "").strip().lower()
        for r in conn.execute(
            f"SELECT id, white FROM games WHERE id IN ({placeholders})", game_ids
        ).fetchall()
    }
    rows = conn.execute(
        f"SELECT game_id, ply, eval_cp, classification FROM analyses"
        f" WHERE game_id IN ({placeholders}) ORDER BY game_id, ply",
        game_ids,
    ).fetchall()

    by_game: dict[int, list] = defaultdict(list)
    for r in rows:
        by_game[r["game_id"]].append(r)

    out: dict[int, dict] = {}
    for gid, plies in by_game.items():
        player_is_white = white_of.get(gid) == username
        prev_eval = 0  # eval before the first move (white POV)
        loss_sum = 0
        loss_count = 0
        blunders = mistakes = inaccuracies = 0
        series: list[Optional[int]] = []
        for row in plies:
            ev = row["eval_cp"]
            mover_is_white = (row["ply"] % 2) == 0
            if ev is not None:
                series.append(max(-1000, min(1000, ev)))
            else:
                series.append(None)
            # Centipawn loss + classification only for the analyzed player's moves.
            if mover_is_white == player_is_white:
                if row["classification"] == "blunder":
                    blunders += 1
                elif row["classification"] == "mistake":
                    mistakes += 1
                elif row["classification"] == "inaccuracy":
                    inaccuracies += 1
                if ev is not None and prev_eval is not None:
                    before = prev_eval if mover_is_white else -prev_eval
                    after = ev if mover_is_white else -ev
                    loss_sum += max(0, before - after)
                    loss_count += 1
            if ev is not None:
                prev_eval = ev
        out[gid] = {
            "analyzed": True,
            "acpl": round(loss_sum / loss_count) if loss_count else 0,
            "blunders": blunders,
            "mistakes": mistakes,
            "inaccuracies": inaccuracies,
            "eval_series": series,
        }
    return out


# ---------------------------------------------------------------------------
# LLM settings
# ---------------------------------------------------------------------------

class LLMSettingsIn(BaseModel):
    provider: str  # "anthropic" | "openai" | "gemini" | "ollama"
    api_key: str   # plaintext — encrypted before writing to DB


@app.get("/settings/llm")
def settings_llm_get():
    """Return current provider and whether an API key is stored (never the key itself)."""
    return get_llm_settings()


@app.post("/settings/llm")
def settings_llm_post(body: LLMSettingsIn):
    valid_providers = {"anthropic", "openai", "gemini", "ollama"}
    if body.provider not in valid_providers:
        raise HTTPException(400, f"provider must be one of {sorted(valid_providers)}")
    if not body.api_key.strip():
        raise HTTPException(400, "api_key must not be empty")
    save_llm_settings(body.provider, body.api_key.strip())
    return {"ok": True}


# ---------------------------------------------------------------------------
# LLM chat
# ---------------------------------------------------------------------------

class CandidateLine(BaseModel):
    rank: int
    move_san: str
    eval_cp: Optional[int] = None
    mate: Optional[int] = None
    pv_san: list[str] = []


class ChatRequest(BaseModel):
    fen: str
    candidates: list[CandidateLine] = []
    question: str
    eval_cp: Optional[int] = None
    played_move: Optional[str] = None
    best_move: Optional[str] = None
    classification: Optional[str] = None
    eval_cp_before: Optional[int] = None
    eval_cp_after: Optional[int] = None
    user_color: Optional[str] = None
    motif_details: Optional[dict] = None


@app.post("/chat")
async def chat_endpoint(body: ChatRequest):
    if not body.question.strip():
        raise HTTPException(400, "question must not be empty")

    candidates = [c.model_dump() for c in body.candidates]
    played_move_line: dict | None = None

    # If we have the user's played move (SAN) and it's not already in the top lines,
    # look up its concrete engine eval + PV so the LLM can reason about it directly.
    if body.played_move and body.fen:
        played_san = body.played_move
        already_covered = any(c.get("move_san") == played_san for c in candidates)
        if not already_covered:
            try:
                board = chess.Board(body.fen)
                # Find the UCI for the played SAN move
                played_uci = None
                for m in board.legal_moves:
                    if board.san(m) == played_san:
                        played_uci = m.uci()
                        break
                if played_uci:
                    # Push the move and evaluate the resulting position (opponent's turn)
                    board_after = board.copy()
                    board_after.push(chess.Move.from_uci(played_uci))
                    raw = evaluate_position(board_after.fen(), depth=CHAT_DEPTH, multipv=1)
                    if raw:
                        r = raw[0]
                        # Flip eval to be from the perspective of the side that just moved
                        flipped_eval = -r["eval_cp"] if r["eval_cp"] is not None else None
                        pv_san = uci_to_san(board_after, r["pv"])
                        played_move_line = {
                            "move_san": played_san,
                            "eval_cp": flipped_eval,
                            "pv_san": [played_san] + pv_san,
                        }
            except Exception:
                pass  # non-fatal; proceed without it

    try:
        answer = await llm_chat(
            fen=body.fen,
            candidates=candidates,
            question=body.question.strip(),
            eval_cp=body.eval_cp,
            played_move=body.played_move,
            best_move=body.best_move,
            classification=body.classification,
            eval_cp_before=body.eval_cp_before,
            eval_cp_after=body.eval_cp_after,
            played_move_line=played_move_line,
            user_color=body.user_color,
            motif_details=body.motif_details,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"LLM provider error: {e}")
    return {"answer": answer}


# ---------------------------------------------------------------------------
# Best games + narrative
# ---------------------------------------------------------------------------

@app.get("/players/{username}/best-games")
def get_best_games(username: str, limit: int = 3) -> dict:
    """Return the player's top games by quality (lowest acpl + fewest blunders/mistakes).
    Only includes analyzed games with at least 20 analyzed plies."""
    with conn_ctx() as conn:
        # Get all analyzed game IDs for this player with enough plies
        rows = conn.execute(
            """
            SELECT g.id, g.white, g.black, g.result, g.played_at,
                   g.opening_name, g.eco, g.num_moves, g.time_control,
                   COUNT(a.ply) as analyzed_plies
            FROM games g
            JOIN analyses a ON a.game_id = g.id
            WHERE g.player_username = ?
            GROUP BY g.id
            HAVING analyzed_plies >= 20
            """,
            (username,),
        ).fetchall()

    if not rows:
        return {"games": []}

    game_ids = [r["id"] for r in rows]
    row_by_id = {r["id"]: r for r in rows}

    with conn_ctx() as conn:
        summaries = _eval_summaries(conn, username, game_ids)

    # Score each game: lower is better
    def score(gid: int) -> float:
        s = summaries.get(gid)
        if not s:
            return float("inf")
        return s["acpl"] + s["blunders"] * 30 + s["mistakes"] * 10

    ranked = sorted(game_ids, key=score)[:limit]

    result = []
    for gid in ranked:
        r = row_by_id[gid]
        s = summaries.get(gid, {})
        result.append({
            "id": gid,
            "white": r["white"],
            "black": r["black"],
            "result": r["result"],
            "played_at": r["played_at"],
            "opening_name": r["opening_name"],
            "eco": r["eco"],
            "num_moves": r["num_moves"],
            "time_control": r["time_control"],
            "acpl": s.get("acpl", 0),
            "blunders": s.get("blunders", 0),
            "mistakes": s.get("mistakes", 0),
            "inaccuracies": s.get("inaccuracies", 0),
        })
    return {"games": result}


@app.post("/games/{game_id}/narrative")
async def get_game_narrative(game_id: int) -> dict:
    """Generate (or return cached) an LLM narrative for a game.
    Picks 3 key positions: opening (~ply 12), biggest eval swing, final."""
    with conn_ctx() as conn:
        # Check cache first
        cached = conn.execute(
            "SELECT narrative FROM narratives WHERE game_id = ?", (game_id,)
        ).fetchone()
        if cached:
            return {"narrative": cached["narrative"], "cached": True}

        game = conn.execute(
            "SELECT white, black, result, opening_name, eco, player_username "
            "FROM games WHERE id = ?",
            (game_id,),
        ).fetchone()
        if not game:
            raise HTTPException(404, "game not found")

        plies = conn.execute(
            "SELECT ply, fen, eval_cp, classification, motif_tags "
            "FROM analyses WHERE game_id = ? ORDER BY ply",
            (game_id,),
        ).fetchall()

    if len(plies) < 10:
        raise HTTPException(400, "game has insufficient analysis")

    username = game["player_username"]

    # ── Key position 1: opening (~ply 12, or earliest middlegame ply) ──────
    opening_ply = min(range(len(plies)), key=lambda i: abs(plies[i]["ply"] - 12))
    opening_pos = plies[opening_ply]

    # ── Key position 2: biggest single-move eval swing ──────────────────────
    biggest_swing_idx = 0
    biggest_swing = 0
    for i in range(1, len(plies)):
        a = plies[i - 1]["eval_cp"]
        b = plies[i]["eval_cp"]
        if a is not None and b is not None:
            swing = abs(b - a)
            if swing > biggest_swing:
                biggest_swing = swing
                biggest_swing_idx = i
    critical_pos = plies[biggest_swing_idx]

    # ── Key position 3: final position ──────────────────────────────────────
    final_pos = plies[-1]

    key_positions = [
        {"label": "Opening", "fen": opening_pos["fen"],
         "eval_cp": opening_pos["eval_cp"] or 0,
         "move_num": opening_pos["ply"] // 2 + 1},
        {"label": "Critical moment", "fen": critical_pos["fen"],
         "eval_cp": critical_pos["eval_cp"] or 0,
         "move_num": critical_pos["ply"] // 2 + 1},
        {"label": "Final position", "fen": final_pos["fen"],
         "eval_cp": final_pos["eval_cp"] or 0,
         "move_num": final_pos["ply"] // 2 + 1},
    ]

    # Collect dominant motifs across all plies
    motif_counts: dict[str, int] = {}
    for p in plies:
        try:
            tags = json.loads(p["motif_tags"] or "[]")
        except Exception:
            tags = []
        for t in tags:
            motif_counts[t] = motif_counts.get(t, 0) + 1
    dominant_motifs = [m for m, _ in sorted(motif_counts.items(), key=lambda x: -x[1])[:3]]

    with conn_ctx() as conn:
        summaries = _eval_summaries(conn, username, [game_id])
    s = summaries.get(game_id, {})

    try:
        text = await llm_narrative(
            white=game["white"],
            black=game["black"],
            result=game["result"],
            opening_name=game["opening_name"] or game["eco"],
            player_username=username,
            acpl=s.get("acpl", 0),
            blunders=s.get("blunders", 0),
            mistakes=s.get("mistakes", 0),
            key_positions=key_positions,
            dominant_motifs=dominant_motifs,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"LLM provider error: {e}")

    # Cache it
    with conn_ctx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO narratives(game_id, narrative, created_at) VALUES(?, ?, ?)",
            (game_id, text, datetime.now(timezone.utc).isoformat()),
        )

    return {"narrative": text, "cached": False}


@app.delete("/games/{game_id}/narrative")
def delete_game_narrative(game_id: int) -> dict:
    """Clear the cached narrative for a game so it can be regenerated."""
    with conn_ctx() as conn:
        conn.execute("DELETE FROM narratives WHERE game_id = ?", (game_id,))
    return {"ok": True}
