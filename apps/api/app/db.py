import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "CHESS_COACH_DB",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.sqlite"),
)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def conn_ctx():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with conn_ctx() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                username TEXT PRIMARY KEY,
                last_synced_at TEXT
            );
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_username TEXT NOT NULL,
                chesscom_id TEXT NOT NULL,
                played_at TEXT,
                time_control TEXT,
                white TEXT,
                black TEXT,
                result TEXT,
                eco TEXT,
                pgn TEXT NOT NULL,
                UNIQUE(player_username, chesscom_id),
                FOREIGN KEY(player_username) REFERENCES players(username)
            );
            CREATE INDEX IF NOT EXISTS idx_games_player ON games(player_username, played_at);
            """
        )
