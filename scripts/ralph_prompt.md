You are working inside the chess-coach monorepo as part of an automated "ralph loop". Each invocation, you do exactly one thing.

PROCEDURE — follow in order, no skipping:

1. Read spec/PRD.md in full. This is the product spec; treat it as authoritative.
2. Read spec/PROGRESS.md. Find the FIRST line matching `- [ ] ` (unchecked). This is your task for this iteration. If there are no unchecked items, print "ALL DONE" and exit without making changes.
3. Implement that single task and ONLY that task. Do not work ahead. Do not refactor unrelated code. Acceptance criteria for the task come from the matching section in PRD.md.
4. Smoke-test what you built before declaring done:
   - API changes: hit the new endpoint with curl against a freshly-started uvicorn.
   - Web changes: confirm `pnpm --filter @chess-coach/web build` succeeds; if it is a page, also confirm `pnpm --filter @chess-coach/web dev` serves it (HTTP 200) on the relevant route.
   - Make tests reproducible by adding scripts in scripts/smoke/ when sensible.
5. In spec/PROGRESS.md, change the leading `- [ ] ` of the task you completed to `- [x] `. Do not edit any other checkbox. Append one line to the "Iteration log" section of PROGRESS.md, in this exact form:
       YYYY-MM-DD HH:MM  <task summary>  <will-fill-sha>
   The wrapper rewrites `<will-fill-sha>` to the commit hash after you exit.
6. Stage and commit ALL your changes (including PROGRESS.md) with message:
       ralph: <one-line task summary>
   Do NOT use --no-verify. Do NOT push.
7. Stop. Do not start the next task. The wrapper loop will re-invoke you.

CONSTRAINTS:
- The Python backend lives in apps/api (FastAPI + python-chess + Stockfish + SQLite). Use a venv at apps/api/.venv (scripts/run-api.sh creates it). Add new deps to apps/api/requirements.txt.
- The web app lives in apps/web (Next.js 14 App Router, TS, Tailwind). Use pnpm.
- Database: SQLite file at apps/api/data.sqlite (gitignored). SQLAlchemy or raw sqlite3 both fine. A simple init_db() called at API startup is acceptable for v1; no Alembic.
- Be polite to chess.com: send a User-Agent header and sleep ~300ms between archive fetches.
- Stockfish must be invoked via python-chess `chess.engine.SimpleEngine`. If `stockfish` is not on PATH, fail loudly with instructions ("brew install stockfish").
- Never delete games/, the existing tools/games/ archive, or rewrite git history.

EFFICIENCY RULES — these cost real money/time, follow them:
- **Always use absolute paths.** Your cwd is not stable across Bash calls; `cd apps/api && ...` has bitten us. Use `/Users/prestonyadegar/CodingProjects/personal_repos/chess_coach/...` or `$ROOT/...` where you set ROOT once.
- **To start the API, run `scripts/run-api.sh` in the background.** Do not hand-roll `uvicorn` invocations from arbitrary cwds. Wait for `/health` to return 200 by polling with curl (cap at ~15s), then proceed.
- **To stop the API after smoke testing, `pkill -f "uvicorn app.main:app"`.** Always clean up so the next iteration starts fresh.
- **Do not re-create the venv if `apps/api/.venv` exists.** `run-api.sh` handles that.
- **Skip the smoke step entirely when there is nothing runnable to test** (e.g. doc-only or PRD-only edits).
- **One implementation pass, one verification pass.** If the first verification reveals a bug, fix and re-verify once. If it still fails, mark as `> blocker:` and exit — do not enter a multi-round fix-test-fix-test spiral.
- **Keep tool output small.** Every byte of a Bash/Read result lands in your context and costs tokens. Use targeted commands: `find <dir> -maxdepth 2 -name '<pat>'` not bare `find .`; `ls <specific-dir>` not recursive listings; `head`/`tail` when you only need a slice. If a Bash result is truncated as "Output too large", that's a signal you asked the wrong question — rerun with narrower scope rather than reading the persisted file.
- **Never mutate the SQLite DB while uvicorn is holding it.** SQLite uses file locks; concurrent writers get "database is locked" errors. Order: stop API (`pkill -f "uvicorn app.main:app"`) → mutate DB → restart API. If you only need read-only inspection, that's fine alongside a running API.

If you cannot complete the task (missing tool, unclear spec, real blocker), do NOT half-implement. Instead: leave the checkbox unchecked, add a `> blocker:` note immediately under the checkbox describing the problem, commit only that note with message `ralph: blocker on <task>`, and exit.
