"""Heuristic motif tagger — assigns pattern labels to blunder/mistake/inaccuracy moves."""

import json
from typing import List, Optional

import chess


def _material_count(board: chess.Board) -> int:
    values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
    return sum(
        len(board.pieces(pt, c)) * v
        for pt, v in values.items()
        for c in (chess.WHITE, chess.BLACK)
    )


def _is_hanging(board: chess.Board, sq: chess.Square, color: chess.Color) -> bool:
    """Piece of `color` on `sq` is attacked and has zero defenders."""
    if not board.attackers(not color, sq):
        return False
    return not board.attackers(color, sq)


def _check_hanging_piece(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    """Player left the moved piece hanging, OR missed capturing a free opponent piece."""
    board_after = board_before.copy()
    board_after.push(played_move)

    # Piece that moved is now hanging
    if _is_hanging(board_after, played_move.to_square, mover):
        return True

    # Opponent had a free piece to capture that we didn't take
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
    """Best move creates a fork (attacks ≥2 opponent pieces); played move doesn't."""
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

    # Confirm played move doesn't achieve the same
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


def _check_back_rank(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    """After the move, the player's king is vulnerable to a back-rank tactic."""
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

    # Are pawns directly in front of the king blocking escape?
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
        return False  # King can escape; not a back-rank trap

    # Is there an opponent rook/queen that can slide to the back rank?
    for sq in chess.SQUARES:
        p = board_after.piece_at(sq)
        if p is None or p.color != opp:
            continue
        if p.piece_type not in (chess.ROOK, chess.QUEEN):
            continue
        if chess.square_rank(sq) == back_rank:
            return True  # Already on the back rank, danger
        # Check if it attacks king_sq (i.e., clear path on the file)
        if board_after.is_attacked_by(opp, king_sq):
            return True

    return False


def _check_pin_missed(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    mover: chess.Color,
) -> bool:
    """Best move creates a new pin on an opponent piece; played move doesn't."""
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
        return sum(1 for sq in chess.SQUARES if (p := b.piece_at(sq)) is not None
                   and p.color == opp and b.is_pinned(opp, sq))

    return pinned_count(board_best) > pinned_count(board_play)


def _check_discovered_attack(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    """Moving a piece opens an attack by another friendly piece behind it."""
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
        # New attacker is not the piece that just moved → discovered
        for att_sq in new_att:
            if att_sq != to_sq:
                return True

    return False


def _check_overloaded(board_before: chess.Board, mover: chess.Color) -> bool:
    """An opponent piece defends two or more pieces we're attacking — it's overloaded."""
    opp = not mover
    duties: dict[chess.Square, int] = {}

    for sq in chess.SQUARES:
        p = board_before.piece_at(sq)
        if p is None or p.color != opp or p.piece_type == chess.KING:
            continue
        if not board_before.attackers(mover, sq):
            continue
        for def_sq in board_before.attackers(opp, sq):
            duties[def_sq] = duties.get(def_sq, 0) + 1

    return any(v >= 2 for v in duties.values())


def _check_king_safety(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    """The move weakens our king's pawn shelter or exposes the king."""
    board_after = board_before.copy()
    board_after.push(played_move)

    king_sq = board_after.king(mover)
    if king_sq is None:
        return False

    opp = not mover
    king_rank = chess.square_rank(king_sq)
    castled_rank = 0 if mover == chess.WHITE else 7

    # If king is on back rank (castled), check pawn shield deterioration
    if king_rank == castled_rank:
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
            return True  # Pawn shield got weaker

    # If king moved to a square heavily attacked by opponent
    if played_move.from_square == board_before.king(mover):
        attackers_on_dest = len(board_after.attackers(opp, king_sq))
        if attackers_on_dest >= 2:
            return True

    return False


def _check_endgame_technique(board_before: chess.Board) -> bool:
    """Position is an endgame (low material or no queens)."""
    wq = len(board_before.pieces(chess.QUEEN, chess.WHITE))
    bq = len(board_before.pieces(chess.QUEEN, chess.BLACK))
    if wq == 0 and bq == 0:
        return True
    return _material_count(board_before) <= 20


def _check_opening_principle(
    board_before: chess.Board, played_move: chess.Move, mover: chess.Color
) -> bool:
    """Violation of basic opening principles (before move 15)."""
    if board_before.fullmove_number > 15:
        return False

    piece = board_before.piece_at(played_move.from_square)
    if piece is None:
        return False

    start_rank = 0 if mover == chess.WHITE else 7

    # Moving a minor piece for the second time while others sit on start rank
    if piece.piece_type in (chess.KNIGHT, chess.BISHOP):
        if chess.square_rank(played_move.from_square) != start_rank:
            # Already moved once; count undeveloped pieces
            undeveloped = sum(
                1 for sq in chess.SQUARES
                if (p := board_before.piece_at(sq)) is not None
                and p.color == mover
                and p.piece_type in (chess.KNIGHT, chess.BISHOP)
                and chess.square_rank(sq) == start_rank
            )
            if undeveloped >= 2:
                return True

    # Early queen move while ≥2 minor pieces are undeveloped
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


def tag_motifs(
    board_before: chess.Board,
    played_move: chess.Move,
    best_move: Optional[chess.Move],
    classification: str,
) -> List[str]:
    """Return heuristic motif tags for a classified mistake move."""
    if classification not in ("blunder", "mistake", "inaccuracy"):
        return []

    mover = board_before.turn
    tags: List[str] = []

    checks = [
        ("hanging_piece", lambda: _check_hanging_piece(board_before, played_move, mover)),
        ("fork_missed", lambda: _check_fork_missed(board_before, played_move, best_move, mover)),
        ("back_rank", lambda: _check_back_rank(board_before, played_move, mover)),
        ("pin_missed", lambda: _check_pin_missed(board_before, played_move, best_move, mover)),
        ("discovered_attack", lambda: _check_discovered_attack(board_before, played_move, mover)),
        ("overloaded_piece", lambda: _check_overloaded(board_before, mover)),
        ("king_safety", lambda: _check_king_safety(board_before, played_move, mover)),
        ("endgame_technique", lambda: _check_endgame_technique(board_before)),
        ("opening_principle", lambda: _check_opening_principle(board_before, played_move, mover)),
    ]

    for name, fn in checks:
        try:
            if fn():
                tags.append(name)
        except Exception:
            pass

    return tags


def encode_tags(tags: List[str]) -> Optional[str]:
    """Encode tag list to JSON string for DB storage, or None if empty."""
    return json.dumps(tags) if tags else None
