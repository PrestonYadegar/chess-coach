"""Heuristic motif tagger — assigns pattern labels to blunder/mistake/inaccuracy moves.

Tactical detectors run on every classified mistake. The two phase-context tags
(endgame_technique, opening_principle) only fire when no tactical motif did,
so they act as last-resort catch-alls rather than crowding the chart.
"""

import json
from typing import List, Optional

import chess


PIECE_VALUE = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}


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


def _is_hanging(board: chess.Board, sq: chess.Square, color: chess.Color) -> bool:
    if not board.attackers(not color, sq):
        return False
    return not board.attackers(color, sq)


def _check_hanging_piece(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    """Player left the moved piece hanging, OR missed capturing a free opponent piece."""
    board_after = board_before.copy()
    board_after.push(played_move)

    if _is_hanging(board_after, played_move.to_square, mover):
        return True

    opp = not mover
    for sq in chess.SQUARES:
        p = board_before.piece_at(sq)
        if p is None or p.color != opp or p.piece_type == chess.KING:
            continue
        if board_before.attackers(mover, sq) and not board_before.attackers(opp, sq):
            if played_move.to_square != sq:
                return True

    return False


def _check_fork_missed(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> bool:
    if best_move is None or best_move == played_move:
        return False

    board_best = board_before.copy()
    board_best.push(best_move)
    to_sq = best_move.to_square

    opp = not mover
    attacked = sum(
        1
        for sq in chess.SQUARES
        if (p := board_best.piece_at(sq)) is not None
        and p.color == opp
        and p.piece_type != chess.KING
        and to_sq in board_best.attackers(mover, sq)
    )
    if attacked < 2:
        return False

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
    return attacked_play < 2


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


def _has_skewer(
    board: chess.Board, from_sq: chess.Square, color: chess.Color
) -> bool:
    p = board.piece_at(from_sq)
    if p is None or p.piece_type not in _RAYS:
        return False
    for front_sq, back_sq in _skewer_pairs(board, from_sq, p.piece_type, color):
        fp = board.piece_at(front_sq)
        bp = board.piece_at(back_sq)
        if fp is None or bp is None:
            continue
        # Front must be at least as valuable as back (definition of skewer);
        # king-in-front is the absolute skewer case and always counts.
        if PIECE_VALUE[fp.piece_type] >= PIECE_VALUE[bp.piece_type]:
            return True
    return False


def _check_skewer_missed(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> bool:
    """Best move would land a long-range piece on a skewer line; played move doesn't."""
    if best_move is None or best_move == played_move:
        return False
    p = board_before.piece_at(best_move.from_square)
    if p is None or p.piece_type not in _RAYS:
        return False

    board_best = board_before.copy()
    board_best.push(best_move)
    if not _has_skewer(board_best, best_move.to_square, mover):
        return False

    board_play = board_before.copy()
    board_play.push(played_move)
    return not _has_skewer(board_play, played_move.to_square, mover)


def _check_back_rank(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    board_after = board_before.copy()
    board_after.push(played_move)

    king_sq = board_after.king(mover)
    if king_sq is None:
        return False

    back_rank = 0 if mover == chess.WHITE else 7
    if chess.square_rank(king_sq) != back_rank:
        return False

    opp = not mover
    king_file = chess.square_file(king_sq)

    shield_rank = 1 if mover == chess.WHITE else 6
    shield_squares = [
        chess.square(f, shield_rank)
        for f in range(max(0, king_file - 1), min(8, king_file + 2))
    ]
    pawn_count = sum(
        1 for sq in shield_squares
        if (p := board_after.piece_at(sq)) is not None
        and p.color == mover
        and p.piece_type == chess.PAWN
    )
    if pawn_count < len(shield_squares):
        return False

    for sq in chess.SQUARES:
        p = board_after.piece_at(sq)
        if p is None or p.color != opp:
            continue
        if p.piece_type not in (chess.ROOK, chess.QUEEN):
            continue
        if chess.square_rank(sq) == back_rank:
            return True
        if board_after.is_attacked_by(opp, king_sq):
            return True

    return False


def _check_pin_missed(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> bool:
    if best_move is None or best_move == played_move:
        return False

    moving_piece = board_before.piece_at(best_move.from_square)
    if moving_piece is None or moving_piece.piece_type not in (
        chess.BISHOP, chess.ROOK, chess.QUEEN
    ):
        return False

    opp = not mover

    board_best = board_before.copy()
    board_best.push(best_move)

    board_play = board_before.copy()
    board_play.push(played_move)

    def pinned_count(b: chess.Board) -> int:
        return sum(
            1 for sq in chess.SQUARES
            if (p := b.piece_at(sq)) is not None
            and p.color == opp and b.is_pinned(opp, sq)
        )

    return pinned_count(board_best) > pinned_count(board_play)


def _check_discovered_attack(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    opp = not mover
    to_sq = played_move.to_square

    board_after = board_before.copy()
    board_after.push(played_move)

    for sq in chess.SQUARES:
        p = board_after.piece_at(sq)
        if p is None or p.color != opp or p.piece_type == chess.KING:
            continue

        before_att = board_before.attackers(mover, sq)
        after_att = board_after.attackers(mover, sq)

        new_att = set(after_att) - set(before_att)
        for att_sq in new_att:
            if att_sq != to_sq:
                return True

    return False


def _check_overloaded(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> bool:
    """Best move captures a piece whose defender also defends another piece we
    attack — pulling the defender off its second duty. Played move doesn't take
    this capture."""
    if best_move is None or best_move == played_move:
        return False
    if not board_before.is_capture(best_move):
        return False

    target_sq = best_move.to_square
    target_piece = board_before.piece_at(target_sq)
    if target_piece is None or target_piece.color == mover:
        return False

    opp = not mover
    defenders = board_before.attackers(opp, target_sq)
    if not defenders:
        return False

    for def_sq in defenders:
        for sq in chess.SQUARES:
            if sq == target_sq:
                continue
            p = board_before.piece_at(sq)
            if p is None or p.color != opp or p.piece_type == chess.KING:
                continue
            # Same defender also defends `sq`, AND we attack `sq`. Capturing
            # target_sq forces the defender to either recapture or save `sq`,
            # not both.
            if def_sq in board_before.attackers(opp, sq) and board_before.attackers(
                mover, sq
            ):
                return True

    return False


def _check_intermezzo_missed(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> bool:
    """Best move is a forcing check that the player ignored to play an 'obvious'
    recapture instead — the classic zwischenzug pattern."""
    if best_move is None or best_move == played_move:
        return False
    if not board_before.gives_check(best_move):
        return False
    if board_before.gives_check(played_move):
        return False
    # The "missed intermezzo" framing requires the played move to look like the
    # obvious continuation — typically a recapture.
    return board_before.is_capture(played_move)


def _check_only_move_missed(
    score_before: Optional["chess.engine.PovScore"],
    second_pv_score: Optional["chess.engine.PovScore"],
    played_move: chess.Move,
    best_move: Optional[chess.Move],
) -> bool:
    """The position had one stand-out move (≥ 2-pawn gap to the runner-up) and
    the player chose something else. Captures the 'only defense missed'
    pattern — but also fires when there's a single winning shot."""
    if (
        best_move is None
        or second_pv_score is None
        or score_before is None
        or played_move == best_move
    ):
        return False
    # Mate situations are owned by the mating-net detectors.
    if score_before.is_mate() or second_pv_score.is_mate():
        return False
    sb = score_before.score()
    s2 = second_pv_score.score()
    if sb is None or s2 is None:
        return False
    return (sb - s2) >= 200


def _check_mating_net_missed(
    score_before: Optional["chess.engine.PovScore"],
    score_after: Optional["chess.engine.PovScore"],
) -> bool:
    """Best line had a forced mate FOR the mover; played move threw it away."""
    if score_before is None or not score_before.is_mate():
        return False
    m = score_before.mate()
    if m is None or m <= 0:
        return False
    if score_after is not None and score_after.is_mate():
        m_after = score_after.mate()
        if m_after is not None and m_after > 0:
            return False  # still mating, just a delay
    return True


def _check_mating_net_allowed(
    score_before: Optional["chess.engine.PovScore"],
    score_after: Optional["chess.engine.PovScore"],
) -> bool:
    """Position was not already lost-to-mate; played move now is."""
    if score_before is not None and score_before.is_mate():
        m = score_before.mate()
        if m is not None and m < 0:
            return False  # already getting mated, not a fresh blunder
    if score_after is None or not score_after.is_mate():
        return False
    m_after = score_after.mate()
    return m_after is not None and m_after < 0


def _check_king_safety(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    board_after = board_before.copy()
    board_after.push(played_move)

    king_sq = board_after.king(mover)
    if king_sq is None:
        return False

    opp = not mover
    # Only treat as a castled-king position if the king is on a typical
    # castled square. Otherwise the e-pawn push from the start would always
    # count as breaking the pawn shield, which it isn't.
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
            return True

    if played_move.from_square == board_before.king(mover):
        attackers_on_dest = len(board_after.attackers(opp, king_sq))
        if attackers_on_dest >= 2:
            return True

    return False


def _pawn_weakness_count(board: chess.Board, color: chess.Color) -> int:
    """Doubled + isolated pawns for `color`. Backward pawn detection is skipped
    (hard to do without false positives at heuristic speed)."""
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


def _check_pawn_structure(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    """The move left mover's pawn structure measurably worse (doubled/isolated)."""
    board_after = board_before.copy()
    board_after.push(played_move)
    return _pawn_weakness_count(board_after, mover) > _pawn_weakness_count(
        board_before, mover
    )


# ── Catch-alls (only fire when no tactical motif did) ───────────────────────


def _check_endgame_technique(board_before: chess.Board) -> bool:
    """Pure-pawn or near-pure-pawn endgame mistake — actual technique failure."""
    # No pieces other than king + pawn for either side
    for color in (chess.WHITE, chess.BLACK):
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            if board_before.pieces(pt, color):
                return False
    return True


def _check_opening_principle(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    if board_before.fullmove_number > 12:
        return False

    piece = board_before.piece_at(played_move.from_square)
    if piece is None:
        return False

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
                return True

    if piece.piece_type == chess.QUEEN and board_before.fullmove_number <= 5:
        undeveloped = sum(
            1 for sq in chess.SQUARES
            if (p := board_before.piece_at(sq)) is not None
            and p.color == mover
            and p.piece_type in (chess.KNIGHT, chess.BISHOP)
            and chess.square_rank(sq) == start_rank
        )
        if undeveloped >= 2:
            return True

    return False


# ── Orchestrator ────────────────────────────────────────────────────────────


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
    """Return heuristic motif tags for a classified mistake move.

    Scores are all from the mover's point of view. `score_after` is the eval
    AFTER `played_move` from the same mover's POV (engine returns it from the
    new side-to-move's POV, so the caller flips it).
    """
    if classification not in ("blunder", "mistake", "inaccuracy"):
        return []

    mover = board_before.turn
    tags: List[str] = []

    checks = [
        ("hanging_piece", lambda: _check_hanging_piece(board_before, played_move, mover)),
        ("fork_missed", lambda: _check_fork_missed(board_before, played_move, best_move, mover)),
        ("skewer_missed", lambda: _check_skewer_missed(board_before, played_move, best_move, mover)),
        ("pin_missed", lambda: _check_pin_missed(board_before, played_move, best_move, mover)),
        ("back_rank", lambda: _check_back_rank(board_before, played_move, mover)),
        ("discovered_attack", lambda: _check_discovered_attack(board_before, played_move, mover)),
        ("overloaded_piece", lambda: _check_overloaded(board_before, played_move, best_move, mover)),
        ("intermezzo_missed", lambda: _check_intermezzo_missed(board_before, played_move, best_move, mover)),
        ("only_move_missed", lambda: _check_only_move_missed(score_before, second_pv_score, played_move, best_move)),
        ("mating_net_missed", lambda: _check_mating_net_missed(score_before, score_after)),
        ("mating_net_allowed", lambda: _check_mating_net_allowed(score_before, score_after)),
        ("king_safety", lambda: _check_king_safety(board_before, played_move, mover)),
        ("pawn_structure", lambda: _check_pawn_structure(board_before, played_move, mover)),
    ]

    for name, fn in checks:
        try:
            if fn():
                tags.append(name)
        except Exception:
            pass

    # Catch-alls only fire when no specific motif did — otherwise they'd
    # crowd the chart with phase context that's already covered by `phase`.
    if not tags:
        if phase == "endgame":
            try:
                if _check_endgame_technique(board_before):
                    tags.append("endgame_technique")
            except Exception:
                pass
        elif phase == "opening":
            try:
                if _check_opening_principle(board_before, played_move, mover):
                    tags.append("opening_principle")
            except Exception:
                pass

    return tags


def encode_tags(tags: List[str]) -> Optional[str]:
    return json.dumps(tags) if tags else None
