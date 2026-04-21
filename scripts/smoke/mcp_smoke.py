#!/usr/bin/env python3
"""End-to-end smoke test for the Chess Coach MCP server.

Spawns the MCP server as a subprocess, speaks the JSON-RPC/MCP stdio protocol,
and verifies that list_tools, list_games, and get_game_analysis all work.

Usage:
    python scripts/smoke/mcp_smoke.py [username]
"""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "apps" / "api"
VENV_PYTHON = API_DIR / ".venv" / "bin" / "python"
DB_PATH = API_DIR / "data.sqlite"


def send(proc: subprocess.Popen, msg: dict) -> None:
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line.encode())
    proc.stdin.flush()


def recv(proc: subprocess.Popen, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line:
            return json.loads(line.decode())
        time.sleep(0.05)
    raise TimeoutError("No response from MCP server within timeout")


def check(condition: bool, msg: str) -> None:
    if condition:
        print(f"  PASS  {msg}")
    else:
        print(f"  FAIL  {msg}")
        sys.exit(1)


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else None

    if not VENV_PYTHON.exists():
        print("ERROR: venv missing. Run scripts/run-api.sh once first.", file=sys.stderr)
        sys.exit(1)

    if not DB_PATH.exists():
        print("ERROR: data.sqlite not found. Sync a player first.", file=sys.stderr)
        sys.exit(1)

    # Resolve a username from the DB if not provided.
    if not username:
        import sqlite3
        con = sqlite3.connect(str(DB_PATH))
        row = con.execute("SELECT username FROM players LIMIT 1").fetchone()
        con.close()
        if not row:
            print("ERROR: No players in DB. Run sync first.", file=sys.stderr)
            sys.exit(1)
        username = row[0]
        print(f"Using player: {username}")

    proc = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "app.mcp_server"],
        cwd=str(API_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # ── 1. Initialize ───────────────────────────────────────────────────
        print("\n[1] initialize")
        send(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "0.0.1"},
            },
        })
        resp = recv(proc)
        check("result" in resp, f"initialize succeeded: {resp.get('result', {}).get('serverInfo', {})}")

        # initialized notification
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        # ── 2. List tools ───────────────────────────────────────────────────
        print("\n[2] tools/list")
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        resp = recv(proc)
        tools = resp.get("result", {}).get("tools", [])
        tool_names = {t["name"] for t in tools}
        expected = {
            "list_games", "get_game_pgn", "get_game_analysis",
            "get_mistake_history", "get_top_patterns", "next_puzzle",
            "submit_puzzle_attempt",
        }
        check(expected.issubset(tool_names), f"all 7 tools present: {sorted(tool_names)}")

        # ── 3. list_games ────────────────────────────────────────────────────
        print(f"\n[3] tools/call → list_games(username={username})")
        send(proc, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "list_games",
                "arguments": {"username": username, "limit": 5},
            },
        })
        resp = recv(proc)
        content = resp.get("result", {}).get("content", [])
        check(len(content) > 0, "got content")
        data = json.loads(content[0]["text"])
        check("error" not in data, f"no error: total={data.get('total')}")
        check(isinstance(data.get("games"), list), f"games list returned ({len(data.get('games', []))} items)")

        # ── 4. get_game_analysis ─────────────────────────────────────────────
        # Find a game with analysis.
        import sqlite3
        con = sqlite3.connect(str(DB_PATH))
        row = con.execute(
            "SELECT g.id FROM analyses a JOIN games g ON g.id=a.game_id"
            " WHERE g.player_username=? LIMIT 1", (username,)
        ).fetchone()
        con.close()

        if row:
            game_id = row[0]
            print(f"\n[4] tools/call → get_game_analysis(game_id={game_id})")
            send(proc, {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "get_game_analysis",
                    "arguments": {"game_id": game_id},
                },
            })
            resp = recv(proc)
            content = resp.get("result", {}).get("content", [])
            check(len(content) > 0, "got content")
            data = json.loads(content[0]["text"])
            check("error" not in data, "no error")
            check(len(data.get("plies", [])) > 0, f"plies returned ({len(data.get('plies', []))})")
        else:
            print("\n[4] get_game_analysis — skipped (no analyzed games in DB)")

        print("\nAll checks passed. MCP server is working end-to-end.\n")

    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    main()
