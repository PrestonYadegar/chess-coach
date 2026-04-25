# chess-coach

A free, self-hostable chess learning platform for Chess.com players rated ~1800 and below. Sync your games, analyze with Stockfish, discover your recurring mistake patterns, and drill them with targeted puzzles — no subscription, no paywall, no telemetry.

## What it does

- **Sync your games** from Chess.com — all archives, incrementally, idempotent
- **Engine analysis** with Stockfish at depth 14 by default, classifying every move as blunder, mistake, inaccuracy, etc. with eval swings and best-move suggestions. Re-analyze any game at deeper depth from the game view.
- **Mistake patterns** — 9 heuristic motif detectors (hanging pieces, forks, back rank, pins, discovered attacks, overloaded pieces, king safety, endgame technique, opening principles) aggregated across all your games so you see what you actually blunder, not just what looks bad in hindsight
- **Drill queue** — personalized puzzles mixing Lichess's open puzzle database (filtered to your weak motifs) with positions from your own games
- **Interactive board** — step through games, explore alternate lines with draggable pieces, see engine candidates with eval, hover motif evidence overlaid on the board
- **AI coaching** — add your own LLM API key (OpenAI, Anthropic, etc.) in Settings to unlock drill chat explanations and game narratives. The LLM explains facts the engine already verified; it never decides what is good or bad.
- **Background analysis** — analysis runs server-side so it's safe to close the tab or refresh. A floating widget is available to manage workers and track progress.

## Who it's for

Intermediate Chess.com players (sub-1800) who want structured improvement without a human coach or having to pay for a product. The analysis depth and motif detection are tuned for the kinds of mistakes that show up at this rating range.

## Quickstart

**Prerequisites:** Node 18+, Python 3.11+, pnpm, Stockfish on PATH

```bash
brew install stockfish   # macOS; or install from stockfishchess.org
pnpm install
pnpm dev:api             # http://localhost:8000
pnpm dev:web             # http://localhost:3000
```

Enter your Chess.com username on the homepage to sync your games and start analyzing.

**Optional — AI coaching features:**  
Go to **Settings → AI Coach**, choose a provider (OpenAI, Anthropic, etc.), and paste your API key. This enables explanation chat on the drill page and narratives on the game view.

## Key considerations

- **Single-user, local-first** — query for any profile on Chess.com by username. Data stored locally in a small SQLite db (10-100MB)
- **No opening prep** — the platform focuses on middlegame and endgame mistakes; it does not build opening repertoires
- **Stockfish required** — analysis features don't work without it on PATH
- **Chess.com only** — Lichess game import is not implemented
- **LLM integration** — AI coaching features require your own API key; there is no hosted model. Ollama is supported out of the box if you'd prefer to run a local model
- **Engine analysis** — Stockfish needs a brief warmup on first use; games are auto-enqueued after sync and evals are cached. Depth 14 and 4 workers by default, both configurable in Settings

## Repo layout

```
apps/
  web/        Next.js 14 (App Router, TypeScript, Tailwind)
  api/        FastAPI + python-chess + Stockfish — ingest, analysis, LLM, drill
scripts/
  run-api.sh  Starts the API, creates the Python venv on first run
```

## Possible future directions

**General improvements**
- Lichess game import
- Support for alternative engines (e.g. Leela Chess Zero) for multiple perspectives
- Better LLM grounding for chess

**Deeper analysis for stronger players (2000+)**
- **Opening repertoire tree** — trace where you leave the opening book, common divergence points, and win rate at each branch.
- **Time correlation** — correlate eval progression with time remaining
- **Positioning analysis** — evaluate whether middlegame moves adhered to key chess principles or followed a coherent and correct plan
- **Endgame classification & conversion tracking** — categorize endgames by type and track conversion rate

## Contributing

Issues, pull requests, and forks are very welcome. If you have ideas, find bugs, or want to adapt this for your own use — go for it.

## License

MIT
