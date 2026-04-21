"""Chess Coach MCP Server.

Exposes 7 tools so any MCP client (Claude Desktop, Cursor, etc.) can query
the local chess-coach database.

Run with:
    python -m app.mcp_server
or via the helper script:
    scripts/run-mcp.sh
"""

import json
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import chess
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from .db import conn_ctx
from .engine_cache import evaluate_position as _evaluate_position

server = Server("chess-coach")

# ── helpers ─────────────────────────────────────────────────────────────────

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


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=2)


# ── tool definitions ─────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_games",
            description=(
                "List chess games for a player (paginated). "
                "Returns id, opponent, result, time_control, and date for each game."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Chess.com username"},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                    "offset": {"type": "integer", "default": 0, "minimum": 0},
                    "result": {"type": "string", "description": "Filter by result: win, loss, draw"},
                    "time_control": {"type": "string", "description": "Filter by time control class"},
                },
                "required": ["username"],
            },
        ),
        types.Tool(
            name="get_game_pgn",
            description="Return the full PGN text for a specific game by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "game_id": {"type": "integer", "description": "Game database ID"},
                },
                "required": ["game_id"],
            },
        ),
        types.Tool(
            name="get_game_analysis",
            description=(
                "Return per-ply engine analysis for a game: eval, classification "
                "(blunder/mistake/inaccuracy/good), best move, played move, motif tags, and game phase."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "game_id": {"type": "integer", "description": "Game database ID"},
                },
                "required": ["game_id"],
            },
        ),
        types.Tool(
            name="get_mistake_history",
            description=(
                "Return the player's recent blunders and mistakes: FEN, played move, "
                "best move, eval swing, and motif tags. Ordered newest first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Chess.com username"},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                    "classification": {
                        "type": "string",
                        "description": "blunder, mistake, or inaccuracy (default: blunder and mistake)",
                    },
                },
                "required": ["username"],
            },
        ),
        types.Tool(
            name="get_top_patterns",
            description=(
                "Return the player's most common mistake motif patterns, ranked by "
                "number of games affected. Each entry includes example FENs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Chess.com username"},
                    "top_n": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                },
                "required": ["username"],
            },
        ),
        types.Tool(
            name="next_puzzle",
            description=(
                "Return the next drill puzzle for a player, optionally filtered by motif. "
                "Mixes Lichess theme puzzles matched to the player's weaknesses with "
                "positions from the player's own games just before a mistake."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Chess.com username"},
                    "motif": {
                        "type": "string",
                        "description": "Optional motif tag to filter by (e.g. fork_missed)",
                    },
                },
                "required": ["username"],
            },
        ),
        types.Tool(
            name="submit_puzzle_attempt",
            description="Record whether a player solved a puzzle.",
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Chess.com username"},
                    "puzzle_id": {"type": "string", "description": "Puzzle ID"},
                    "solved": {"type": "boolean", "description": "Whether the player solved it"},
                },
                "required": ["username", "puzzle_id", "solved"],
            },
        ),
        types.Tool(
            name="evaluate_position",
            description=(
                "Evaluate a FEN position with Stockfish and return the top-N candidate moves "
                "with their evaluations and principal variations. "
                "eval_cp is white-POV centipawns (null on mate). "
                "mate is signed mate-in-N (null otherwise). "
                "pv_uci and pv_san give the full line ≥5 plies when available. "
                "Results are cached — repeat calls at same/shallower depth return instantly."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "fen": {"type": "string", "description": "FEN string of the position to evaluate"},
                    "depth": {"type": "integer", "default": 18, "minimum": 1, "maximum": 30,
                              "description": "Stockfish search depth (default 18)"},
                    "multipv": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10,
                                "description": "Number of candidate lines to return (default 3)"},
                },
                "required": ["fen"],
            },
        ),
        types.Tool(
            name="explore_line",
            description=(
                "Apply a sequence of moves (UCI or SAN) from a starting FEN and return the "
                "resulting FEN plus its Stockfish evaluation and best continuation. "
                "Returns an error if any move is illegal. "
                "Use this to reason about alternative lines: each call extends the position "
                "one move-sequence at a time and reports what the engine thinks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "fen": {"type": "string", "description": "Starting FEN"},
                    "moves": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Sequence of moves in UCI (e4e5) or SAN (e4) notation",
                        "minItems": 1,
                    },
                    "depth": {"type": "integer", "default": 18, "minimum": 1, "maximum": 30,
                              "description": "Stockfish search depth for the resulting position"},
                    "multipv": {"type": "integer", "default": 1, "minimum": 1, "maximum": 5,
                                "description": "Number of candidate lines to return for the resulting position"},
                },
                "required": ["fen", "moves"],
            },
        ),
        types.Tool(
            name="explain_move",
            description=(
                "Return a structured fact bundle for a specific ply of an analyzed game. "
                "Contains everything needed for an LLM to produce a coaching explanation:\n"
                "  • played_move_san / played_move_uci — what was actually played\n"
                "  • eval_before / eval_after — white-POV centipawn evals (null on mate)\n"
                "  • mate_before / mate_after — signed mate-in-N (null otherwise)\n"
                "  • eval_swing_cp — centipawn loss for the side to move (positive = bad)\n"
                "  • classification — blunder / mistake / inaccuracy / good\n"
                "  • phase — opening / middlegame / endgame\n"
                "  • candidates — top-N moves (from engine_lines cache) each with eval_cp, "
                "mate, move_san, move_uci, pv_san, pv_uci\n"
                "  • motif_evidence — list of {tag, squares, pieces, exploiting_move, line_san} "
                "for every motif tag found at this ply\n\n"
                "IMPORTANT — you must use ONLY the facts returned here. Do NOT evaluate the "
                "position yourself or substitute your own judgment about which move is better. "
                "Explain (a) what idea or tactic was missed (conceptually), and (b) the concrete "
                "line that refutes the played move, citing the squares and pieces listed in "
                "motif_evidence. If motif_evidence is empty, explain from eval_swing and "
                "the candidate lines alone."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "game_id": {"type": "integer", "description": "Game database ID"},
                    "ply": {"type": "integer", "description": "Ply index (0-based)"},
                    "multipv": {
                        "type": "integer",
                        "default": 3,
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Number of candidate moves to include (default 3)",
                    },
                },
                "required": ["game_id", "ply"],
            },
        ),
    ]


