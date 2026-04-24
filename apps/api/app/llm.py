"""
LLM provider routing — Anthropic, OpenAI, Gemini, Ollama.

API keys are stored encrypted in the `app_settings` DB table using Fernet
symmetric encryption. The encryption key lives in SECRET_KEY env var (or the
.env file next to the api package); it is auto-generated on first boot.
"""

import os
import secrets
from pathlib import Path

import chess
import httpx
from cryptography.fernet import Fernet, InvalidToken

from .db import conn_ctx

# ---------------------------------------------------------------------------
# Secret-key bootstrap
# ---------------------------------------------------------------------------

_ENV_PATH = Path(__file__).parent.parent / ".env"


def _load_or_create_secret_key() -> bytes:
    """Return a URL-safe base64 Fernet key, creating and persisting one if absent."""
    val = os.environ.get("SECRET_KEY", "").strip()
    if val:
        return val.encode()

    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            if line.startswith("SECRET_KEY="):
                key = line.split("=", 1)[1].strip()
                if key:
                    os.environ["SECRET_KEY"] = key
                    return key.encode()

    # Generate a fresh Fernet key (32 random bytes, URL-safe base64-encoded).
    key = Fernet.generate_key().decode()
    os.environ["SECRET_KEY"] = key
    with _ENV_PATH.open("a") as f:
        f.write(f"\nSECRET_KEY={key}\n")
    return key.encode()


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_secret_key())
    return _fernet


# ---------------------------------------------------------------------------
# Encrypt / decrypt helpers
# ---------------------------------------------------------------------------

def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError("Could not decrypt stored value — SECRET_KEY may have changed.")


# ---------------------------------------------------------------------------
# Settings helpers (app_settings table)
# ---------------------------------------------------------------------------

def get_llm_settings() -> dict:
    with conn_ctx() as conn:
        rows = conn.execute(
            "SELECT key, value FROM app_settings WHERE key IN ('llm_provider', 'llm_api_key')"
        ).fetchall()
    data = {r["key"]: r["value"] for r in rows}
    provider = data.get("llm_provider", "")
    has_key = bool(data.get("llm_api_key", ""))
    return {"provider": provider, "has_api_key": has_key}


def save_llm_settings(provider: str, api_key: str) -> None:
    encrypted = encrypt_value(api_key)
    with conn_ctx() as conn:
        conn.execute(
            "INSERT INTO app_settings(key, value) VALUES('llm_provider', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (provider,),
        )
        conn.execute(
            "INSERT INTO app_settings(key, value) VALUES('llm_api_key', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (encrypted,),
        )


def _get_api_key() -> tuple[str, str]:
    """Return (provider, plaintext_api_key). Raises ValueError if not configured."""
    with conn_ctx() as conn:
        rows = conn.execute(
            "SELECT key, value FROM app_settings WHERE key IN ('llm_provider', 'llm_api_key')"
        ).fetchall()
    data = {r["key"]: r["value"] for r in rows}
    provider = data.get("llm_provider", "")
    raw = data.get("llm_api_key", "")
    if not provider or not raw:
        raise ValueError("LLM provider not configured. Visit /settings to set your API key.")
    return provider, decrypt_value(raw)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

CHESS_PRINCIPLES = """\
When analyzing any position, apply these seven principles where relevant:
1. **Material balance**: Raw piece count is the baseline. Equal material shifts focus entirely to the six factors below.
2. **Immediate threats**: Always ask — what is threatening me right now? What else can my opponent do? What else can I do?
3. **King safety**: Often the most critical factor. King safety determines whether to launch a direct attack (e.g. pawn storm with opposite-side castling) or consolidate defensively.
4. **Open lines**: Control of open files, ranks, and diagonals dictates how rooks, queens, and bishops break through or maneuver.
5. **Pawn structure and weak/strong squares**: Pawn chains, backward/isolated pawns, and outposts (strong squares for pieces) form the strategic skeleton of the position.
6. **Center and space**: Control of the four central squares and overall territory — space gives fluidity to your pieces, leaves the opponent cramped.
7. **Development and piece activity**: Which pieces are active, passive, or misplaced? Who has mobilized their army more efficiently?"""

