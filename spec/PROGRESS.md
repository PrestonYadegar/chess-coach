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
- [x] API: motif tagger heuristics for the 9 tags listed in PRD.
- [x] API: `GET /players/{username}/patterns`.
- [x] Web: `/players/[username]/patterns` page.

## Phase 4 — Puzzles
- [x] Importer for Lichess open puzzle DB.
- [x] API: `GET /players/{username}/drill`.
- [x] API: `POST /puzzle_attempts`.
- [x] Web: `/players/[username]/drill` page.

## Phase 5 — MCP
- [x] `apps/api/app/mcp_server.py` with the 7 tools listed in PRD.
- [x] README section: how to wire into Claude Desktop / Cursor.
- [x] End-to-end smoke test.

## Phase 6 — Move explanations & interactive exploration
Build order: backend foundation → MCP tools → web. See PRD "Phase 6" for full acceptance criteria. Guiding principle: analysis only deepens/broadens — every engine evaluation routes through the position-keyed `engine_lines` cache and never recomputes what is already cached at ≥ the requested depth/breadth.
- [x] API: persist the engine PV — add `analyses.pv` (JSON UCI array, first 8 plies of `best_info["pv"]`), drop+rebuild migration on missing column, surface `pv` in `GET /games/{id}/analysis` and the web `PlyAnalysis` type.
- [x] API: `engine_lines` cache + persistent Stockfish singleton + cache-backed `evaluate_position(fen, depth, multipv)` service. Reads cache, computes only missing breadth/depth, upserts. One lock-guarded long-lived engine, no per-request popen.
- [x] API: `POST /positions/evaluate` — `{fen, depth?=18, multipv?=1}` → `{lines:[{rank, move_uci, move_san, eval_cp, mate, pv_uci, pv_san}], depth}` (white-POV, pv ≥5 plies when available), 400 on invalid FEN. Backed by the cache service.
- [x] API: motif evidence — enhance the motif tagger (or post-pass over PV+board) so each tag carries structured evidence (cited squares/pieces + exploiting UCI move/line). Persist as `analyses.motif_details` JSON, surface in `GET /games/{id}/analysis`.
- [x] MCP: `evaluate_position(fen)` + `explore_line(fen, moves[])` tools — route through the cache; return top-N candidates + lines; `explore_line` applies moves (illegal → error) and returns resulting FEN + eval + best continuation.
- [x] MCP: `explain_move(game_id, ply)` tool — structured fact bundle (played move SAN+UCI, eval before/after, swing, classification, phase, top-N candidate moves w/ SAN PVs from cache, motif evidence w/ cited squares + lines in SAN); tool description tells the LLM to explain from facts only.
- [x] Web: board overlays — draw best move as an arrow + highlight target square; selecting a motif highlights its cited squares/line. Overlays update while stepping through moves (`react-chessboard` customArrows/customSquareStyles).
- [x] Web: candidate moves in Move Detail — show top 3 candidates (best included) each with eval + clickable line ≥5 plies, previewed on the board; data from `POST /positions/evaluate` at multipv≥3.
- [x] Web: interactive motif chips — clicking a chip highlights exactly its cited squares/pieces on the board and shows its evidence; no motif may be a label with no on-board referent.
- [x] Web: "Explore from here" mode — toggle draggable pieces, branch a side-line off the current position (mainline untouched), live debounced eval + candidate update via `POST /positions/evaluate`, breadcrumb + "Return to game" reset, illegal moves snap back.

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
2026-06-13 11:00  API: motif tagger heuristics (9 tags) integrated into analyze pipeline  8ed817ecabe58d139d1f07b4e179443cd2898643
2026-06-13 11:15  API: GET /players/{username}/patterns — motif aggregation endpoint  2933c6af9b20c538d2e71f308caa0f306cfec52d
2026-06-13 11:30  Web: /players/[username]/patterns — motif cards page with frequency bar and drill CTA  ebfeddbabbce19050e121b6fd4120e9b8a3001ec
2026-06-13 12:00  Lichess puzzle DB importer — puzzles/puzzle_attempts tables + streaming CSV import + smoke test  cd8160a770a5e4940af1752be9388b942e86dbd5
2026-06-13 12:30  GET /players/{username}/drill — mixed puzzle queue from Lichess themes + own pre-blunder FENs  09db9578eb38551b90aadaed6b12aba4e9b24fb2
2026-06-13 18:30  POST /puzzle_attempts — record solve/fail with player + puzzle validation  da0f7186f8a8656cf609e24571edead8de3182c3
2026-06-14 00:00  Web: /players/[username]/drill — board + solve interaction + streak counter  47d0276cf841b131023e90617110781154831a6f
2026-06-14 06:00  MCP server: apps/api/app/mcp_server.py with 7 tools (list_games, get_game_pgn, get_game_analysis, get_mistake_history, get_top_patterns, next_puzzle, submit_puzzle_attempt)  3acb07718a40c216500852789d93a291c4d5a4b4
2026-06-14 07:00  README section: MCP server setup for Claude Desktop and Cursor with tool table  2fcce0a3e57f009c8efd655919cce25319e700c5
2026-06-14 08:00  MCP end-to-end smoke test: initialize + tools/list + list_games + get_game_analysis  ddfe4e16238bfebb90b9b2a262ea51f65fbef3ec
2026-06-14 09:00  API: analyses.pv column (JSON UCI array ≤8 plies), drop+rebuild migration, surface in GET /games/{id}/analysis and web PlyAnalysis type  79de0c6b1bf6dd869d3366c736e39307dd07084c
2026-06-14 10:00  API: engine_lines cache table + persistent Stockfish singleton + cache-backed evaluate_position service  ec2442447980c701158b1e845f75c861bf43cc22
2026-06-14 11:00  API: POST /positions/evaluate — FEN evaluation endpoint with UCI+SAN lines, white-POV evals, cache-backed  94a71daf45ebe6de6c186174b9273b4ba37937e4
2026-06-14 12:00  API: motif evidence — structured evidence per tag (squares, pieces, exploiting move), analyses.motif_details JSON column, surfaced in GET /games/{id}/analysis  0b7b6fe5b21fb0dd690e87d48d79934b106b1c35
2026-06-14 13:00  MCP: evaluate_position + explore_line tools — cache-backed, top-N candidates + SAN/UCI lines, illegal move detection  edaa3977a497fbe808b938d201c820758968b213
2026-06-14 14:00  MCP: explain_move tool — structured fact bundle with played/best move SAN, eval swing, candidates, motif evidence  d8f116886b094b82af74122fba4995630ab4172c
2026-06-14 15:00  Web: board overlays — best move arrow + target highlight; clickable motif chips highlight cited squares/line  57cc1f96b94d72e1de0cce6e0f5606af92f71443
2026-06-14 16:00  Web: candidate moves in Move Detail — top 3 candidates with eval + clickable PV line, board preview on hover/select  b370d65656190c9eec86c090baddc71c536418b5
2026-06-14 17:00  Web: interactive motif chips — filter to evidence-only chips, evidence panel on select, board overlays  7c9f009ef94576d739d1688350d9c37cb491fd3d
2026-06-14 18:00  Web: "Explore from here" mode — draggable pieces, side-line branch, debounced eval+candidates, breadcrumb, Return to game  8184957c5e8577fb3e3701c654165eeb657f6fd5
