# Progress

The ralph loop reads this file plus `PRD.md`, picks the FIRST unchecked item below, implements it, ticks the box, commits, and exits. Order matters — do not skip.

## Phase 1 — Ingest
- [x] API: `POST /players/{username}/sync` — fetch Chess.com monthly archives, parse PGN, upsert into `games`. Port logic from `tools/download_games.sh`. Idempotent.
- [x] API: `GET /players/{username}/games?limit&offset&result&time_control` — paginated list.
- [x] API: `GET /games/{id}` — single game with PGN.
- [x] Web: `/` — username input, triggers sync, redirects to `/players/[username]`.
- [x] Web: `/players/[username]` — game list table.
- [x] Web: `/players/[username]/games/[id]` — game detail (board + moves, no analysis yet).

## Phase 2 — Engine analysis
- [x] API: `POST /games/{id}/analyze` — Stockfish per-ply, classify, persist. Idempotent.
- [x] API: `GET /games/{id}/analysis`.
- [x] Web: render eval bar + per-move classification badges on game detail page.

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
2026-06-13 06:58  POST /players/{username}/sync endpoint with sqlite schema + chess.com PGN ingest  2d934b5467f029f4d16d948e2bf36ef678b0857a
2026-06-13 07:15  GET /players/{username}/games paginated list with result and time_control filters  c5b943846188715faa3522392e5152a4562648c9
2026-06-13 07:25  GET /games/{id} single game with PGN  a4721fd76953a3460fd90f828ef094f4a66b3059
2026-06-13 07:35  Web: / homepage with username input, sync trigger, redirect to /players/[username]  54ee32e354d6072f09642de8e87ec556bd19afae
2026-06-13 08:15  Web: /players/[username] game list table with pagination and result display  f67e8acd92b01b2de8b4d2828231b8e2fba1096b
2026-06-13 09:05  Web: /players/[username]/games/[id] game detail page with board and move list  f868314a3bcfdf6e574264174879194bc4922d4d
2026-06-13 10:00  POST /games/{id}/analyze — Stockfish per-ply analysis, classification, idempotent persist  21d19f731272110cbed8943f03b770808ebc0b68
2026-06-13 10:15  GET /games/{id}/analysis — return per-ply analysis rows  ef6a2bd312a7366d3ab73d7c73fa3c303b649744
2026-06-13 10:30  Web: eval bar + per-move classification badges on game detail page  4777b401bb60bbf3388af5f7c7729b76a1feb2b8