SYSTEM_PROMPT = """\
You are a grandmaster chess coach embedded in a chess analysis app. Do not attempt to calculate variations yourself — Stockfish has already done that. Your job is to translate engine numbers and lines into human strategic concepts.

You will receive:
- The board position as FEN plus a plain-text piece list showing every piece and its exact square — use the piece list as your ground truth for what is where; do not try to parse the FEN yourself
- The user's move and engine's best move, each annotated with from→to squares (e.g. "Ke2 (e1→e2)") so direction is unambiguous, plus the evaluation swing
- Stockfish's top lines with principal variations — each capture move is annotated with the exact piece captured (e.g. "cxd3 (×Rook)") — treat these annotations as ground truth; never contradict them
- A material inventory listing every piece on the board at the start of the position
- Pre-computed tactical motifs (when present) — programmatically detected patterns with exact squares and pieces identified; treat these as verified facts, not suggestions
- The user's question

Rules:
- Never contradict or second-guess the engine evaluation
- Never quote centipawn values or evaluation scores in your response — express them as chess consequences instead ("this drops the knight", "White seizes a decisive advantage", "the position becomes lost") — the user sees the numbers elsewhere; your job is to explain the chess
- Never invent move refutations not present in the provided lines
- When describing a capture, always use the capture annotation provided (e.g. "cxd3 captures the Rook") — never guess what piece is on a square
- Every piece you mention must be found in the piece list — never name a piece on a square unless it appears there
- Move directions (e.g. "king moves toward/away from center") must be derived from the from→to squares in the move annotation, not assumed
- Do NOT make independent positional assessments (e.g. "Black is cramped", "White has space advantage") unless the engine evaluation and piece list together clearly support it — your job is to explain what the engine already calculated, not re-evaluate the position yourself
- Structure your response: first explain why the user's move fails (using the user's move line if provided), then explain what the engine's best move accomplishes instead
- When asked "why doesn't X work?", trace through the principal variation after X to show concretely what fails — don't just say it loses a tempo or misses something abstractly
- Explain in terms of strategic features: piece activity, king safety, pawn structure, tempos, control of files/squares, tactical motifs

""" + CHESS_PRINCIPLES + """

Speak like a patient coach, not an engine readout. Use markdown with short paragraphs. Scale length to the question — a simple "why?" needs 3–4 sentences; a multi-part question about ideas, mistakes, and strengths/weaknesses can go longer, but stay focused and never pad."""


_PIECE_NAMES = {'p': 'Pawn', 'n': 'Knight', 'b': 'Bishop', 'r': 'Rook', 'q': 'Queen', 'k': 'King'}
_MOTIF_LABELS = {
    "hanging_piece": "Hanging Piece",
    "fork_missed": "Fork (missed)",
    "skewer_missed": "Skewer (missed)",
    "pin_missed": "Pin (missed)",
    "back_rank": "Back-rank Weakness",
    "discovered_attack": "Discovered Attack",
    "overloaded_piece": "Overloaded Piece",
    "intermezzo_missed": "Intermezzo / In-between Move (missed)",
    "only_move_missed": "Only Move (missed)",
    "mating_net_missed": "Mating Net (missed)",
    "mating_net_allowed": "Mating Net (allowed)",
    "king_safety": "King Safety",
    "pawn_structure": "Pawn Structure",
    "endgame_technique": "Endgame Technique",
    "opening_principle": "Opening Principle",
}


