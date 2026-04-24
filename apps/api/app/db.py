import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "CHESS_COACH_DB",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data.sqlite"),
)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL + busy_timeout so concurrent analysis workers writing the engine_lines
    # cache don't hit "database is locked". journal_mode is a persistent property
    # of the file; busy_timeout/synchronous are per-connection.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
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
            if "phase" not in cols or "pv" not in cols or "motif_details" not in cols:
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
                pv TEXT,
                motif_details TEXT,
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
            CREATE INDEX IF NOT EXISTS idx_attempts_user_puzzle ON puzzle_attempts(username, puzzle_id);
            CREATE TABLE IF NOT EXISTS player_settings (
                username TEXT PRIMARY KEY,
                auto_analyze INTEGER NOT NULL DEFAULT 1,
                auto_depth INTEGER NOT NULL DEFAULT 18,
                auto_workers INTEGER NOT NULL DEFAULT 4
            );
            """
        )
        # Additive migration: opening_name / opening_ply / num_moves on games.
        game_cols = {r[1] for r in conn.execute("PRAGMA table_info(games)").fetchall()}
        if "opening_name" not in game_cols:
            conn.execute("ALTER TABLE games ADD COLUMN opening_name TEXT")
        if "opening_ply" not in game_cols:
            conn.execute("ALTER TABLE games ADD COLUMN opening_ply INTEGER")
        if "num_moves" not in game_cols:
            conn.execute("ALTER TABLE games ADD COLUMN num_moves INTEGER")
            # Backfill existing rows from stored PGN.
            import chess.pgn, io as _io, math as _math
            rows = conn.execute("SELECT id, pgn FROM games WHERE num_moves IS NULL").fetchall()
            for row in rows:
                try:
                    game = chess.pgn.read_game(_io.StringIO(row["pgn"]))
                    board = game.board()
                    plies = 0
                    for move in game.mainline_moves():
                        board.push(move)
                        plies += 1
                    nm = _math.ceil(plies / 2)
                except Exception:
                    nm = None
                conn.execute("UPDATE games SET num_moves = ? WHERE id = ?", (nm, row["id"]))

        # Additive migration: auto_batch / auto_time_format on player_settings.
        settings_cols = {r[1] for r in conn.execute("PRAGMA table_info(player_settings)").fetchall()}
        if "auto_batch" not in settings_cols:
            conn.execute("ALTER TABLE player_settings ADD COLUMN auto_batch INTEGER NOT NULL DEFAULT 50")
        if "auto_time_format" not in settings_cols:
            conn.execute("ALTER TABLE player_settings ADD COLUMN auto_time_format TEXT")

        # engine_lines: position-keyed analysis cache.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS engine_lines (
                fen TEXT NOT NULL,
                multipv_rank INTEGER NOT NULL,
                move_uci TEXT NOT NULL,
                eval_cp INTEGER,
                mate INTEGER,
                pv TEXT NOT NULL DEFAULT '[]',
                depth INTEGER NOT NULL,
                computed_at TEXT NOT NULL,
                PRIMARY KEY (fen, multipv_rank)
            )
            """
        )
        # app_settings: generic key/value store for server-side configuration
        # (LLM provider, encrypted API key, etc.).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        # narratives: cached LLM game narratives keyed by game_id.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS narratives (
                game_id  INTEGER PRIMARY KEY,
                narrative TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(game_id) REFERENCES games(id)
            )
            """
        )
