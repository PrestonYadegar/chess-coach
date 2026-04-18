import io
import time
from datetime import datetime, timezone
from typing import Iterator

import chess.pgn
import httpx

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
        yield {
            "chesscom_id": chesscom_id,
            "played_at": played_at,
            "time_control": headers.get("TimeControl"),
            "white": headers.get("White"),
            "black": headers.get("Black"),
            "result": headers.get("Result"),
            "eco": headers.get("ECO"),
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


def sync_player_games(username: str, conn, sleep_seconds: float = ARCHIVE_SLEEP_SECONDS) -> dict:
    conn.execute(
        "INSERT OR IGNORE INTO players (username, last_synced_at) VALUES (?, NULL)",
        (username,),
    )
    archives = list_archives(username)
    total_seen = 0
    inserted = 0
    for i, url in enumerate(archives):
        if i > 0:
            time.sleep(sleep_seconds)
        pgn_text = fetch_archive_pgn(url)
        for g in iter_games_from_pgn(pgn_text):
            total_seen += 1
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO games
                    (player_username, chesscom_id, played_at, time_control,
                     white, black, result, eco, pgn)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    g["pgn"],
                ),
            )
            if cur.rowcount:
                inserted += 1
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