def _format_motif_context(motif_details: dict, user_color: str | None, fen: str) -> str:
    """Convert motif evidence dicts into human-readable tactical context."""
    if not motif_details:
        return ""

    try:
        board = chess.Board(fen)
    except Exception:
        board = None

    def piece_on(sq_name: str) -> str:
        if board is None:
            return ""
        try:
            sq = chess.parse_square(sq_name)
            p = board.piece_at(sq)
            if p:
                side = "White" if p.color == chess.WHITE else "Black"
                return f" ({side}'s {_PIECE_NAMES[p.symbol().lower()]})"
        except Exception:
            pass
        return ""

    mover_side = user_color.capitalize() if user_color else "the player to move"
    opp_side = ("Black" if user_color == "white" else "White") if user_color else "the opponent"

    lines = []
    for tag, ev in motif_details.items():
        label = _MOTIF_LABELS.get(tag, tag.replace("_", " ").title())
        parts: list[str] = [f"**{label}**"]

        if tag == "hanging_piece":
            sq = ev.get("squares", [None])[0]
            piece = ev.get("piece", "piece")
            reason = ev.get("reason", "")
            if reason == "moved_piece_left_hanging":
                ann = piece_on(sq) if sq else ""
                parts.append(f"{mover_side} left their {piece} hanging on {sq}{ann}.")
            elif reason == "free_capture_missed":
                ann = piece_on(sq) if sq else ""
                parts.append(f"{mover_side} missed capturing a free {opp_side} {piece} on {sq}{ann}.")

        elif tag == "fork_missed":
            fsq = ev.get("fork_square", "?")
            targets = ev.get("targets", [])
            target_desc = " and ".join(
                f"{t}{piece_on(t)}" for t in targets[:2]
            )
            parts.append(
                f"{mover_side} missed a fork: best move lands on {fsq} attacking {target_desc} simultaneously."
            )

        elif tag == "skewer_missed":
            sqs = ev.get("squares", [])
            att = ev.get("attacker_square", "?")
            if len(sqs) >= 2:
                front_ann = piece_on(sqs[0])
                back_ann = piece_on(sqs[1])
                parts.append(
                    f"{mover_side} missed a skewer: piece on {att} would attack {sqs[0]}{front_ann} "
                    f"with {sqs[1]}{back_ann} behind it on the same line."
                )

        elif tag == "pin_missed":
            att = ev.get("attacker_square", "?")
            pinned = ev.get("pinned_squares", [])
            pinned_desc = ", ".join(f"{sq}{piece_on(sq)}" for sq in pinned[:2])
            parts.append(
                f"{mover_side} missed a pin: piece on {att} would pin {pinned_desc} against a more valuable piece behind it."
            )

        elif tag == "back_rank":
            ksq = ev.get("king_square", "?")
            threat_sq = ev.get("squares", [None])[0]
            parts.append(
                f"{mover_side}'s king on {ksq} is vulnerable to a back-rank mate"
                + (f" — {opp_side} can play to {threat_sq}." if threat_sq else ".")
            )

        elif tag == "discovered_attack":
            attacks = ev.get("discovered_attacks", [])
            frm = ev.get("moved_from", "?")
            to = ev.get("moved_to", "?")
            if attacks:
                a = attacks[0]
                tgt_ann = piece_on(a["target"])
                parts.append(
                    f"{mover_side}'s move from {frm} to {to} uncovered an attack on "
                    f"{a['target']}{tgt_ann} by the piece on {a['uncovered_attacker']}."
                )

        elif tag == "overloaded_piece":
            tgt = ev.get("target", "?")
            def_sq = ev.get("overloaded_defender", "?")
            also = ev.get("also_defends", "?")
            def_ann = piece_on(def_sq)
            tgt_ann = piece_on(tgt)
            also_ann = piece_on(also)
            parts.append(
                f"{opp_side}'s piece on {def_sq}{def_ann} is overloaded — it defends both "
                f"{tgt}{tgt_ann} and {also}{also_ann}. Capturing {tgt} forces it to abandon one."
            )

        elif tag == "intermezzo_missed":
            parts.append(
                f"{mover_side} missed an in-between move (intermezzo): instead of recapturing, "
                f"the best move first delivers check, forcing the opponent to respond before the recapture happens."
            )

        elif tag == "mating_net_missed":
            parts.append(f"{mover_side} missed a forced mating sequence that was available.")

        elif tag == "mating_net_allowed":
            parts.append(f"{mover_side}'s move allowed {opp_side} to set up a forced mating sequence.")

        elif tag == "king_safety":
            note = ev.get("note", "")
            parts.append(f"King safety concern for {mover_side}" + (f": {note}" if note else "."))

        elif tag == "pawn_structure":
            note = ev.get("note", "")
            parts.append(f"Pawn structure issue" + (f": {note}" if note else "."))

        else:
            if ev:
                parts.append(str(ev))

        lines.append(" ".join(parts))

    return "[TACTICAL MOTIFS DETECTED]\n" + "\n".join(f"- {l}" for l in lines) + "\n"


