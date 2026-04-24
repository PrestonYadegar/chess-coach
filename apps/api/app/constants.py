"""Shared constants for the chess-coach API.

Centralizes engine depths, classification thresholds, and Stockfish config that
were previously duplicated (and occasionally hardcoded) across modules.
"""

# ── Engine search depths ──────────────────────────────────────────────────────
# Auto-analyze and most one-off evaluations use DEFAULT_DEPTH (18). The manual
# batch-analysis JOB default is intentionally shallower (14) for speed; it is
# kept distinct so the two are not accidentally unified.
DEFAULT_DEPTH = 18
JOB_DEFAULT_DEPTH = 14  # manual batch-analyze default; do NOT change to 18
CHAT_DEPTH = 16  # depth for the on-the-fly played-move eval in /chat

# ── Move classification thresholds (centipawn swing, mover POV) ───────────────
BLUNDER_CP = 200
MISTAKE_CP = 100
INACCURACY_CP = 50

# ── Stockfish engine configuration ────────────────────────────────────────────
ENGINE_THREADS = 1
ENGINE_HASH_MB = 128
