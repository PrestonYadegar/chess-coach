"""Shared chess move/line formatting helpers.

Shared helpers for turning engine UCI output into SAN and candidate-line dicts.
"""
from typing import Optional

import chess


def uci_to_san(board: chess.Board, uci_moves: list[str]) -> list[str]:
    """Apply UCI moves from `board` (copied) and return SAN strings.

    Stops at the first illegal/unparseable move (returning the SAN collected so
    far), matching the prior callers' behavior.
    """
    b = board.copy()
    san_moves: list[str] = []
    for uci in uci_moves:
        try:
            move = chess.Move.from_uci(uci)
            san_moves.append(b.san(move))
            b.push(move)
        except (ValueError, AssertionError):
            break
    return san_moves


def format_lines(board: chess.Board, raw_lines: list) -> list[dict]:
    """Format engine_cache.evaluate_position output into candidate-line dicts.

    Returns one dict per line:
        {rank, move_uci, move_san, eval_cp, mate, pv_uci, pv_san}
    """
    lines: list[dict] = []
    for line in raw_lines:
        move_uci = line["move_uci"]
        try:
            move_san = board.san(chess.Move.from_uci(move_uci)) if move_uci else ""
        except (ValueError, AssertionError):
            move_san = move_uci
        pv_uci = line["pv"]
        pv_san = uci_to_san(board, pv_uci)
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