def _piece_list(fen: str) -> str:
    """Return a plain-text piece list grouped by side, e.g. 'White: King(e1), Queen(d1)...'"""
    _order = [chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]
    try:
        board = chess.Board(fen)
        result = []
        for color, label in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
            parts = []
            for pt in _order:
                squares = sorted(board.pieces(pt, color), key=lambda s: (chess.square_file(s), chess.square_rank(s)))
                name = _PIECE_NAMES[chess.piece_symbol(pt).lower()]
                for sq in squares:
                    parts.append(f"{name}({chess.square_name(sq)})")
            result.append(f"{label}: {', '.join(parts)}")
        return "\n".join(result)
    except Exception:
        return ""


def _annotate_move_squares(fen: str, move_san: str) -> str:
    """Return 'SAN (from→to)' by parsing the SAN against the position."""
    try:
        board = chess.Board(fen)
        move = board.parse_san(move_san)
        frm = chess.square_name(move.from_square)
        to = chess.square_name(move.to_square)
        return f"{move_san} ({frm}→{to})"
    except Exception:
        return move_san


def _annotate_captures(fen: str, pv_san: list[str]) -> list[str]:
    """Return pv_san with capture targets labelled, e.g. 'cxd3 (×Rook)'."""
    try:
        board = chess.Board(fen)
        result = []
        for san in pv_san:
            move = board.parse_san(san)
            captured = board.piece_at(move.to_square)
            if captured is None and board.is_en_passant(move):
                captured_sym = 'p'
            elif captured:
                captured_sym = captured.symbol().lower()
            else:
                captured_sym = None
            if captured_sym:
                result.append(f"{san} (×{_PIECE_NAMES[captured_sym]})")
            else:
                result.append(san)
            board.push(move)
        return result
    except Exception:
        return pv_san


def _material_inventory(fen: str) -> str:
    """Return a compact material inventory string for both sides."""
    try:
        board = chess.Board(fen)
        counts: dict[str, dict[str, int]] = {
            'White': {'Queen': 0, 'Rook': 0, 'Bishop': 0, 'Knight': 0, 'Pawn': 0},
            'Black': {'Queen': 0, 'Rook': 0, 'Bishop': 0, 'Knight': 0, 'Pawn': 0},
        }
        values = {'Queen': 9, 'Rook': 5, 'Bishop': 3, 'Knight': 3, 'Pawn': 1}
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece and piece.piece_type != chess.KING:
                side = 'White' if piece.color == chess.WHITE else 'Black'
                name = _PIECE_NAMES[piece.symbol().lower()]
                counts[side][name] += 1
        lines = []
        for side in ('White', 'Black'):
            parts = [f"{v}×{k}" for k, v in counts[side].items() if v > 0]
            total = sum(counts[side][k] * values[k] for k in counts[side])
            lines.append(f"{side}: {', '.join(parts)} = {total} pts")
        return "\n".join(lines)
    except Exception:
        return ""


