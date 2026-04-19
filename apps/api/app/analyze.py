"""Stockfish per-ply analysis for a single game."""
import io
import shutil
import sqlite3
from typing import Optional

import chess
import chess.engine
import chess.pgn

from .motif import encode_tags, tag_motifs


STOCKFISH_PATH = shutil.which("stockfish")
DEFAULT_DEPTH = 18


def _classify(eval_before_cp: Optional[int], eval_after_cp: Optional[int]) -> str:
    """Classify a move based on centipawn swing from the player's perspective.

    Both values are from the perspective of the side to move at that ply
    (before the move was played).  eval_before is the engine score before the
    move; eval_after is the score from the opponent's perspective negated so
    it's back in the player's frame.
    """
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


def analyze_game(game_id: int, conn: sqlite3.Connection, depth: int = DEFAULT_DEPTH) -> dict:
    if STOCKFISH_PATH is None:
        raise RuntimeError(
            "stockfish not found on PATH. Install it: brew install stockfish"
        )

    row = conn.execute("SELECT pgn FROM games WHERE id = ?", (game_id,)).fetchone()
    if not row:
        raise ValueError(f"game {game_id} not found")

    pgn_text = row["pgn"]
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError(f"could not parse PGN for game {game_id}")

    # Delete existing analysis rows for idempotency
    conn.execute("DELETE FROM analyses WHERE game_id = ?", (game_id,))

    rows_to_insert = []

    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        board = game.board()
        moves = list(game.mainline_moves())

        # Get eval before first move
        info_before = engine.analyse(board, chess.engine.Limit(depth=depth))
        score_before = info_before["score"].white()

        for ply_index, move in enumerate(moves):
            fen_before = board.fen()
            played_move_uci = move.uci()

            # eval before (from white's perspective)
            if score_before.is_mate():
                eval_before_cp = None
                is_mate_before = True
            else:
                eval_before_cp = score_before.score()
                is_mate_before = False

            # Get best move and its eval
            best_move_uci = info_before.get("pv", [move])[0].uci() if info_before.get("pv") else played_move_uci

            # Make the actual move
            board.push(move)

            # Evaluate after the move (opponent's turn, so negate for player's frame)
            info_after = engine.analyse(board, chess.engine.Limit(depth=depth))
            score_after = info_after["score"].white()

            if score_after.is_mate():
                eval_after_cp = None
                is_mate_after = True
            else:
                eval_after_cp = score_after.score()
                is_mate_after = False

            # Compute classification in the moving side's frame
            # ply_index 0,2,4,... = white moves; 1,3,5,... = black moves
            is_white_move = (ply_index % 2 == 0)
            if is_white_move:
                before_player = eval_before_cp
                # after: board is now black to move; white perspective after move
                after_player = eval_after_cp
            else:
                # negate for black's frame
                before_player = (-eval_before_cp) if eval_before_cp is not None else None
                after_player = (-eval_after_cp) if eval_after_cp is not None else None

            # Mate swings always blunder
            if is_mate_before != is_mate_after or (
                is_mate_before and is_mate_after and before_player != after_player
            ):
                classification = "blunder"
            else:
                classification = _classify(before_player, after_player)

            # Motif tagging (heuristic, only for mistakes/blunders/inaccuracies)
            best_move_obj = chess.Move.from_uci(best_move_uci) if best_move_uci else None
            board_for_tags = chess.Board(fen_before)
            motif_list = tag_motifs(board_for_tags, move, best_move_obj, classification)
            motif_tags_json = encode_tags(motif_list)

            rows_to_insert.append((
                game_id,
                ply_index,
                fen_before,
                best_move_uci,
                played_move_uci,
                eval_after_cp,
                classification,
                motif_tags_json,
            ))

            score_before = info_after["score"].white()

    conn.executemany(
        "INSERT OR REPLACE INTO analyses"
        " (game_id, ply, fen, best_move, played_move, eval_cp, classification, motif_tags)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows_to_insert,
    )

    return {"game_id": game_id, "plies_analyzed": len(rows_to_insert)}
