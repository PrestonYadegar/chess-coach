import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import httpx

from .analyze import analyze_game
from .chesscom import sync_player_games
from .db import conn_ctx, init_db

# Map our 9 internal motif tags → Lichess theme keywords (used for LIKE search)
_MOTIF_TO_LICHESS: dict[str, list[str]] = {
    "hanging_piece": ["hangingPiece"],
    "fork_missed": ["fork"],
    "back_rank": ["backRankMate"],
    "pin_missed": ["pin"],
    "discovered_attack": ["discoveredAttack"],
    "overloaded_piece": ["overloadedPiece"],
    "king_safety": ["kingsideAttack", "queensideAttack", "attackingF2F7"],
    "endgame_technique": ["endgame"],
    "opening_principle": ["opening"],
}

app = FastAPI(title="chess-coach api", version="0.0.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


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
            "SELECT ply, fen, best_move, played_move, eval_cp, classification, motif_tags"
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
            " white, black, result, eco, pgn FROM games WHERE id = ?",
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
            "SELECT a.game_id, a.fen, a.motif_tags"
            " FROM analyses a"
            " JOIN games g ON g.id = a.game_id"
            " WHERE g.player_username = ?"
            "   AND a.motif_tags IS NOT NULL"
            "   AND a.classification IN ('blunder', 'mistake', 'inaccuracy')"
            " ORDER BY a.game_id DESC",
            (username,),
        ).fetchall()

    # Aggregate per motif
    counts: dict[str, int] = defaultdict(int)
    last_game: dict[str, int] = {}
    examples: dict[str, list] = defaultdict(list)

    for r in rows:
        game_id = r["game_id"]
        fen = r["fen"]
        try:
            tags = json.loads(r["motif_tags"])
        except (json.JSONDecodeError, TypeError):
            continue

        for tag in tags:
            counts[tag] += 1
            if tag not in last_game:
                last_game[tag] = game_id
            if len(examples[tag]) < 3:
                examples[tag].append(fen)

    patterns = [
        {
            "motif": motif,
            "count": counts[motif],
            "last_seen_game_id": last_game.get(motif),
            "example_fens": examples[motif],
        }
        for motif in sorted(counts, key=lambda m: counts[m], reverse=True)
    ]

    return {"username": username, "patterns": patterns}


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
                "SELECT a.motif_tags FROM analyses a"
                " JOIN games g ON g.id = a.game_id"
                " WHERE g.player_username = ?"
                "   AND a.motif_tags IS NOT NULL"
                "   AND a.classification IN ('blunder', 'mistake', 'inaccuracy')"
                " ORDER BY a.game_id DESC LIMIT 500",
                (username,),
            ).fetchall()
            counts: dict[str, int] = defaultdict(int)
            for mr in mistake_rows:
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