async def chat(
    fen: str,
    candidates: list[dict],
    question: str,
    eval_cp: int | None = None,
    played_move: str | None = None,
    best_move: str | None = None,
    classification: str | None = None,
    eval_cp_before: int | None = None,
    eval_cp_after: int | None = None,
    played_move_line: dict | None = None,
    user_color: str | None = None,
    motif_details: dict | None = None,
) -> str:
    provider, api_key = _get_api_key()

    # Resolve current eval from candidates if not provided directly
    if eval_cp is None and candidates:
        eval_cp = candidates[0].get("eval_cp")

    def _eval_label(cp: int) -> str:
        if cp > 150:
            return f"+{cp / 100:.1f} (White winning)"
        elif cp < -150:
            return f"{cp / 100:.1f} (Black winning)"
        else:
            return f"{cp / 100:+.1f} (roughly equal)"

    move_context = ""
    if played_move:
        label = f" ({classification})" if classification else ""
        annotated_played = _annotate_move_squares(fen, played_move)
        move_context = f"User's move: **{annotated_played}**{label}\n"
        if best_move and best_move != played_move:
            annotated_best = _annotate_move_squares(fen, best_move)
            move_context += f"Engine's best move: **{annotated_best}**\n"
        if eval_cp_before is not None and eval_cp_after is not None:
            move_context += (
                f"Evaluation swing: {_eval_label(eval_cp_before)} → {_eval_label(eval_cp_after)} "
                f"(delta: {(eval_cp_after - eval_cp_before) / 100:+.1f} pawns)\n"
            )
        elif eval_cp is not None:
            move_context += f"Position evaluation after move: {_eval_label(eval_cp)}\n"
        move_context += "\n"
    elif eval_cp is not None:
        move_context = f"Position evaluation: {_eval_label(eval_cp)}\n\n"

    # Build lines section: played move's concrete line first (if we have it), then top engine lines
    played_line_text = ""
    if played_move_line:
        raw_pv = played_move_line.get("pv_san", [])[:10]
        annotated_pv = _annotate_captures(fen, raw_pv)
        pv = " ".join(annotated_pv)
        ev = played_move_line.get("eval_cp")
        ev_str = f" (eval: {ev / 100:+.1f})" if ev is not None else ""
        played_line_text = f"User's move line{ev_str}: {pv}\n\n"

    def _fmt_line(c: dict) -> str:
        raw_pv = c.get('pv_san', [])[:10]
        annotated_pv = _annotate_captures(fen, raw_pv)
        pv_str = " ".join(annotated_pv)
        if c.get('eval_cp') is not None:
            return f"{c['rank']}. {c['move_san']} (eval: {c['eval_cp'] / 100:+.1f}) — {pv_str}"
        return f"{c['rank']}. {c['move_san']} — {pv_str}"

    lines_text = "\n".join(_fmt_line(c) for c in candidates)

    pieces = _piece_list(fen)
    pieces_section = f"Piece locations:\n{pieces}\n" if pieces else ""

    inventory = _material_inventory(fen)
    inventory_section = f"Material count:\n{inventory}\n\n" if inventory else ""

    motif_section = _format_motif_context(motif_details or {}, user_color, fen)
    motif_section = motif_section + "\n" if motif_section else ""

    color_note = f"The user is playing as **{user_color}**. " if user_color else ""
    eval_note = (
        f"Note: all evaluations are from White's perspective "
        f"(positive = White is better, negative = Black is better).\n"
    )

    user_content = (
        f"[BOARD STATE]\n"
        f"FEN: {fen}\n"
        f"{pieces_section}"
        f"{color_note}{eval_note}\n"
        f"{inventory_section}"
        f"{motif_section}"
        f"[ENGINE DATA]\n"
        f"{move_context}"
        f"{played_line_text}"
        f"Stockfish top lines:\n{lines_text}\n\n"
        f"[QUESTION]\n"
        f"{question}"
    )

    if provider == "anthropic":
        return await _chat_anthropic(api_key, user_content)
    elif provider == "openai":
        return await _chat_openai(api_key, user_content)
    elif provider == "gemini":
        return await _chat_gemini(api_key, user_content)
    elif provider == "ollama":
        return await _chat_ollama(api_key, user_content)
    else:
        raise ValueError(f"Unknown provider: {provider!r}")


async def _chat_anthropic(api_key: str, user_content: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 800,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_content}],
            },
        )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


async def _chat_openai(api_key: str, user_content: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 800,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            },
        )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


async def _chat_gemini(api_key: str, user_content: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            headers={"content-type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": user_content}]}],
                "generationConfig": {"maxOutputTokens": 800},
            },
        )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _chat_ollama(api_key: str, user_content: str) -> str:
    # For Ollama, api_key holds the model name (e.g. "llama3.2") and it runs
    # locally — no auth required.
    model = api_key or "llama3.2"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            },
        )
    r.raise_for_status()
    return r.json()["message"]["content"]


# ---------------------------------------------------------------------------
# Game narrative
# ---------------------------------------------------------------------------

