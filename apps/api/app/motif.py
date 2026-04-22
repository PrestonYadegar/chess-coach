"""Heuristic motif tagger — assigns pattern labels to blunder/mistake/inaccuracy moves.

Tactical detectors run on every classified mistake. The two phase-context tags
(endgame_technique, opening_principle) only fire when no tactical motif did,
so they act as last-resort catch-alls rather than crowding the chart.

Each detector now returns either None (did not fire) or a dict of structured
evidence (squares, pieces, exploiting move/line). `tag_motifs` returns the list
of tag names; `tag_motifs_with_details` returns (tags, details_dict).
"""

import json
from typing import Dict, List, Optional, Tuple

import chess


PIECE_VALUE = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}

_PIECE_NAME = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


def _sq_name(sq: chess.Square) -> str:
    return chess.square_name(sq)


def _material_count(board: chess.Board) -> int:
    return sum(
        len(board.pieces(pt, c)) * v
        for pt, v in PIECE_VALUE.items()
        for c in (chess.WHITE, chess.BLACK)
        if pt != chess.KING
    )


def _non_pawn_material(board: chess.Board) -> int:
    return sum(
        len(board.pieces(pt, c)) * v
        for pt, v in [
            (chess.KNIGHT, 3),
            (chess.BISHOP, 3),
            (chess.ROOK, 5),
            (chess.QUEEN, 9),
        ]
        for c in (chess.WHITE, chess.BLACK)
    )


def compute_phase(board: chess.Board) -> str:
    """Classify the position into opening / middlegame / endgame.

    Endgame is decided by remaining non-pawn material — once both sides are
    down to roughly a rook + minor or less, it's an endgame regardless of
    move number. Opening covers the first dozen full moves before material
    starts coming off.
    """
    if _non_pawn_material(board) <= 13:
        return "endgame"
    if board.fullmove_number <= 12:
        return "opening"
    return "middlegame"


# ── Tactical detectors ──────────────────────────────────────────────────────


def _legal_capture_targets(board: chess.Board) -> set:
    """Squares the side-to-move can *legally* capture on.

    Uses legal_moves rather than raw attacker bitboards so a pinned piece — which
    `board.attackers()` still reports as an attacker — is correctly excluded. A
    knight pinned to its own king does not make the enemy piece it "attacks"
    actually capturable.
    """
    return {m.to_square for m in board.legal_moves if board.is_capture(m)}


