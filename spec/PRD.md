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
- `analyses(game_id FK, ply INT, fen TEXT, best_move TEXT, played_move TEXT, eval_cp INT, classification TEXT, motif_tags TEXT[])` — one row per ply
- `mistakes(id PK, game_id FK, ply INT, classification, motif_tags, fen_before, played_move, best_move, eval_swing_cp)` — denormalized view of blunders/mistakes/inaccuracies for fast querying
- `puzzles(id PK, source TEXT, fen TEXT, solution_moves TEXT, themes TEXT[])` — seeded from Lichess open puzzle DB
- `puzzle_attempts(id PK, puzzle_id FK, username FK, solved BOOL, attempted_at)`

## Phases & acceptance criteria

The ralph loop works through these in order. Each phase has a checklist in `spec/PROGRESS.md`; the loop marks items done as it builds them.

### Phase 1 — Ingest
- [ ] API: `POST /players/{username}/sync` fetches all Chess.com monthly archives, parses PGN, upserts into `games`. Idempotent. (Port logic from `tools/download_games.sh`.)
- [ ] API: `GET /players/{username}/games?limit&offset&result&time_control` returns paginated list.
- [ ] API: `GET /games/{id}` returns full game + PGN.
- [ ] Web: `/` shows a username input → triggers sync → redirects to game list.
- [ ] Web: `/players/[username]` lists games with date, opponent, result, time control. Click → game detail page.

### Phase 2 — Engine analysis
- [ ] API: `POST /games/{id}/analyze` runs Stockfish over each ply (configurable depth, default 18), writes per-ply rows. Idempotent.
- [ ] API: `GET /games/{id}/analysis` returns the per-ply data.
- [ ] Classification rule: centipawn loss thresholds → `blunder` (>=200), `mistake` (100–199), `inaccuracy` (50–99), `good` (else). Mate-score swings always blunder.
- [ ] Web: game detail page renders a board (use `chessground` or `react-chessboard`) with move list, eval bar, and per-move classification badges.

### Phase 3 — Mistake patterns
- [ ] API: motif tagger — for each mistake, derive heuristic tags from the engine PV and board state: `hanging_piece`, `fork_missed`, `back_rank`, `pin_missed`, `discovered_attack`, `overloaded_piece`, `king_safety`, `endgame_technique`, `opening_principle`.
- [ ] API: `GET /players/{username}/patterns` returns aggregated counts: motif → count, last_seen_game_id, example FENs.
- [ ] Web: `/players/[username]/patterns` shows top motifs as cards with frequency and "drill this" CTA.

### Phase 4 — Puzzles
- [ ] Importer: load Lichess open puzzle DB into `puzzles` table, tagged by theme.
- [ ] API: `GET /players/{username}/drill?motif=hanging_piece` returns a puzzle queue mixing (a) puzzles whose themes match the user's top mistakes and (b) replayed positions from the user's own pre-blunder FENs.
- [ ] API: `POST /puzzle_attempts` records solve/fail.
- [ ] Web: `/players/[username]/drill` board + solve interaction + streak counter.

### Phase 5 — MCP server
- [ ] Separate entrypoint `apps/api/app/mcp_server.py` exposing tools: `list_games`, `get_game_pgn`, `get_game_analysis`, `get_mistake_history`, `get_top_patterns`, `next_puzzle`, `submit_puzzle_attempt`.
- [ ] Docs in README: how to add this MCP server to Claude Desktop / Cursor.
- [ ] Smoke test: an MCP client can list games and fetch one analysis end-to-end.

## Out of scope for v1 (revisit later)
- Multi-user auth / sharing.
- Lichess imports.
- Opening repertoire builder.
- Spaced-repetition scheduling for puzzles.
- Cloud deployment guides.

## Definition of done (v1)
All phase 1–5 checklists complete; `pnpm dev:web` + `pnpm dev:api` running locally lets a user enter their Chess.com username, see their games, see analysis, see patterns, drill puzzles, and any MCP client can hit the same data.
