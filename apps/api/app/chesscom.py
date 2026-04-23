import io
import time
from datetime import datetime, timezone
from typing import Iterator

import chess.pgn
import httpx

from .openings import classify_game

USER_AGENT = "chess-coach/1.0"
BASE = "https://api.chess.com/pub"
ARCHIVE_SLEEP_SECONDS = 0.3


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    )


def list_archives(username: str) -> list[str]:
    with _client() as c:
        r = c.get(f"{BASE}/player/{username}/games/archives")
        r.raise_for_status()
        return list(r.json().get("archives", []))


def fetch_archive_pgn(url: str) -> str:
    with _client() as c:
        r = c.get(f"{url}/pgn")
        r.raise_for_status()
        return r.text


def _chesscom_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    return url.rstrip("/").rsplit("/", 1)[-1]


def _count_plies(game) -> int:
    count = 0
    node = game
    while node.variations:
        node = node.variations[0]
        count += 1
    return count


def iter_games_from_pgn(pgn_text: str) -> Iterator[dict]:
    stream = io.StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            return
        headers = game.headers
        url = headers.get("Link") or headers.get("Site")
        chesscom_id = _chesscom_id_from_url(url) or _build_synthetic_id(headers)
        played_at = _parse_played_at(headers)
        eco_book, opening_name, opening_ply = classify_game(game)
        import math
        plies = _count_plies(game)
        yield {
            "chesscom_id": chesscom_id,
            "played_at": played_at,
            "time_control": headers.get("TimeControl"),
            "white": headers.get("White"),
            "black": headers.get("Black"),
            "result": headers.get("Result"),
            # Prefer the chess.com ECO header when present, fall back to the
            # book's classification (also gives us a finer-grained name).
            "eco": headers.get("ECO") or eco_book,
            "opening_name": opening_name,
            "opening_ply": opening_ply or None,
            "num_moves": math.ceil(plies / 2) if plies else None,
            "pgn": str(game),
        }


def _build_synthetic_id(headers) -> str:
    parts = [
        headers.get("Date", "?"),
        headers.get("UTCTime", headers.get("Time", "?")),
        headers.get("White", "?"),
        headers.get("Black", "?"),
    ]
    return "synthetic:" + "|".join(parts)


def _parse_played_at(headers) -> str | None:
    date = headers.get("UTCDate") or headers.get("Date")
    time_str = headers.get("UTCTime") or headers.get("Time")
    if not date or date == "????.??.??":
        return None
    try:
        if time_str and time_str != "??:??:??":
            dt = datetime.strptime(f"{date} {time_str}", "%Y.%m.%d %H:%M:%S")
        else:
            dt = datetime.strptime(date, "%Y.%m.%d")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _ingest_one_archive(conn, username: str, url: str) -> tuple[int, int]:
    """Fetch+insert games for one monthly archive. Returns (seen, inserted)."""
    pgn_text = fetch_archive_pgn(url)
    seen = inserted = 0
    for g in iter_games_from_pgn(pgn_text):
        seen += 1
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO games
                (player_username, chesscom_id, played_at, time_control,
                 white, black, result, eco, opening_name, opening_ply, num_moves, pgn)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                g["chesscom_id"],
                g["played_at"],
                g["time_control"],
                g["white"],
                g["black"],
                g["result"],
                g["eco"],
                g["opening_name"],
                g["opening_ply"],
                g.get("num_moves"),
                g["pgn"],
            ),
        )
        if cur.rowcount:
            inserted += 1
    return seen, inserted


def _archive_label(url: str) -> str:
    """`.../games/2024/03` -> `2024-03`."""
    parts = url.rstrip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}-{parts[-1]}"
    return url


def _get_last_synced_at(conn, username: str) -> str | None:
    row = conn.execute(
        "SELECT last_synced_at FROM players WHERE username = ?", (username,)
    ).fetchone()
    return row[0] if row else None


def _incremental_archives(archives: list[str], last_synced_at: str | None) -> list[str]:
    """Drop monthly archives that predate the month we last synced.

    chess.com archives are one-per-month (`.../games/YYYY/MM`). Anything before
    the last-synced month is already fully ingested, so we only re-fetch the
    last-synced month onward — new games land via INSERT OR IGNORE. When we've
    never synced (last_synced_at is None) we keep everything."""
    if not last_synced_at:
        return archives
    # last_synced_at is ISO ("2024-03-17T..."); the month label is "2024-03".
    cutoff = last_synced_at[:7]
    return [u for u in archives if _archive_label(u) >= cutoff]


def sync_player_games(
    username: str, conn, sleep_seconds: float = ARCHIVE_SLEEP_SECONDS, full: bool = False
) -> dict:
    """Blocking sync — kept for the existing POST endpoint and for tests."""
    last_synced_at = _get_last_synced_at(conn, username)
    conn.execute(
        "INSERT OR IGNORE INTO players (username, last_synced_at) VALUES (?, NULL)",
        (username,),
    )
    archives = list_archives(username)
    if not full:
        archives = _incremental_archives(archives, last_synced_at)
    total_seen = 0
    inserted = 0
    for i, url in enumerate(archives):
        if i > 0:
            time.sleep(sleep_seconds)
        seen, ins = _ingest_one_archive(conn, username, url)
        total_seen += seen
        inserted += ins
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE players SET last_synced_at = ? WHERE username = ?",
        (now, username),
    )
    return {
        "username": username,
        "archives": len(archives),
        "games_seen": total_seen,
        "games_inserted": inserted,
        "last_synced_at": now,
    }


def sync_player_games_events(
    username: str, conn, sleep_seconds: float = ARCHIVE_SLEEP_SECONDS, full: bool = False
):
    """Generator version: yields a dict per progress event so an SSE
    endpoint can stream them to the client. Commits after each archive
    so the partial state is visible if the client disconnects."""
    last_synced_at = _get_last_synced_at(conn, username)
    conn.execute(
        "INSERT OR IGNORE INTO players (username, last_synced_at) VALUES (?, NULL)",
        (username,),
    )
    conn.commit()
    try:
        archives = list_archives(username)
    except Exception as e:
        yield {"type": "error", "message": f"failed to list archives: {e}"}
        return
    if not full:
        archives = _incremental_archives(archives, last_synced_at)

    yield {"type": "start", "username": username, "archives": len(archives)}

    total_seen = 0
    total_inserted = 0
    for i, url in enumerate(archives):
        if i > 0:
            time.sleep(sleep_seconds)
        label = _archive_label(url)
        try:
            seen, ins = _ingest_one_archive(conn, username, url)
            conn.commit()
        except Exception as e:
            yield {
                "type": "archive_error",
                "index": i,
                "archive": label,
                "message": str(e),
            }
            continue
        total_seen += seen
        total_inserted += ins
        yield {
            "type": "archive_done",
            "index": i,
            "archive": label,
            "archives_total": len(archives),
            "games_seen_in_archive": seen,
            "games_inserted_in_archive": ins,
            "games_seen_total": total_seen,
            "games_inserted_total": total_inserted,
        }

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE players SET last_synced_at = ? WHERE username = ?",
        (now, username),
    )
    conn.commit()
    yield {
        "type": "done",
        "username": username,
        "archives": len(archives),
        "games_seen": total_seen,
        "games_inserted": total_inserted,
        "last_synced_at": now,
    }