def _detect_hanging_piece(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> Optional[dict]:
    """Player left the moved piece hanging, OR missed capturing a free opponent piece.

    Both arms gate on *legal* captures (pins respected), not pseudo-legal attacker
    bitboards, to avoid flagging a "free" capture that the only attacker is pinned
    from making.
    """
    opp = not mover

    board_after = board_before.copy()
    board_after.push(played_move)
    to_sq = played_move.to_square

    # Moved piece left hanging: after the move it's the opponent's turn, so a
    # legal capture of to_sq by them — with no defender of ours — means it hangs.
    if to_sq in _legal_capture_targets(board_after) and not board_after.attackers(mover, to_sq):
        p = board_after.piece_at(to_sq)
        return {
            "squares": [_sq_name(to_sq)],
            "piece": _PIECE_NAME.get(p.piece_type, "piece") if p else "piece",
            "reason": "moved_piece_left_hanging",
        }

    # Free capture missed: before the move it's the mover's turn, so check the
    # captures they could *legally* make on an undefended enemy piece but didn't.
    capturable = _legal_capture_targets(board_before)
    for sq in chess.SQUARES:
        p = board_before.piece_at(sq)
        if p is None or p.color != opp or p.piece_type == chess.KING:
            continue
        if sq in capturable and not board_before.attackers(opp, sq):
            if played_move.to_square != sq:
                return {
                    "squares": [_sq_name(sq)],
                    "piece": _PIECE_NAME.get(p.piece_type, "piece"),
                    "reason": "free_capture_missed",
                }

    return None


def _detect_fork_missed(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> Optional[dict]:
    if best_move is None or best_move == played_move:
        return None

    board_best = board_before.copy()
    board_best.push(best_move)
    to_sq = best_move.to_square

    opp = not mover
    forked = [
        sq for sq in chess.SQUARES
        if (p := board_best.piece_at(sq)) is not None
        and p.color == opp
        and p.piece_type != chess.KING
        and to_sq in board_best.attackers(mover, sq)
    ]
    if len(forked) < 2:
        return None

    board_play = board_before.copy()
    board_play.push(played_move)
    to_sq_p = played_move.to_square
    attacked_play = sum(
        1
        for sq in chess.SQUARES
        if (p := board_play.piece_at(sq)) is not None
        and p.color == opp
        and p.piece_type != chess.KING
        and to_sq_p in board_play.attackers(mover, sq)
    )
    if attacked_play >= 2:
        return None

    return {
        "fork_square": _sq_name(to_sq),
        "targets": [_sq_name(sq) for sq in forked[:4]],
        "by_move": best_move.uci(),
    }


_RAYS = {
    chess.BISHOP: [(1, 1), (1, -1), (-1, 1), (-1, -1)],
    chess.ROOK: [(1, 0), (-1, 0), (0, 1), (0, -1)],
    chess.QUEEN: [
        (1, 1), (1, -1), (-1, 1), (-1, -1),
        (1, 0), (-1, 0), (0, 1), (0, -1),
    ],
}


def _skewer_pairs(
    board: chess.Board,
    from_sq: chess.Square,
    piece_type: chess.PieceType,
    color: chess.Color,
) -> list[tuple[chess.Square, chess.Square]]:
    """From `from_sq`, scan rays for two enemy pieces in a row (front, back)."""
    pairs: list[tuple[chess.Square, chess.Square]] = []
    f0 = chess.square_file(from_sq)
    r0 = chess.square_rank(from_sq)
    for dx, dy in _RAYS.get(piece_type, ()):
        front: Optional[chess.Square] = None
        for step in range(1, 8):
            f, r = f0 + dx * step, r0 + dy * step
            if not (0 <= f < 8 and 0 <= r < 8):
                break
            sq = chess.square(f, r)
            p = board.piece_at(sq)
            if p is None:
                continue
            if p.color == color:
                break  # own piece blocks the ray
            if front is None:
                front = sq
                continue
            pairs.append((front, sq))
            break
    return pairs


def _has_skewer_detail(
    board: chess.Board, from_sq: chess.Square, color: chess.Color
) -> Optional[Tuple[chess.Square, chess.Square]]:
    p = board.piece_at(from_sq)
    if p is None or p.piece_type not in _RAYS:
        return None
    for front_sq, back_sq in _skewer_pairs(board, from_sq, p.piece_type, color):
        fp = board.piece_at(front_sq)
        bp = board.piece_at(back_sq)
        if fp is None or bp is None:
            continue
        if PIECE_VALUE[fp.piece_type] >= PIECE_VALUE[bp.piece_type]:
            return (front_sq, back_sq)
    return None


def _detect_skewer_missed(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> Optional[dict]:
    """Best move would land a long-range piece on a skewer line; played move doesn't."""
    if best_move is None or best_move == played_move:
        return None
    p = board_before.piece_at(best_move.from_square)
    if p is None or p.piece_type not in _RAYS:
        return None

    board_best = board_before.copy()
    board_best.push(best_move)
    pair = _has_skewer_detail(board_best, best_move.to_square, mover)
    if pair is None:
        return None

    board_play = board_before.copy()
    board_play.push(played_move)
    if _has_skewer_detail(board_play, played_move.to_square, mover) is not None:
        return None

    front_sq, back_sq = pair
    return {
        "squares": [_sq_name(front_sq), _sq_name(back_sq)],
        "by_move": best_move.uci(),
        "attacker_square": _sq_name(best_move.to_square),
    }


def _detect_back_rank(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> Optional[dict]:
    """Flag only a *real* back-rank threat: the played move lets the opponent
    deliver immediate checkmate with a rook or queen on the mover's back rank.

    A loose "king on the back rank behind its pawns with an enemy rook somewhere
    on that rank" heuristic produced false positives — an enemy rook on the back
    rank that cannot actually mate (king has luft, rook is blocked/defended) is
    not a back-rank motif. Requiring an actual mate-in-1 keeps this honest.
    """
    board_after = board_before.copy()
    board_after.push(played_move)

    king_sq = board_after.king(mover)
    if king_sq is None:
        return None

    back_rank = 0 if mover == chess.WHITE else 7
    if chess.square_rank(king_sq) != back_rank:
        return None

    # It's the opponent's turn in board_after — do they have a checkmating move
    # that lands a rook/queen on the mover's back rank?
    for move in board_after.legal_moves:
        piece = board_after.piece_at(move.from_square)
        if piece is None or piece.piece_type not in (chess.ROOK, chess.QUEEN):
            continue
        if chess.square_rank(move.to_square) != back_rank:
            continue
        board_after.push(move)
        is_mate = board_after.is_checkmate()
        board_after.pop()
        if is_mate:
            return {
                "king_square": _sq_name(king_sq),
                "squares": [_sq_name(move.to_square)],
                "by_move": move.uci(),
                "reason": "back_rank_mate_threat",
            }

    return None


def _detect_pin_missed(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> Optional[dict]:
    if best_move is None or best_move == played_move:
        return None

    moving_piece = board_before.piece_at(best_move.from_square)
    if moving_piece is None or moving_piece.piece_type not in (
        chess.BISHOP, chess.ROOK, chess.QUEEN
    ):
        return None

    opp = not mover

    board_best = board_before.copy()
    board_best.push(best_move)

    board_play = board_before.copy()
    board_play.push(played_move)

    def pinned_pieces(b: chess.Board) -> List[chess.Square]:
        return [
            sq for sq in chess.SQUARES
            if (p := b.piece_at(sq)) is not None
            and p.color == opp and b.is_pinned(opp, sq)
        ]

    pins_best = pinned_pieces(board_best)
    pins_play = pinned_pieces(board_play)

    if len(pins_best) <= len(pins_play):
        return None

    new_pins = [sq for sq in pins_best if sq not in pins_play]
    return {
        "by_move": best_move.uci(),
        "pinned_squares": [_sq_name(sq) for sq in new_pins],
        "attacker_square": _sq_name(best_move.to_square),
    }


def _detect_discovered_attack(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> Optional[dict]:
    opp = not mover
    to_sq = played_move.to_square

    board_after = board_before.copy()
    board_after.push(played_move)

    targets = []
    for sq in chess.SQUARES:
        p = board_after.piece_at(sq)
        if p is None or p.color != opp or p.piece_type == chess.KING:
            continue

        before_att = set(board_before.attackers(mover, sq))
        after_att = set(board_after.attackers(mover, sq))
        new_att = after_att - before_att
        for att_sq in new_att:
            if att_sq != to_sq:
                targets.append({"target": _sq_name(sq), "uncovered_attacker": _sq_name(att_sq)})

    if not targets:
        return None

    return {
        "moved_from": _sq_name(played_move.from_square),
        "moved_to": _sq_name(played_move.to_square),
        "discovered_attacks": targets[:3],
    }


def _detect_overloaded(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> Optional[dict]:
    if best_move is None or best_move == played_move:
        return None
    if not board_before.is_capture(best_move):
        return None

    target_sq = best_move.to_square
    target_piece = board_before.piece_at(target_sq)
    if target_piece is None or target_piece.color == mover:
        return None

    opp = not mover
    defenders = board_before.attackers(opp, target_sq)
    if not defenders:
        return None

    for def_sq in defenders:
        for sq in chess.SQUARES:
            if sq == target_sq:
                continue
            p = board_before.piece_at(sq)
            if p is None or p.color != opp or p.piece_type == chess.KING:
                continue
            if def_sq in board_before.attackers(opp, sq) and board_before.attackers(mover, sq):
                return {
                    "target": _sq_name(target_sq),
                    "overloaded_defender": _sq_name(def_sq),
                    "also_defends": _sq_name(sq),
                    "by_move": best_move.uci(),
                }

    return None


def _detect_intermezzo_missed(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> Optional[dict]:
    if best_move is None or best_move == played_move:
        return None
    if not board_before.gives_check(best_move):
        return None
    if board_before.gives_check(played_move):
        return None
    if not board_before.is_capture(played_move):
        return None
    return {
        "by_move": best_move.uci(),
        "missed_check": True,
    }


def _detect_only_move_missed(
    score_before: Optional["chess.engine.PovScore"],
    second_pv_score: Optional["chess.engine.PovScore"],
    played_move: chess.Move,
    best_move: Optional[chess.Move],
) -> Optional[dict]:
    if (
        best_move is None
        or second_pv_score is None
        or score_before is None
        or played_move == best_move
    ):
        return None
    if score_before.is_mate() or second_pv_score.is_mate():
        return None
    sb = score_before.score()
    s2 = second_pv_score.score()
    if sb is None or s2 is None:
        return None
    if (sb - s2) < 200:
        return None
    return {
        "by_move": best_move.uci(),
        "gap_cp": sb - s2,
    }


def _detect_mating_net_missed(
    score_before: Optional["chess.engine.PovScore"],
    score_after: Optional["chess.engine.PovScore"],
) -> Optional[dict]:
    if score_before is None or not score_before.is_mate():
        return None
    m = score_before.mate()
    if m is None or m <= 0:
        return None
    if score_after is not None and score_after.is_mate():
        m_after = score_after.mate()
        if m_after is not None and m_after > 0:
            return None
    return {"mate_in": m}


def _detect_mating_net_allowed(
    score_before: Optional["chess.engine.PovScore"],
    score_after: Optional["chess.engine.PovScore"],
) -> Optional[dict]:
    if score_before is not None and score_before.is_mate():
        m = score_before.mate()
        if m is not None and m < 0:
            return None
    if score_after is None or not score_after.is_mate():
        return None
    m_after = score_after.mate()
    if m_after is None or m_after >= 0:
        return None
    return {"opponent_mate_in": abs(m_after)}


def _detect_king_safety(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> Optional[dict]:
    board_after = board_before.copy()
    board_after.push(played_move)

    king_sq = board_after.king(mover)
    if king_sq is None:
        return None

    opp = not mover
    castled_squares = (
        (chess.G1, chess.C1) if mover == chess.WHITE else (chess.G8, chess.C8)
    )

    if king_sq in castled_squares:
        shield_rank = 1 if mover == chess.WHITE else 6
        king_file = chess.square_file(king_sq)
        shield_squares = [
            chess.square(f, shield_rank)
            for f in range(max(0, king_file - 1), min(8, king_file + 2))
        ]
        pawns_before = sum(
            1 for sq in shield_squares
            if (p := board_before.piece_at(sq)) is not None
            and p.color == mover and p.piece_type == chess.PAWN
        )
        pawns_after = sum(
            1 for sq in shield_squares
            if (p := board_after.piece_at(sq)) is not None
            and p.color == mover and p.piece_type == chess.PAWN
        )
        if pawns_after < pawns_before:
            return {
                "king_square": _sq_name(king_sq),
                "reason": "pawn_shield_broken",
                "shield_squares": [_sq_name(sq) for sq in shield_squares],
            }

    if played_move.from_square == board_before.king(mover):
        attackers_on_dest = len(board_after.attackers(opp, king_sq))
        if attackers_on_dest >= 2:
            return {
                "king_square": _sq_name(king_sq),
                "reason": "king_moved_into_danger",
                "attacker_count": attackers_on_dest,
            }

    return None


def _pawn_weakness_count(board: chess.Board, color: chess.Color) -> int:
    pawn_squares = board.pieces(chess.PAWN, color)
    file_counts = [0] * 8
    for sq in pawn_squares:
        file_counts[chess.square_file(sq)] += 1
    doubled = sum(c - 1 for c in file_counts if c > 1)
    isolated = 0
    for sq in pawn_squares:
        f = chess.square_file(sq)
        if not any(
            0 <= nf < 8 and file_counts[nf] > 0
            for nf in (f - 1, f + 1)
        ):
            isolated += 1
    return doubled + isolated


def _detect_pawn_structure(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> Optional[dict]:
    board_after = board_before.copy()
    board_after.push(played_move)
    before_count = _pawn_weakness_count(board_before, mover)
    after_count = _pawn_weakness_count(board_after, mover)
    if after_count <= before_count:
        return None
    # Collect newly weakened pawn squares
    weak_after = [
        sq for sq in board_after.pieces(chess.PAWN, mover)
        if _pawn_weakness_count(
            board_after, mover
        ) > before_count
    ]
    return {
        "weaknesses_before": before_count,
        "weaknesses_after": after_count,
        "moved_pawn": _sq_name(played_move.to_square),
    }


# ── Catch-alls (only fire when no tactical motif did) ───────────────────────


def _detect_endgame_technique(board_before: chess.Board) -> Optional[dict]:
    for color in (chess.WHITE, chess.BLACK):
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            if board_before.pieces(pt, color):
                return None
    return {"phase": "endgame"}


def _detect_opening_principle(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> Optional[dict]:
    if board_before.fullmove_number > 12:
        return None

    piece = board_before.piece_at(played_move.from_square)
    if piece is None:
        return None

    start_rank = 0 if mover == chess.WHITE else 7

    if piece.piece_type in (chess.KNIGHT, chess.BISHOP):
        if chess.square_rank(played_move.from_square) != start_rank:
            undeveloped = sum(
                1 for sq in chess.SQUARES
                if (p := board_before.piece_at(sq)) is not None
                and p.color == mover
                and p.piece_type in (chess.KNIGHT, chess.BISHOP)
                and chess.square_rank(sq) == start_rank
            )
            if undeveloped >= 2:
                return {
                    "reason": "moved_developed_piece_with_undeveloped_pieces",
                    "undeveloped_count": undeveloped,
                    "fullmove": board_before.fullmove_number,
                }

    if piece.piece_type == chess.QUEEN and board_before.fullmove_number <= 5:
        undeveloped = sum(
            1 for sq in chess.SQUARES
            if (p := board_before.piece_at(sq)) is not None
            and p.color == mover
            and p.piece_type in (chess.KNIGHT, chess.BISHOP)
            and chess.square_rank(sq) == start_rank
        )
        if undeveloped >= 2:
            return {
                "reason": "early_queen_development",
                "undeveloped_count": undeveloped,
                "fullmove": board_before.fullmove_number,
            }

    return None


# ── Orchestrator ────────────────────────────────────────────────────────────


def tag_motifs_with_details(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    classification: str,
    *,
    score_before: Optional["chess.engine.PovScore"] = None,
    score_after: Optional["chess.engine.PovScore"] = None,
    second_pv_score: Optional["chess.engine.PovScore"] = None,
    phase: str = "middlegame",
) -> Tuple[List[str], Dict[str, dict]]:
    """Return (tags, details) where details maps each tag name to its evidence dict."""
    if classification not in ("blunder", "mistake", "inaccuracy"):
        return [], {}

    mover = board_before.turn
    tags: List[str] = []
    details: Dict[str, dict] = {}

    checks = [
        ("hanging_piece", lambda: _detect_hanging_piece(board_before, played_move, mover)),
        ("fork_missed", lambda: _detect_fork_missed(board_before, played_move, best_move, mover)),
        ("skewer_missed", lambda: _detect_skewer_missed(board_before, played_move, best_move, mover)),
        ("pin_missed", lambda: _detect_pin_missed(board_before, played_move, best_move, mover)),
        ("back_rank", lambda: _detect_back_rank(board_before, played_move, mover)),
        ("discovered_attack", lambda: _detect_discovered_attack(board_before, played_move, mover)),
        ("overloaded_piece", lambda: _detect_overloaded(board_before, played_move, best_move, mover)),
        ("intermezzo_missed", lambda: _detect_intermezzo_missed(board_before, played_move, best_move, mover)),
        ("only_move_missed", lambda: _detect_only_move_missed(score_before, second_pv_score, played_move, best_move)),
        ("mating_net_missed", lambda: _detect_mating_net_missed(score_before, score_after)),
        ("mating_net_allowed", lambda: _detect_mating_net_allowed(score_before, score_after)),
        ("king_safety", lambda: _detect_king_safety(board_before, played_move, mover)),
        ("pawn_structure", lambda: _detect_pawn_structure(board_before, played_move, mover)),
    ]

    for name, fn in checks:
        try:
            evidence = fn()
            if evidence is not None:
                tags.append(name)
                details[name] = evidence
        except Exception:
            pass

    # Catch-alls only fire when no specific motif did.
    if not tags:
        if phase == "endgame":
            try:
                evidence = _detect_endgame_technique(board_before)
                if evidence is not None:
                    tags.append("endgame_technique")
                    details["endgame_technique"] = evidence
            except Exception:
                pass
        elif phase == "opening":
            try:
                evidence = _detect_opening_principle(board_before, played_move, mover)
                if evidence is not None:
                    tags.append("opening_principle")
                    details["opening_principle"] = evidence
            except Exception:
                pass

    return tags, details


def tag_motifs(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    classification: str,
    *,
    score_before: Optional["chess.engine.PovScore"] = None,
    score_after: Optional["chess.engine.PovScore"] = None,
    second_pv_score: Optional["chess.engine.PovScore"] = None,
    phase: str = "middlegame",
) -> List[str]:
    """Return heuristic motif tags for a classified mistake move (tags only)."""
    tags, _ = tag_motifs_with_details(
        board_before, played_move, best_move, classification,
        score_before=score_before, score_after=score_after,
        second_pv_score=second_pv_score, phase=phase,
    )
    return tags


def encode_tags(tags: List[str]) -> Optional[str]:
    return json.dumps(tags) if tags else None
