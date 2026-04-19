from typing import Optional

from fastapi import FastAPI, HTTPException, Query
import httpx

from .analyze import analyze_game
from .chesscom import sync_player_games
from .db import conn_ctx, init_db

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
