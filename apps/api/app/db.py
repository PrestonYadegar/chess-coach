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
        # One-shot migration: the analyses schema gained a `phase` column.
        # Drop the old table on first boot under the new code; results will be
        # rebuilt as games are re-analyzed.
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='analyses'"
        ).fetchone()
        if existing:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(analyses)").fetchall()}
            if "phase" not in cols:
                conn.execute("DROP TABLE analyses")
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
            CREATE TABLE IF NOT EXISTS analyses (
                game_id INTEGER NOT NULL,
                ply INTEGER NOT NULL,
                fen TEXT NOT NULL,
                best_move TEXT,
                played_move TEXT,
                eval_cp INTEGER,
                classification TEXT,
                motif_tags TEXT,
                phase TEXT,
                PRIMARY KEY (game_id, ply),
                FOREIGN KEY(game_id) REFERENCES games(id)
            );
            CREATE INDEX IF NOT EXISTS idx_analyses_game ON analyses(game_id);
            CREATE INDEX IF NOT EXISTS idx_analyses_phase ON analyses(phase);
            CREATE TABLE IF NOT EXISTS puzzles (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'lichess',
                fen TEXT NOT NULL,
                solution_moves TEXT NOT NULL,
                themes TEXT NOT NULL DEFAULT '[]',
                rating INTEGER,
                popularity INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_puzzles_themes ON puzzles(themes);
            CREATE TABLE IF NOT EXISTS puzzle_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                puzzle_id TEXT NOT NULL,
                username TEXT NOT NULL,
                solved INTEGER NOT NULL,
                attempted_at TEXT NOT NULL,
                FOREIGN KEY(puzzle_id) REFERENCES puzzles(id),
                FOREIGN KEY(username) REFERENCES players(username)
            );
            CREATE INDEX IF NOT EXISTS idx_attempts_user ON puzzle_attempts(username, attempted_at);
            """
        )
        # Additive migration: opening_name / opening_ply on games.
        game_cols = {r[1] for r in conn.execute("PRAGMA table_info(games)").fetchall()}
        if "opening_name" not in game_cols:
            conn.execute("ALTER TABLE games ADD COLUMN opening_name TEXT")
        if "opening_ply" not in game_cols:
            conn.execute("ALTER TABLE games ADD COLUMN opening_ply INTEGER")