# ── tool implementations ─────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        result = _dispatch(name, arguments)
        return [types.TextContent(type="text", text=_json(result))]
    except ValueError as e:
        return [types.TextContent(type="text", text=_json({"error": str(e)}))]


def _dispatch(name: str, args: dict) -> Any:
    if name == "list_games":
        return _list_games(args)
    elif name == "get_game_pgn":
        return _get_game_pgn(args)
    elif name == "get_game_analysis":
        return _get_game_analysis(args)
    elif name == "get_mistake_history":
        return _get_mistake_history(args)
    elif name == "get_top_patterns":
        return _get_top_patterns(args)
    elif name == "next_puzzle":
        return _next_puzzle(args)
    elif name == "submit_puzzle_attempt":
        return _submit_puzzle_attempt(args)
    elif name == "evaluate_position":
        return _mcp_evaluate_position(args)
    elif name == "explore_line":
        return _mcp_explore_line(args)
    elif name == "explain_move":
        return _mcp_explain_move(args)
    else:
        raise ValueError(f"Unknown tool: {name}")


def _list_games(args: dict) -> dict:
    username = args["username"].strip().lower()
    limit = min(int(args.get("limit", 20)), 100)
    offset = int(args.get("offset", 0))
    result_filter = args.get("result")
    tc_filter = args.get("time_control")

    with conn_ctx() as conn:
        if not conn.execute(
            "SELECT 1 FROM players WHERE username = ?", (username,)
        ).fetchone():
            raise ValueError(f"Player '{username}' not found. Run sync first.")

        conditions = ["player_username = ?"]
        params: list = [username]
        if result_filter:
            conditions.append("result = ?")
            params.append(result_filter)
        if tc_filter:
            conditions.append("time_control = ?")
            params.append(tc_filter)

        where = " AND ".join(conditions)
        total = conn.execute(
            f"SELECT COUNT(*) FROM games WHERE {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, chesscom_id, played_at, time_control, white, black, result, eco, opening_name"
            f" FROM games WHERE {where} ORDER BY played_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {
        "username": username,
        "total": total,
        "limit": limit,
        "offset": offset,
        "games": [dict(r) for r in rows],
    }


