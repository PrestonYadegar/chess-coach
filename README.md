# chess-coach

Free, self-hostable chess improvement platform. Pull your Chess.com games, analyze them with Stockfish, find your recurring mistakes, and drill them with targeted puzzles. Bring your own LLM agent via MCP — no paid tier, ever.

## Layout

```
apps/
  web/        Next.js 14 (App Router, TS, Tailwind) — UI
  api/        FastAPI + python-chess + Stockfish — ingest, analysis, MCP
spec/
  PRD.md      Product spec, source of truth for the ralph loop
  PROGRESS.md Phase checklist the ralph loop updates each iteration
scripts/
  ralph.sh    The ralph loop driver
  run-api.sh  Local API runner (creates venv if missing)
tools/
  download_games.sh   Standalone Chess.com PGN downloader (already used to seed data)
  games/              Local PGN archive (gitignored)
```

## Quickstart

```
pnpm install                # installs web deps
pnpm dev:web                # http://localhost:3000
pnpm dev:api                # http://localhost:8000
```

`stockfish` must be on PATH for analysis features (`brew install stockfish`).

## The ralph loop

`scripts/ralph.sh` re-invokes Claude Code with a prompt that says: read `spec/PRD.md` and `spec/PROGRESS.md`, pick the next unchecked acceptance criterion, implement it, update PROGRESS, commit. See the script for safety rails.
