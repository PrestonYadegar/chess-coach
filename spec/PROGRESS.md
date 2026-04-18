# Progress

The ralph loop reads this file plus `PRD.md`, picks the FIRST unchecked item below, implements it, ticks the box, commits, and exits. Order matters — do not skip.

## Phase 1 — Ingest
- [ ] API: `POST /players/{username}/sync` — fetch Chess.com monthly archives, parse PGN, upsert into `games`. Port logic from `tools/download_games.sh`. Idempotent.
- [ ] API: `GET /players/{username}/games?limit&offset&result&time_control` — paginated list.
- [ ] API: `GET /games/{id}` — single game with PGN.
- [ ] Web: `/` — username input, triggers sync, redirects to `/players/[username]`.
- [ ] Web: `/players/[username]` — game list table.
- [ ] Web: `/players/[username]/games/[id]` — game detail (board + moves, no analysis yet).

## Phase 2 — Engine analysis
- [ ] API: `POST /games/{id}/analyze` — Stockfish per-ply, classify, persist. Idempotent.
- [ ] API: `GET /games/{id}/analysis`.
- [ ] Web: render eval bar + per-move classification badges on game detail page.

## Phase 3 — Mistake patterns
- [ ] API: motif tagger heuristics for the 9 tags listed in PRD.
- [ ] API: `GET /players/{username}/patterns`.
- [ ] Web: `/players/[username]/patterns` page.

## Phase 4 — Puzzles
- [ ] Importer for Lichess open puzzle DB.
- [ ] API: `GET /players/{username}/drill`.
- [ ] API: `POST /puzzle_attempts`.
- [ ] Web: `/players/[username]/drill` page.

## Phase 5 — MCP
- [ ] `apps/api/app/mcp_server.py` with the 7 tools listed in PRD.
- [ ] README section: how to wire into Claude Desktop / Cursor.
- [ ] End-to-end smoke test.

---

## Iteration log
(The ralph loop appends one line per iteration: `YYYY-MM-DD HH:MM  <task>  <commit-sha>`)
