# chess-coach — Product Requirements

## One-liner
Free, self-hostable chess improvement platform. Pull your Chess.com games, analyze them with Stockfish, surface your recurring mistakes, drill them with targeted puzzles. Bring your own LLM agent via MCP.

## Goals
- **Zero paywall.** No tier, no upsell, no telemetry. Forever.
- **Bring your own agent.** All useful operations exposed as MCP tools so any LLM client (Claude Desktop, Cursor, etc.) can plug in.
- **Useful in week 1.** Even before puzzles/patterns, a user should be able to import their games and step through engine analysis.
- **Local-first.** Default deployment is `pnpm dev:web` + `pnpm dev:api` + local SQLite + local Stockfish. No cloud required.

## Non-goals
- Real-time play against other users (no matchmaking, no lobbies, no chat).
- Mobile apps. The web UI must work on mobile, but no native shells.
- Account systems with passwords. A user is identified by their Chess.com username; that's it.
- Hosted multi-tenant SaaS. If someone else wants to host, fine — but the project does not run a paid service.

## Users
- **Primary:** intermediate club player (800–1800) who plays online, has hundreds–thousands of games, and wants targeted improvement without a coach.
- **Secondary:** the same user's LLM agent, which queries the MCP server to give natural-language coaching ("show me my last 3 games where I hung a piece in the opening").

## Tech stack (decided)
- Monorepo, pnpm workspaces.
- `apps/web` — Next.js 14 App Router, TypeScript, Tailwind. Talks to API over HTTP.
- `apps/api` — FastAPI, python-chess, Stockfish (via `chess.engine`). SQLite for storage (single file, gitignored).
- MCP server lives inside `apps/api` (separate entrypoint, same code/data).

## Data model (sketch)
- `players(username PK, last_synced_at)`
- `games(id PK, player_username FK, chesscom_id, played_at, time_control, white, black, result, eco, pgn TEXT)`
- `analyses(game_id FK, ply INT, fen TEXT, best_move TEXT, played_move TEXT, eval_cp INT, classification TEXT, motif_tags TEXT[], phase TEXT, pv TEXT, motif_details TEXT)` — one row per ply. `pv` is a JSON UCI array: the engine's principal variation (refutation / best line) from `fen`, truncated to ~8 plies. `motif_details` is JSON: per-tag structured evidence (the squares/pieces involved and the concrete move(s) that exploit or refute), so each motif can be cited on the board and explained, not left as a bare label.
- `engine_lines(fen TEXT, multipv_rank INT, move_uci TEXT, eval_cp INT, mate INT, pv TEXT, depth INT, computed_at TEXT, PRIMARY KEY(fen, multipv_rank))` — the incremental engine-analysis cache, keyed by position. Holds the top-N candidate moves for a FEN, each with its eval and principal variation, at the deepest/broadest computed so far. **Every** evaluation path (game analysis, `/positions/evaluate`, on-demand deepening) upserts here; reads check it first and only compute the missing breadth (more `multipv_rank`s) or depth. We never recompute what is already cached at ≥ the requested depth — analysis only deepens and broadens over time.
- `mistakes(id PK, game_id FK, ply INT, classification, motif_tags, fen_before, played_move, best_move, eval_swing_cp)` — denormalized view of blunders/mistakes/inaccuracies for fast querying
- `puzzles(id PK, source TEXT, fen TEXT, solution_moves TEXT, themes TEXT[])` — seeded from Lichess open puzzle DB
- `puzzle_attempts(id PK, puzzle_id FK, username FK, solved BOOL, attempted_at)`

## Background — already built (v1 phases 1–3, most of 4)

These are **done and working** — do not rebuild or refactor them; they are described here only so the loop understands the existing surface area. The authoritative per-item record (with commit shas) is in `spec/PROGRESS.md`.

