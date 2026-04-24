"""Shared motif metadata.

`MOTIF_TO_LICHESS` maps our internal motif tags to Lichess theme keywords used
for LIKE search of the puzzle DB. Previously duplicated byte-for-byte in
main.py and mcp_server.py.
"""

# Map our internal motif tags → Lichess theme keywords (used for LIKE search)
MOTIF_TO_LICHESS: dict[str, list[str]] = {
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