def _get_game_pgn(args: dict) -> dict:
    game_id = int(args["game_id"])
    with conn_ctx() as conn:
        row = conn.execute(
            "SELECT id, white, black, result, played_at, pgn FROM games WHERE id = ?",
            (game_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"Game {game_id} not found.")
    return dict(row)


def _get_game_analysis(args: dict) -> dict:
    game_id = int(args["game_id"])
    with conn_ctx() as conn:
        if not conn.execute("SELECT 1 FROM games WHERE id = ?", (game_id,)).fetchone():
            raise ValueError(f"Game {game_id} not found.")
        rows = conn.execute(
            "SELECT ply, fen, best_move, played_move, eval_cp, classification, motif_tags, phase"
            " FROM analyses WHERE game_id = ? ORDER BY ply",
            (game_id,),
        ).fetchall()

    plies = []
    for r in rows:
        d = dict(r)
        try:
            d["motif_tags"] = json.loads(d["motif_tags"]) if d["motif_tags"] else []
        except (json.JSONDecodeError, TypeError):
            d["motif_tags"] = []
        plies.append(d)

    return {"game_id": game_id, "plies": plies}


def _get_mistake_history(args: dict) -> dict:
    username = args["username"].strip().lower()
    limit = min(int(args.get("limit", 20)), 100)
    classification = args.get("classification")

    if classification:
        allowed = {"blunder", "mistake", "inaccuracy"}
        if classification not in allowed:
            raise ValueError(f"classification must be one of {allowed}")
        class_filter = f"= '{classification}'"
    else:
        class_filter = "IN ('blunder', 'mistake')"

    with conn_ctx() as conn:
        if not conn.execute(
            "SELECT 1 FROM players WHERE username = ?", (username,)
        ).fetchone():
            raise ValueError(f"Player '{username}' not found.")

        rows = conn.execute(
            f"SELECT a.game_id, a.ply, a.fen, a.best_move, a.played_move,"
            f"       a.eval_cp, a.classification, a.motif_tags, a.phase,"
            f"       g.played_at, g.white, g.black"
            f" FROM analyses a JOIN games g ON g.id = a.game_id"
            f" WHERE g.player_username = ? AND a.classification {class_filter}"
            f" ORDER BY g.played_at DESC, a.ply LIMIT ?",
            (username, limit),
        ).fetchall()

    mistakes = []
    for r in rows:
        d = dict(r)
        try:
            d["motif_tags"] = json.loads(d["motif_tags"]) if d["motif_tags"] else []
        except (json.JSONDecodeError, TypeError):
            d["motif_tags"] = []
        mistakes.append(d)

    return {"username": username, "count": len(mistakes), "mistakes": mistakes}


def _get_top_patterns(args: dict) -> dict:
    username = args["username"].strip().lower()
    top_n = min(int(args.get("top_n", 5)), 20)

    with conn_ctx() as conn:
        if not conn.execute(
            "SELECT 1 FROM players WHERE username = ?", (username,)
        ).fetchone():
            raise ValueError(f"Player '{username}' not found.")

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

    patterns = sorted(
        games_per_motif.keys(),
        key=lambda m: len(games_per_motif[m]),
        reverse=True,
    )[:top_n]

    return {
        "username": username,
        "patterns": [
            {
                "motif": m,
                "games_affected": len(games_per_motif[m]),
                "example_fens": examples[m],
            }
            for m in patterns
        ],
    }


def _next_puzzle(args: dict) -> dict:
    username = args["username"].strip().lower()
    motif = args.get("motif")

    with conn_ctx() as conn:
        if not conn.execute(
            "SELECT 1 FROM players WHERE username = ?", (username,)
        ).fetchone():
            raise ValueError(f"Player '{username}' not found.")

        if motif and motif not in _MOTIF_TO_LICHESS:
            raise ValueError(f"Unknown motif '{motif}'. Known: {list(_MOTIF_TO_LICHESS)}")

        target_motif = motif
        if not target_motif:
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

        # Prefer Lichess puzzle matching the motif
        if target_motif:
            lichess_themes = _MOTIF_TO_LICHESS[target_motif]
            like_clauses = " OR ".join("themes LIKE ?" for _ in lichess_themes)
            like_params = [f"%{t}%" for t in lichess_themes]
            puzzle_row = conn.execute(
                f"SELECT id, fen, solution_moves, themes FROM puzzles"
                f" WHERE ({like_clauses})"
                f" ORDER BY RANDOM() LIMIT 1",
                like_params,
            ).fetchone()
            if puzzle_row:
                try:
                    themes_list = json.loads(puzzle_row["themes"])
                except (json.JSONDecodeError, TypeError):
                    themes_list = []
                return {
                    "type": "lichess_puzzle",
                    "puzzle_id": puzzle_row["id"],
                    "fen": puzzle_row["fen"],
                    "solution_moves": puzzle_row["solution_moves"].split(),
                    "themes": themes_list,
                    "motif": target_motif,
                }

        # Fall back to own-game pre-blunder position
        own_params: list = [username]
        own_where = "g.player_username = ? AND a.classification IN ('blunder', 'mistake')"
        if target_motif:
            own_where += " AND a.motif_tags LIKE ?"
            own_params.append(f"%{target_motif}%")
        own_row = conn.execute(
            f"SELECT a.game_id, a.ply, a.fen, a.best_move, a.played_move,"
            f"       a.classification, a.motif_tags"
            f" FROM analyses a JOIN games g ON g.id = a.game_id"
            f" WHERE {own_where}"
            f" ORDER BY RANDOM() LIMIT 1",
            own_params,
        ).fetchone()
        if own_row:
            try:
                tags = json.loads(own_row["motif_tags"] or "[]")
            except (json.JSONDecodeError, TypeError):
                tags = []
            return {
                "type": "own_game",
                "game_id": own_row["game_id"],
                "ply": own_row["ply"],
                "fen": own_row["fen"],
                "best_move": own_row["best_move"],
                "played_move": own_row["played_move"],
                "classification": own_row["classification"],
                "motif_tags": tags,
                "motif": target_motif,
            }

        raise ValueError("No puzzles found. Import the Lichess puzzle DB or analyze some games first.")


def _submit_puzzle_attempt(args: dict) -> dict:
    username = args["username"].strip().lower()
    puzzle_id = str(args["puzzle_id"])
    solved = bool(args["solved"])
    now = datetime.now(timezone.utc).isoformat()

    with conn_ctx() as conn:
        if not conn.execute(
            "SELECT 1 FROM players WHERE username = ?", (username,)
        ).fetchone():
            raise ValueError(f"Player '{username}' not found.")
        if not conn.execute(
            "SELECT 1 FROM puzzles WHERE id = ?", (puzzle_id,)
        ).fetchone():
            raise ValueError(f"Puzzle '{puzzle_id}' not found.")
        cur = conn.execute(
            "INSERT INTO puzzle_attempts (puzzle_id, username, solved, attempted_at)"
            " VALUES (?, ?, ?, ?)",
            (puzzle_id, username, int(solved), now),
        )
        attempt_id = cur.lastrowid

    return {
        "id": attempt_id,
        "puzzle_id": puzzle_id,
        "username": username,
        "solved": solved,
        "attempted_at": now,
    }


def _uci_to_san(board: chess.Board, uci_moves: list) -> list:
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


def _format_lines(board: chess.Board, raw_lines: list) -> list:
    lines = []
    for line in raw_lines:
        move_uci = line["move_uci"]
        try:
            move_san = board.san(chess.Move.from_uci(move_uci)) if move_uci else ""
        except (ValueError, AssertionError):
            move_san = move_uci
        pv_uci = line["pv"]
        pv_san = _uci_to_san(board, pv_uci)
        lines.append({
            "rank": line["rank"],
            "move_uci": move_uci,
            "move_san": move_san,
            "eval_cp": line["eval_cp"],
            "mate": line["mate"],
            "pv_uci": pv_uci,
            "pv_san": pv_san,
        })
    return lines


def _mcp_evaluate_position(args: dict) -> dict:
    fen = args["fen"]
    depth = min(int(args.get("depth", 18)), 30)
    multipv = min(int(args.get("multipv", 3)), 10)

    try:
        board = chess.Board(fen)
    except ValueError as e:
        raise ValueError(f"invalid FEN: {e}") from e

    raw_lines = _evaluate_position(fen, depth=depth, multipv=multipv)
    actual_depth = raw_lines[0]["depth"] if raw_lines else depth
    return {
        "fen": fen,
        "depth": actual_depth,
        "lines": _format_lines(board, raw_lines),
    }


def _mcp_explore_line(args: dict) -> dict:
    fen = args["fen"]
    moves = args["moves"]
    depth = min(int(args.get("depth", 18)), 30)
    multipv = min(int(args.get("multipv", 1)), 5)

    try:
        board = chess.Board(fen)
    except ValueError as e:
        raise ValueError(f"invalid starting FEN: {e}") from e

    applied: list[str] = []
    for mv in moves:
        move = None
        # Try UCI first, then SAN.
        try:
            candidate = chess.Move.from_uci(mv)
            if candidate in board.legal_moves:
                move = candidate
        except ValueError:
            pass
        if move is None:
            try:
                move = board.parse_san(mv)
            except ValueError:
                pass
        if move is None:
            raise ValueError(
                f"illegal or unparseable move '{mv}' after {applied} in position {board.fen()}"
            )
        applied.append(board.san(move))
        board.push(move)

    result_fen = board.fen()
    raw_lines = _evaluate_position(result_fen, depth=depth, multipv=multipv)
    actual_depth = raw_lines[0]["depth"] if raw_lines else depth

    return {
        "starting_fen": fen,
        "moves_applied_san": applied,
        "result_fen": result_fen,
        "depth": actual_depth,
        "lines": _format_lines(board, raw_lines),
    }


def _mcp_explain_move(args: dict) -> dict:
    game_id = int(args["game_id"])
    ply = int(args["ply"])
    multipv = min(int(args.get("multipv", 3)), 5)

    with conn_ctx() as conn:
        game_row = conn.execute(
            "SELECT id, white, black, result, played_at, time_control FROM games WHERE id = ?",
            (game_id,),
        ).fetchone()
        if not game_row:
            raise ValueError(f"Game {game_id} not found.")

        row = conn.execute(
            "SELECT ply, fen, best_move, played_move, eval_cp, classification,"
            "       motif_tags, phase, pv, motif_details"
            " FROM analyses WHERE game_id = ? AND ply = ?",
            (game_id, ply),
        ).fetchone()
        if not row:
            raise ValueError(f"No analysis found for game {game_id} ply {ply}. Run analyze first.")

        # Also fetch ply-1 (the position before the move) to get eval_before
        prev_row = conn.execute(
            "SELECT eval_cp FROM analyses WHERE game_id = ? AND ply = ?",
            (game_id, ply - 1),
        ).fetchone() if ply > 0 else None

    d = dict(row)
    fen = d["fen"]
    played_move_uci = d.get("played_move") or ""
    best_move_uci = d.get("best_move") or ""
    eval_after = d.get("eval_cp")  # eval after the move was played (from analysis)
    eval_before = prev_row["eval_cp"] if prev_row else None

    # Parse motif tags and details
    try:
        motif_tags = json.loads(d["motif_tags"]) if d["motif_tags"] else []
    except (json.JSONDecodeError, TypeError):
        motif_tags = []

    try:
        motif_details_raw = json.loads(d["motif_details"]) if d.get("motif_details") else {}
    except (json.JSONDecodeError, TypeError):
        motif_details_raw = {}

    # Compute SAN representations from FEN
    try:
        board = chess.Board(fen)
    except ValueError as e:
        raise ValueError(f"Stored FEN is invalid: {e}") from e

    def uci_to_san_safe(uci: str) -> str:
        if not uci:
            return ""
        try:
            return board.san(chess.Move.from_uci(uci))
        except (ValueError, AssertionError):
            return uci

    played_move_san = uci_to_san_safe(played_move_uci)
    best_move_san = uci_to_san_safe(best_move_uci)

    # Centipawn swing: positive = bad for the side who played (mover perspective)
    swing: int | None = None
    if eval_before is not None and eval_after is not None:
        # If it's white's turn at this ply, white-pov drop is bad for white
        is_white_turn = board.turn == chess.WHITE
        if is_white_turn:
            swing = eval_before - eval_after
        else:
            swing = eval_after - eval_before

    # Motif evidence — restructure for readability
    motif_evidence = []
    for tag in motif_tags:
        ev = motif_details_raw.get(tag, {})
        entry: dict = {"tag": tag}
        if ev.get("squares"):
            entry["squares"] = ev["squares"]
        if ev.get("pieces"):
            entry["pieces"] = ev["pieces"]
        if ev.get("exploiting_move"):
            entry["exploiting_move"] = ev["exploiting_move"]
            entry["exploiting_move_san"] = uci_to_san_safe(ev["exploiting_move"])
        if ev.get("line"):
            entry["line_san"] = _uci_to_san(board, ev["line"])
            entry["line_uci"] = ev["line"]
        motif_evidence.append(entry)

    # Candidate moves from engine_lines cache (or fallback to best_move only)
    raw_lines = _evaluate_position(fen, depth=18, multipv=multipv)
    candidates = _format_lines(board, raw_lines)

    return {
        "game_id": game_id,
        "ply": ply,
        "game": {
            "white": game_row["white"],
            "black": game_row["black"],
            "result": game_row["result"],
            "played_at": game_row["played_at"],
            "time_control": game_row["time_control"],
        },
        "fen": fen,
        "played_move_san": played_move_san,
        "played_move_uci": played_move_uci,
        "best_move_san": best_move_san,
        "best_move_uci": best_move_uci,
        "eval_before_cp": eval_before,
        "eval_after_cp": eval_after,
        "mate_before": None,
        "mate_after": None,
        "eval_swing_cp": swing,
        "classification": d.get("classification"),
        "phase": d.get("phase"),
        "motif_tags": motif_tags,
        "motif_evidence": motif_evidence,
        "candidates": candidates,
    }


# ── entrypoint ───────────────────────────────────────────────────────────────

async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