- **Ingest.** `POST /players/{username}/sync` (Chess.com archives → `games`, idempotent), `GET /players/{username}/games` (paginated, filterable), `GET /games/{id}`. Web: `/` username input → sync → redirect; `/players/[username]` game list; `/players/[username]/games/[id]` game detail.
- **Engine analysis.** `POST /games/{id}/analyze` (Stockfish per ply, default depth 18, idempotent), `GET /games/{id}/analysis`. Classification thresholds: `blunder` ≥200, `mistake` 100–199, `inaccuracy` 50–99, else `good`; mate-score swings always blunder. Web game detail renders board + move list + eval bar (eval score shown inside the bar) + per-move classification badges + a Move Detail panel (played move, classification, best move, phase, motif tags).
- **Mistake patterns.** Motif tagger (tags: `hanging_piece`, `fork_missed`, `back_rank`, `pin_missed`, `discovered_attack`, `overloaded_piece`, `king_safety`, `endgame_technique`, `opening_principle`), `GET /players/{username}/patterns` (aggregated counts + examples), Web `/players/[username]/patterns` motif cards.
- **Puzzles (backend).** Lichess puzzle DB importer (`puzzles` table, theme-tagged), `GET /players/{username}/drill` (queue mixing theme-matched puzzles + the user's own pre-blunder FENs), `POST /puzzle_attempts`.

## Phases & acceptance criteria (remaining work)

The ralph loop takes the FIRST unchecked item in `spec/PROGRESS.md`, in order. Acceptance criteria for each come from the matching section below.

### Phase 4 — Puzzles (remaining)
- [ ] Web: `/players/[username]/drill` — board + solve interaction + streak counter, driven by `GET /players/{username}/drill` and recording results via `POST /puzzle_attempts`.

### Phase 5 — MCP server
- [ ] Separate entrypoint `apps/api/app/mcp_server.py` exposing tools: `list_games`, `get_game_pgn`, `get_game_analysis`, `get_mistake_history`, `get_top_patterns`, `next_puzzle`, `submit_puzzle_attempt`.
- [ ] Docs in README: how to add this MCP server to Claude Desktop / Cursor.
- [ ] Smoke test: an MCP client can list games and fetch one analysis end-to-end.

### Phase 6 — Move explanations & interactive exploration

**Concept.** LLMs reason poorly about raw board positions but explain *well* when handed verified facts. So Stockfish + the motif tagger produce the ground-truth facts about a move (eval, best line, what was missed); the user's own LLM — connected over MCP — turns those facts into coaching prose. The web UI adds a sandbox where the user can play out alternative lines and watch the eval move, then ask their LLM (through MCP) why a line works or fails. **The LLM never decides what is good or bad — it only explains facts the engine already verified.**

This phase has three layers, built in this order (each layer's items are independent ralph iterations): backend foundation → MCP tools → web UI.

Already present in the web UI (hand-built, do not rebuild): the eval score is rendered inside the eval bar, and a "Move Detail" panel on the game detail page shows the played move, classification, engine best move, phase, and motif tags for the current position. Phase 6 web work *extends* these, it does not replace them.

**Principle: analysis only deepens and broadens — never recompute.** The original per-game analysis (`analyze.py`, `multipv=2`, single truncated PV) is deliberately cheap and is NOT comprehensive enough for the candidate-move/deep-line views below. Rather than re-running it, all richer analysis is written through the position-keyed `engine_lines` cache: any path that evaluates a FEN first reads the cache, computes only the missing breadth/depth, and upserts the result. A position analyzed at depth 18 with 3 lines, then later requested at depth 22 with 5 lines, extends the same rows — earlier work is reused.

**Two motivating gaps this phase closes** (from real UI review):
1. A motif badge like "Skewer Missed" is currently a bare label with no tie to the board — the user cannot tell what it refers to. Motifs must cite their concrete evidence (squares, pieces, the exploiting move) and be visualizable + explainable.
2. The best move is shown only as text. It (and candidate alternatives) should be drawable on the board (arrow + highlighted squares), and the user should see the *top few* candidate moves with their lines, not just the single best.

**Backend foundation**
- Persist the engine PV. In `analyze.py` the principal variation (`best_info["pv"]`) is already computed per ply — store its first 8 plies as a JSON UCI array in a new `analyses.pv` column. Migrate by drop+rebuild of `analyses` on missing column (same one-shot pattern already used for `phase`). Surface `pv` in `GET /games/{id}/analysis` and in the web `PlyAnalysis` type.
- Position-keyed analysis cache. Add the `engine_lines` table and a single `evaluate_position(fen, depth, multipv)` service function that: reads `engine_lines` for the FEN; if it already holds ≥ `multipv` ranks at ≥ `depth`, returns them as-is; otherwise runs Stockfish for the missing breadth/depth and upserts. This function is the one place engine analysis is requested from; everything else calls it. Use a persistent Stockfish singleton (one long-lived engine guarded by a lock — do NOT `popen` per request).
- On-demand evaluation endpoint. `POST /positions/evaluate` — request `{fen, depth?=18, multipv?=1}`, response `{lines: [{rank, move_uci, move_san, eval_cp, mate, pv_uci, pv_san}], depth}` where `eval_cp` is white-POV (null on mate), `mate` is signed mate-in-N (null otherwise), and each `pv` is ≥5 plies when available. Invalid FEN → 400. Backed by the cache function above.
- Motif evidence. Enhance the motif tagger (or add a post-pass over the engine PV + board) so each emitted tag carries structured evidence: the involved squares/pieces and the concrete UCI move(s) that exploit or refute. Persist as `analyses.motif_details` (JSON, parallel to `motif_tags`) and surface it in `GET /games/{id}/analysis`. Example: `skewer_missed → {squares:["e8","e1"], by_move:"e2e8", line:["e2e8", ...]}`.

**MCP tools** (extend the Phase 5 server — same file, same code/data)
- `evaluate_position(fen, depth?, multipv?)` and `explore_line(fen, moves[])`. Both route through the `engine_lines` cache. `evaluate_position` returns the top-N candidate moves with eval + line. `explore_line` applies the SAN/UCI moves to the FEN (illegal move → tool error), then returns the resulting FEN plus its eval and best continuation. Together these let the user's LLM reason about alternative lines without guessing evals.
- `explain_move(game_id, ply)`. Returns a **structured fact bundle, not prose**: played move (SAN+UCI), eval before/after (white-POV and mover-POV), centipawn swing, classification, phase, the **top-N candidate moves** (each with eval + PV in SAN, drawn from the cache), and the **motif evidence** (each tag with its cited squares + exploiting line in SAN). The tool's description instructs the calling LLM to explain — conceptually (the idea missed) and concretely (the line that punishes it, citing the squares/moves provided) — strictly from these facts, and to never substitute its own evaluation.

**Web UI**
- Board overlays for the current move. Draw the engine's best move as an arrow (from→to) with its destination square highlighted; when a motif is selected, highlight its cited squares and draw its exploiting line. Use `react-chessboard`'s `customArrows` / `customSquareStyles` (a translucent "ghost" piece on the best-move target is a nice-to-have on top of the arrow). Overlays update as the user steps through moves.
- Candidate moves in the Move Detail panel. Show the top 3 candidate moves (best included), each with its eval and a clickable line ≥5 plies deep. Hovering/selecting a candidate previews its arrow on the board; clicking lets the user step through that line. Data comes from `POST /positions/evaluate` (cache-backed) for the current FEN, requested at multipv≥3.
- Interactive motifs. The motif chips become clickable: selecting one highlights its cited squares/line on the board and shows its evidence (and, when an LLM is connected via MCP, is the natural anchor for an explanation). A motif must never be a label with no on-board referent.
- "Explore from here" mode. A toggle makes pieces draggable from the currently-viewed position. A legal user move branches a side-line — the actual game mainline is never mutated — and each resulting position is evaluated via `POST /positions/evaluate` so the eval bar, candidate list, and a small "exploring" indicator update live, debounced. The explored side-line shows as a breadcrumb with a "Return to game" reset that restores the mainline cursor. Illegal moves snap back.

**Acceptance for Phase 6.** A user can step to any analyzed move and see, on the board, the best move as an arrow and the top-3 candidate lines (≥5 plies) they can click through; clicking a motif highlights exactly the squares/pieces it refers to; can toggle explore mode, drag pieces to try alternatives, and watch the eval + candidates update live; deeper/broader analysis is persisted to `engine_lines` and reused rather than recomputed; and an MCP client can call `explain_move`, `evaluate_position`, and `explore_line` end-to-end against real data, receiving motif evidence and candidate lines as structured facts.

## Out of scope for v1 (revisit later)
- Multi-user auth / sharing.
- Lichess imports.
- Opening repertoire builder.
- Spaced-repetition scheduling for puzzles.
- Cloud deployment guides.

## Definition of done (v1)
All phase 1–6 checklists complete; `pnpm dev:web` + `pnpm dev:api` running locally lets a user enter their Chess.com username, see their games, see analysis, see patterns, drill puzzles, explore alternative lines with live engine eval, and any MCP client can hit the same data — including fetching the grounded move-explanation facts that let the user's own LLM coach them.
