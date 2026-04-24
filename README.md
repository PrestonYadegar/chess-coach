# chess-coach

Free, self-hostable chess improvement platform. Pull your Chess.com games, analyze them with Stockfish, find your recurring mistakes, and drill them with targeted puzzles. Bring your own LLM agent via MCP — no paid tier, ever.

## Layout

```
apps/
  web/        Next.js 14 (App Router, TS, Tailwind) — UI
  api/        FastAPI + python-chess + Stockfish — ingest, analysis, MCP
spec/
  PRD.md      Product spec, source of truth for the build loop
  PROGRESS.md Phase checklist the build loop updates each iteration
scripts/
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

## MCP server — connect your LLM

Chess Coach exposes all its data as MCP tools so any client (Claude Desktop, Cursor, etc.) can query your games, analysis, patterns, and puzzles.

**Prerequisites:** the API venv must exist (`scripts/run-api.sh` creates it on first run).

### Claude Desktop

Add a server entry to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "chess-coach": {
      "command": "/absolute/path/to/chess-coach/scripts/run-mcp.sh"
    }
  }
}
```

Replace `/absolute/path/to/chess-coach` with the real path (e.g. `$HOME/CodingProjects/chess_coach`). Restart Claude Desktop — the 7 chess-coach tools appear automatically.

### Cursor

Open **Settings → Features → MCP Servers → Add new MCP server** and fill in:

| Field | Value |
|-------|-------|
| Name | `chess-coach` |
| Type | `command` |
| Command | `/absolute/path/to/chess-coach/scripts/run-mcp.sh` |

Save and restart Cursor.

### Available MCP tools

| Tool | Description |
|------|-------------|
| `list_games` | List your games (filterable by result, time control, opening) |
| `get_game_pgn` | Fetch the raw PGN for a game |
| `get_game_analysis` | Per-ply Stockfish analysis + motif tags for a game |
| `get_mistake_history` | Your blunders/mistakes sorted by eval swing |
| `get_top_patterns` | Aggregated motif counts — what you blunder most |
| `next_puzzle` | Get the next drill puzzle from your personalised queue |
| `submit_puzzle_attempt` | Record a solve or fail for a puzzle |

The MCP server reads the same SQLite file as the API. Games must be synced (`POST /players/{username}/sync`) and analyzed (`POST /games/{id}/analyze`) before the tools return useful data.

## The build loop (local-only)

This repo was built with a small Claude Code driver loop. The scripts live under
`scripts/claude_loop*` but are **gitignored** (local-only, not tracked): each run
re-invokes Claude Code with a prompt that says read `spec/PRD.md` and
`spec/PROGRESS.md`, pick the next unchecked acceptance criterion, implement it,
update PROGRESS, commit. See the script for safety rails.