NARRATIVE_SYSTEM_PROMPT = """\
You are a chess writer. Given engine data about a game, write a short thematic narrative — not a move-by-move recap, but a story about *what kind of game it was* and *what decided it*.

""" + CHESS_PRINCIPLES + """

Use these principles to frame your narrative where they apply — ground your language in what actually happened structurally and tactically.

Output format — exactly 3 short sections in markdown:

### The Game
One paragraph capturing the character of the position — was it a closed fortress, an open tactical brawl, a slow positional squeeze? Use vivid but grounded descriptors (e.g. "a locked pawn structure that smoldered for twenty moves", "an open board where both kings felt the heat"). Ground this in the opening and the structural features of the position.

### The Decisive Idea
One paragraph on the key theme or moment that decided the game — a piece sacrifice that cracked a fortress, a passed pawn that became unstoppable, a king march that caught the opponent flat-footed. Lead with the *idea*, not the sequence of events.

### The Verdict
One or two sentences: what this game was ultimately about and how it ended.

Rules:
- Refer to players only as **White** and **Black** — never use their names
- You have accuracy stats (ACPL, blunders, mistakes) for context — use them to calibrate tone, but **never mention the numbers explicitly** in the narrative
- Never quote centipawn values or engine scores — express evaluation shifts as "White seized a decisive advantage", "the position tipped irreversibly", "Black's counterplay evaporated", etc.
- Never list individual moves
- Use expressive but precise chess language: fortress, outpost, passed pawn, breakthrough, overload, pin, zugzwang, etc. — when the position earns the word
- Keep each section to 2–4 sentences. Tight is better than thorough."""


def _eval_label_short(cp: int | None) -> str:
    if cp is None:
        return "unclear"
    if cp > 300:
        return "White is winning"
    if cp > 100:
        return "White is better"
    if cp < -300:
        return "Black is winning"
    if cp < -100:
        return "Black is better"
    return "roughly equal"


async def narrative(
    white: str,
    black: str,
    result: str,
    opening_name: str | None,
    player_username: str,
    acpl: int,
    blunders: int,
    mistakes: int,
    key_positions: list[dict],  # [{label, fen, eval_cp, move_num}]
    dominant_motifs: list[str],
) -> str:
    provider, api_key = _get_api_key()

    player_color = "White" if white.lower() == player_username.lower() else "Black"
    result_label = "White won" if result == "1-0" else "Black won" if result == "0-1" else "Draw"

    positions_text = "\n".join(
        f"  [{p['label']}] Move {p['move_num']}: {_eval_label_short(p['eval_cp'])}. FEN: {p['fen']}"
        for p in key_positions
    )

    motifs_text = ", ".join(dominant_motifs) if dominant_motifs else "none identified"

    content = (
        f"Opening: {opening_name or 'Unknown'}\n"
        f"Result: {result_label}\n"
        f"Dominant motifs: {motifs_text}\n\n"
        f"[Accuracy context — do not quote these numbers in the narrative]\n"
        f"White ACPL: {acpl}, blunders: {blunders}, mistakes: {mistakes}\n\n"
        f"Key positions:\n{positions_text}\n\n"
        f"Write the narrative now."
    )

    if provider == "anthropic":
        return await _narrative_anthropic(api_key, content)
    elif provider == "openai":
        return await _narrative_openai(api_key, content)
    elif provider == "gemini":
        return await _narrative_gemini(api_key, content)
    elif provider == "ollama":
        return await _narrative_ollama(api_key, content)
    else:
        raise ValueError(f"Unknown provider: {provider!r}")


async def _narrative_anthropic(api_key: str, content: str) -> str:
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 700,
                "system": NARRATIVE_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": content}],
            },
        )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


async def _narrative_openai(api_key: str, content: str) -> str:
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 700,
                "messages": [
                    {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
            },
        )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


async def _narrative_gemini(api_key: str, content: str) -> str:
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            headers={"content-type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": NARRATIVE_SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": content}]}],
                "generationConfig": {"maxOutputTokens": 700},
            },
        )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _narrative_ollama(api_key: str, content: str) -> str:
    model = api_key or "llama3.2"
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
            },
        )
    r.raise_for_status()
    return r.json()["message"]["content"]
