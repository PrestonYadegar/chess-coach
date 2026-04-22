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
from .chesscom import sync_player_games, sync_player_games_events
from .db import conn_ctx, init_db
from .engine_cache import evaluate_position, shutdown_engine
from .jobs import active_job_for, get_job, start_job, stream as stream_job

# Map our 9 internal motif tags → Lichess theme keywords (used for LIKE search)
_MOTIF_TO_LICHESS: dict[str, list[str]] = {
    "hanging_piece": ["hangingPiece"],
    "fork_missed": ["fork"],
    "skewer_missed": ["skewer"],
    "back_rank": ["backRankMate"],
    "pin_missed": ["pin"],
    "discovered_attack": ["discoveredAttack"],
    "overloaded_piece": ["overloadedPiece"],
    "intermezzo_missed": ["intermezzo", "zugzwang"],
    "only_move_missed": ["defensiveMove", "quietMove"],
    "mating_net_missed": ["mateIn1", "mateIn2", "mateIn3", "mateIn4", "mateIn5"],
    "mating_net_allowed": ["mateIn1", "mateIn2", "mateIn3"],
    "king_safety": ["kingsideAttack", "queensideAttack", "attackingF2F7"],
    "pawn_structure": ["pawnEndgame", "advancedPawn"],
    "endgame_technique": ["endgame"],
    "opening_principle": ["opening"],
}

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
            return sync_player_games(username, conn)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"chess.com error: {e.response.text[:200]}",
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"chess.com fetch failed: {e}")


@app.get("/players/{username}/sync/stream")
def sync_player_stream(username: str) -> StreamingResponse:
    """Server-Sent Events: one event per archive ingested."""
    username = username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="username required")

    def event_source():
        try:
            with conn_ctx() as conn:
                for event in sync_player_games_events(username, conn):
                    yield f"data: {json.dumps(event)}\n\n"
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
    depth: int = 14
    limit: int = 50
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
        if not conn.execute(
            "SELECT 1 FROM players WHERE username = ?", (username,)
        ).fetchone():
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


