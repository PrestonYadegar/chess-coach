#!/usr/bin/env python3
"""Pretty-print Claude Code's --output-format stream-json events.

Reads NDJSON from stdin, writes human-readable lines to stdout, flushes
on every line so the wrapper shows live progress.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any


START = time.time()


def stamp() -> str:
    return f"[+{int(time.time() - START):>4}s]"


def short(s: str, n: int = 120) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_tool(name: str, inp: dict[str, Any]) -> str:
    # Lift the most useful field per tool so the line tells you what's happening.
    keys_by_tool = {
        "Bash": ("description", "command"),
        "Read": ("file_path",),
        "Edit": ("file_path",),
        "Write": ("file_path",),
        "Glob": ("pattern",),
        "Grep": ("pattern",),
        "WebFetch": ("url",),
        "WebSearch": ("query",),
    }
    for key in keys_by_tool.get(name, ()):
        val = inp.get(key)
        if val:
            return f"{name}({short(str(val), 100)})"
    return name


def handle(event: dict[str, Any]) -> None:
    t = event.get("type")
    if t == "system" and event.get("subtype") == "init":
        sid = event.get("session_id", "?")
        print(f"{stamp()} session {sid[:8]} started", flush=True)
        return
    if t == "assistant":
        msg = event.get("message", {})
        for block in msg.get("content", []):
            bt = block.get("type")
            if bt == "text":
                text = block.get("text", "").strip()
                if text:
                    print(f"{stamp()} assistant: {short(text, 200)}", flush=True)
            elif bt == "tool_use":
                print(
                    f"{stamp()} → {fmt_tool(block.get('name', '?'), block.get('input', {}))}",
                    flush=True,
                )
        return
    if t == "user":
        msg = event.get("message", {})
        for block in msg.get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                content = content or ""
                is_err = block.get("is_error")
                marker = "✗" if is_err else "✓"
                line = short(str(content), 160) if content else ""
                if line:
                    print(f"{stamp()}   {marker} {line}", flush=True)
        return
    if t == "result":
        sub = event.get("subtype", "?")
        cost = event.get("total_cost_usd")
        dur = event.get("duration_ms")
        bits = [f"result={sub}"]
        if dur is not None:
            bits.append(f"{dur / 1000:.1f}s")
        if cost is not None:
            bits.append(f"${cost:.4f}")
        print(f"{stamp()} {' '.join(bits)}", flush=True)
        return


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Non-JSON line; pass through so we don't swallow useful errors.
            print(line, flush=True)
            continue
        try:
            handle(event)
        except Exception as e:  # parser bug shouldn't kill the loop
            print(f"{stamp()} [parser error: {e}] {short(line, 200)}", flush=True)


if __name__ == "__main__":
    main()
