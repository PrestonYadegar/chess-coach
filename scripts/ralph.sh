#!/usr/bin/env bash
# ralph.sh — drive Claude Code through spec/PROGRESS.md, one checkbox at a time.
#
# Each iteration we hand Claude the same prompt: read the PRD, read PROGRESS,
# pick the first unchecked item, implement it, tick the box, commit, exit.
# We loop until PROGRESS has no unchecked items or MAX_ITERS is hit.
#
# Usage:
#   scripts/ralph.sh                  # run with defaults
#   MAX_ITERS=3 scripts/ralph.sh      # cap iterations
#   DRY_RUN=1 scripts/ralph.sh        # print the prompt and exit
#
# Safety rails:
#   - aborts if the working tree is dirty at start (don't mix manual + loop work)
#   - aborts if an iteration leaves the tree dirty (Claude must commit its own work)
#   - aborts if PROGRESS is unchanged after an iteration (no infinite no-op loop)
#   - per-iteration timeout via PER_ITER_TIMEOUT (default 1800s)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MAX_ITERS="${MAX_ITERS:-20}"
PER_ITER_TIMEOUT="${PER_ITER_TIMEOUT:-1800}"
DRY_RUN="${DRY_RUN:-0}"
MODEL="${MODEL:-claude-opus-4-7}"
HEARTBEAT_SECS="${HEARTBEAT_SECS:-15}"
LOG_DIR="${LOG_DIR:-.ralph}"

PROGRESS="spec/PROGRESS.md"
PRD="spec/PRD.md"

if ! command -v claude >/dev/null 2>&1; then
  echo "error: 'claude' CLI not found on PATH. Install Claude Code first." >&2
  exit 1
fi

if [[ ! -f "$PRD" || ! -f "$PROGRESS" ]]; then
  echo "error: missing $PRD or $PROGRESS" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is dirty. Commit or stash before running ralph.sh." >&2
  git status --short
  exit 1
fi

count_unchecked() {
  grep -cE '^- \[ \]' "$PROGRESS" || true
}

PROMPT_FILE="$ROOT/scripts/ralph_prompt.md"
if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "error: missing $PROMPT_FILE" >&2
  exit 1
fi
PROMPT=$(<"$PROMPT_FILE")

if [[ "$DRY_RUN" == "1" ]]; then
  echo "=== ralph prompt ==="
  echo "$PROMPT"
  echo "=== end prompt ==="
  echo "unchecked items: $(count_unchecked)"
  exit 0
fi

iter=0
while (( iter < MAX_ITERS )); do
  iter=$((iter + 1))
  remaining=$(count_unchecked)
  if (( remaining == 0 )); then
    echo "[ralph] PROGRESS.md has no unchecked items. Done."
    exit 0
  fi

  mkdir -p "$LOG_DIR"
  LOG_FILE="$LOG_DIR/iter-$(printf '%03d' "$iter").log"
  RAW_FILE="$LOG_DIR/iter-$(printf '%03d' "$iter").jsonl"
  echo "[ralph] iteration $iter/$MAX_ITERS — $remaining items remaining"
  echo "[ralph] log: $LOG_FILE  raw stream: $RAW_FILE"
  before_progress_hash=$(shasum "$PROGRESS" | awk '{print $1}')
  before_sha=$(git rev-parse HEAD)
  iter_start=$(date +%s)

  # Heartbeat: print elapsed time every $HEARTBEAT_SECS while claude runs.
  (
    while :; do
      sleep "$HEARTBEAT_SECS"
      now=$(date +%s); elapsed=$((now - iter_start))
      echo "[ralph] …still working ($elapsed s elapsed, iteration $iter)"
    done
  ) &
  HEARTBEAT_PID=$!
  trap 'kill $HEARTBEAT_PID 2>/dev/null || true' EXIT INT TERM

  # Stream Claude's JSON events through a small Python pretty-printer so
  # tool calls show up live. Raw JSONL is tee'd to $RAW_FILE for forensics.
  set +e
  claude -p "$PROMPT" \
        --model "$MODEL" \
        --dangerously-skip-permissions \
        --verbose \
        --output-format stream-json \
    | tee "$RAW_FILE" \
    | python3 "$ROOT/scripts/ralph_stream.py" \
    | tee "$LOG_FILE"
  claude_rc=${PIPESTATUS[0]}
  set -e

  kill $HEARTBEAT_PID 2>/dev/null || true
  trap - EXIT INT TERM

  if (( claude_rc != 0 )); then
    echo "[ralph] claude exited with code $claude_rc. Stopping." >&2
    exit 1
  fi

  if [[ -n "$(git status --porcelain)" ]]; then
    echo "[ralph] tree is dirty after iteration — Claude did not commit its work. Stopping." >&2
    git status --short
    exit 1
  fi

  after_progress_hash=$(shasum "$PROGRESS" | awk '{print $1}')
  after_sha=$(git rev-parse HEAD)

  if [[ "$before_sha" == "$after_sha" ]]; then
    echo "[ralph] no new commit this iteration. Stopping." >&2
    exit 1
  fi

  if [[ "$before_progress_hash" == "$after_progress_hash" ]]; then
    echo "[ralph] PROGRESS.md unchanged — possible no-op. Stopping." >&2
    exit 1
  fi

  # Backfill the commit SHA into the iteration log line.
  sed -i.bak "s/<will-fill-sha>/$after_sha/" "$PROGRESS" && rm -f "$PROGRESS.bak"
  if [[ -n "$(git status --porcelain)" ]]; then
    git add "$PROGRESS"
    git commit --amend --no-edit --no-verify >/dev/null
  fi

  echo "[ralph] iteration $iter committed: $after_sha"
done

echo "[ralph] reached MAX_ITERS=$MAX_ITERS. Run again to continue."