@app.get("/players/{username}/analyze/status")
def analyze_player_status(username: str) -> dict:
    username = username.strip().lower()
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT username FROM players WHERE username = ?", (username,)
        ).fetchone()
        if not row:
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
def analyze(game_id: int, depth: int = Query(default=18, ge=1, le=30)) -> dict:
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
def get_player_patterns(username: str) -> dict:
    username = username.strip().lower()
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT username FROM players WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="player not found")

        rows = conn.execute(
            "SELECT a.game_id, a.ply, a.fen, a.motif_tags, a.phase, g.white, g.black"
            " FROM analyses a"
            " JOIN games g ON g.id = a.game_id"
            " WHERE g.player_username = ?"
            "   AND a.classification IN ('blunder', 'mistake', 'inaccuracy')"
            " ORDER BY a.game_id DESC, a.ply ASC",
            (username,),
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
        row = conn.execute(
            "SELECT username FROM players WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="player not found")

        # ── Determine target motif ────────────────────────────────────────────
        target_motif: Optional[str] = motif
        if target_motif and target_motif not in _MOTIF_TO_LICHESS:
            raise HTTPException(status_code=400, detail=f"unknown motif: {target_motif}")

        if not target_motif:
            # Pick the user's most frequent mistake motif automatically
            mistake_rows = conn.execute(
                "SELECT a.motif_tags, a.ply, g.white FROM analyses a"
                " JOIN games g ON g.id = a.game_id"
                " WHERE g.player_username = ?"
                "   AND a.motif_tags IS NOT NULL"
                "   AND a.classification IN ('blunder', 'mistake', 'inaccuracy')"
                " ORDER BY a.game_id DESC LIMIT 500",
                (username,),
            ).fetchall()
            counts: dict[str, int] = defaultdict(int)
            for mr in mistake_rows:
                # Only the player's own moves (see patterns endpoint for rationale).
                player_is_white = (mr["white"] or "").strip().lower() == username
                if ((mr["ply"] % 2) == 0) != player_is_white:
                    continue
                try:
                    tags = json.loads(mr["motif_tags"])
                except (json.JSONDecodeError, TypeError):
                    continue
                for t in tags:
                    if t in _MOTIF_TO_LICHESS:
                        counts[t] += 1
            target_motif = max(counts, key=lambda m: counts[m]) if counts else None

        items: list[dict] = []

        # ── (a) Lichess puzzles matching the motif ────────────────────────────
        if target_motif:
            lichess_themes = _MOTIF_TO_LICHESS[target_motif]
            like_clauses = " OR ".join("themes LIKE ?" for _ in lichess_themes)
            like_params = [f"%{t}%" for t in lichess_themes]
            puzzle_rows = conn.execute(
                f"SELECT id, fen, solution_moves, themes FROM puzzles"
                f" WHERE ({like_clauses})"
                f" ORDER BY RANDOM() LIMIT ?",
                like_params + [limit],
            ).fetchall()
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
        own_where = (
            "g.player_username = ? AND a.classification IN ('blunder', 'mistake')"
        )
        own_params: list = [username]
        if target_motif:
            own_where += " AND a.motif_tags LIKE ?"
            own_params.append(f"%{target_motif}%")

        own_rows = conn.execute(
            f"SELECT a.game_id, a.ply, a.fen, a.best_move, a.played_move,"
            f"       a.classification, a.motif_tags"
            f" FROM analyses a JOIN games g ON g.id = a.game_id"
            f" WHERE {own_where}"
            f" ORDER BY RANDOM() LIMIT ?",
            own_params + [max(1, limit // 3)],
        ).fetchall()
        for or_ in own_rows:
            try:
                tags = json.loads(or_["motif_tags"] or "[]")
            except (json.JSONDecodeError, TypeError):
                tags = []
            items.append(
                {
                    "type": "own_game",
                    "game_id": or_["game_id"],
                    "ply": or_["ply"],
                    "fen": or_["fen"],
                    "best_move": or_["best_move"],
                    "played_move": or_["played_move"],
                    "classification": or_["classification"],
                    "motif_tags": tags,
                    "motif": target_motif,
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
    now = datetime.now(timezone.utc).isoformat()
    with conn_ctx() as conn:
        player_row = conn.execute(
            "SELECT username FROM players WHERE username = ?", (username,)
        ).fetchone()
        if not player_row:
            raise HTTPException(status_code=404, detail="player not found")

        puzzle_row = conn.execute(
            "SELECT id FROM puzzles WHERE id = ?", (body.puzzle_id,)
        ).fetchone()
        if not puzzle_row:
            raise HTTPException(status_code=404, detail="puzzle not found")

        cur = conn.execute(
            "INSERT INTO puzzle_attempts (puzzle_id, username, solved, attempted_at)"
            " VALUES (?, ?, ?, ?)",
            (body.puzzle_id, username, int(body.solved), now),
        )
        attempt_id = cur.lastrowid

    return {
        "id": attempt_id,
        "puzzle_id": body.puzzle_id,
        "username": username,
        "solved": body.solved,
        "attempted_at": now,
    }


class EvaluatePositionIn(BaseModel):
    fen: str
    depth: int = 18
    multipv: int = 1


def _uci_to_san(board: chess.Board, uci_moves: list[str]) -> list[str]:
    """Apply UCI moves from `board` (copied) and return SAN strings."""
    b = board.copy()
    san_moves = []
    for uci in uci_moves:
        try:
            move = chess.Move.from_uci(uci)
            san_moves.append(b.san(move))
            b.push(move)
        except (ValueError, AssertionError):
            break
    return san_moves


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

    lines = []
    for line in raw_lines:
        pv_uci = line["pv"]
        move_uci = line["move_uci"]
        # Compute SAN for the first (best) move
        try:
            move_san = board.san(chess.Move.from_uci(move_uci)) if move_uci else ""
        except (ValueError, AssertionError):
            move_san = move_uci
        pv_san = _uci_to_san(board, pv_uci)
        lines.append(
            {
                "rank": line["rank"],
                "move_uci": move_uci,
                "move_san": move_san,
                "eval_cp": line["eval_cp"],
                "mate": line["mate"],
                "pv_uci": pv_uci,
                "pv_san": pv_san,
            }
        )

    actual_depth = raw_lines[0]["depth"] if raw_lines else body.depth
    return {"lines": lines, "depth": actual_depth}


@app.get("/players/{username}/games")
def list_player_games(
    username: str,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    result: Optional[str] = Query(default=None),
    time_control: Optional[str] = Query(default=None),
) -> dict:
    username = username.strip().lower()
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT username FROM players WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="player not found")

        conditions = ["player_username = ?"]
        params: list = [username]
        if result:
            conditions.append("result = ?")
            params.append(result)
        if time_control:
            conditions.append("time_control = ?")
            params.append(time_control)

        where = " AND ".join(conditions)
        total = conn.execute(
            f"SELECT COUNT(*) FROM games WHERE {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, chesscom_id, played_at, time_control, white, black, result, eco"
            f" FROM games WHERE {where} ORDER BY played_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "games": [dict(r) for r in rows],
    }
