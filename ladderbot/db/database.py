"""Database manager for LadderBot.

Provides connection factory and CRUD helpers for all tables.
Uses SQLite with WAL mode for concurrent read access from the web dashboard.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# Path to schema.sql relative to this file
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Default database path
_DEFAULT_DB_PATH = str(Path(__file__).parent.parent.parent / "data" / "ladderbot.db")


def get_db(db_path: str | None = None) -> sqlite3.Connection:
    """Get a database connection, creating the DB and tables if needed.

    Args:
        db_path: Path to the SQLite database file. Defaults to data/ladderbot.db.

    Returns:
        sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    if db_path is None:
        db_path = _DEFAULT_DB_PATH

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Run schema if tables don't exist
    _init_schema(conn)

    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Execute schema.sql to create tables if they don't exist."""
    schema_sql = _SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)


# -- Game helpers --------------------------------------------------------------


def insert_game(
    conn: sqlite3.Connection,
    game_id: str,
    sport: str,
    home_team: str,
    away_team: str,
    game_date: str,
    home_score: int | None = None,
    away_score: int | None = None,
    status: str = "scheduled",
) -> None:
    """Insert or update a game record."""
    conn.execute(
        """
        INSERT INTO games (game_id, sport, home_team, away_team, game_date, home_score, away_score, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_id) DO UPDATE SET
            home_score = COALESCE(excluded.home_score, games.home_score),
            away_score = COALESCE(excluded.away_score, games.away_score),
            status = excluded.status
        """,
        (game_id, sport, home_team, away_team, game_date, home_score, away_score, status),
    )
    conn.commit()


# -- Odds helpers --------------------------------------------------------------


def insert_odds_snapshot(
    conn: sqlite3.Connection,
    game_id: str,
    bookmaker: str,
    market: str,
    outcome: str,
    price: int,
    point: float | None = None,
) -> int:
    """Insert an odds snapshot. Returns the row id."""
    cursor = conn.execute(
        """
        INSERT INTO odds_snapshots (game_id, bookmaker, market, outcome, price, point)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (game_id, bookmaker, market, outcome, price, point),
    )
    conn.commit()
    return cursor.lastrowid


# -- Prediction helpers --------------------------------------------------------


def insert_prediction(
    conn: sqlite3.Connection,
    game_id: str,
    market: str,
    outcome: str,
    model_prob: float,
    book_prob: float,
    edge: float,
) -> int:
    """Insert a model prediction. Returns the row id."""
    cursor = conn.execute(
        """
        INSERT INTO model_predictions (game_id, market, outcome, model_prob, book_prob, edge)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (game_id, market, outcome, model_prob, book_prob, edge),
    )
    conn.commit()
    return cursor.lastrowid


# -- Pick helpers --------------------------------------------------------------


def insert_pick(
    conn: sqlite3.Connection,
    game_id: str,
    market: str,
    outcome: str,
    odds_at_pick: int,
    parlay_id: int | None = None,
    total_line: float | None = None,
) -> int:
    """Insert a pick. Returns the pick_id."""
    cursor = conn.execute(
        """
        INSERT INTO picks (parlay_id, game_id, market, outcome, odds_at_pick, total_line)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (parlay_id, game_id, market, outcome, odds_at_pick, total_line),
    )
    conn.commit()
    return cursor.lastrowid


# -- Parlay helpers ------------------------------------------------------------


def insert_parlay(
    conn: sqlite3.Connection,
    leg1_pick_id: int,
    leg2_pick_id: int,
    combined_odds: int,
    combined_edge: float,
) -> int:
    """Insert a parlay and link picks back to it. Returns the parlay_id."""
    cursor = conn.execute(
        """
        INSERT INTO parlays (leg1_pick_id, leg2_pick_id, combined_odds, combined_edge)
        VALUES (?, ?, ?, ?)
        """,
        (leg1_pick_id, leg2_pick_id, combined_odds, combined_edge),
    )
    parlay_id = cursor.lastrowid

    # Link picks back to the parlay so joins on picks.parlay_id work
    conn.execute(
        "UPDATE picks SET parlay_id = ? WHERE pick_id IN (?, ?)",
        (parlay_id, leg1_pick_id, leg2_pick_id),
    )
    conn.commit()
    return parlay_id


def update_parlay_placed(
    conn: sqlite3.Connection,
    parlay_id: int,
    fd_leg1_odds: int,
    fd_leg2_odds: int,
    fd_parlay_odds: int,
    fd_edge: float,
    actual_stake: float,
) -> None:
    """Mark a parlay as placed with FanDuel odds."""
    conn.execute(
        """
        UPDATE parlays SET
            fd_leg1_odds = ?,
            fd_leg2_odds = ?,
            fd_parlay_odds = ?,
            fd_edge = ?,
            placed = 1,
            placed_at = datetime('now'),
            actual_stake = ?
        WHERE parlay_id = ?
        """,
        (fd_leg1_odds, fd_leg2_odds, fd_parlay_odds, fd_edge, actual_stake, parlay_id),
    )
    conn.commit()


def update_parlay_skipped(
    conn: sqlite3.Connection,
    parlay_id: int,
    skip_reason: str = "user_choice",
) -> None:
    """Mark a parlay as skipped."""
    conn.execute(
        """
        UPDATE parlays SET skipped = 1, skip_reason = ?
        WHERE parlay_id = ?
        """,
        (skip_reason, parlay_id),
    )
    conn.commit()


def update_parlay_result(
    conn: sqlite3.Connection,
    parlay_id: int,
    result: str,
    payout: float | None = None,
) -> None:
    """Update a parlay's result."""
    conn.execute(
        """
        UPDATE parlays SET result = ?, payout = ?
        WHERE parlay_id = ?
        """,
        (result, payout, parlay_id),
    )
    conn.commit()


# -- Ladder helpers ------------------------------------------------------------


def insert_ladder_state(
    conn: sqlite3.Connection,
    attempt_id: int,
    step: int,
    bankroll: float,
    parlay_id: int | None = None,
    result: str | None = None,
) -> int:
    """Insert a ladder state row. Returns the row id."""
    cursor = conn.execute(
        """
        INSERT INTO ladder_state (attempt_id, step, bankroll, parlay_id, result)
        VALUES (?, ?, ?, ?, ?)
        """,
        (attempt_id, step, bankroll, parlay_id, result),
    )
    conn.commit()
    return cursor.lastrowid


def get_ladder_state(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """Get the most recent ladder state row."""
    return conn.execute(
        "SELECT * FROM ladder_state ORDER BY id DESC LIMIT 1"
    ).fetchone()


def get_active_ladder(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """Get the latest ladder state that has no terminal result.

    Returns the most recent pending (result IS NULL) state row. Returns None
    if no active ladder exists.
    """
    row = conn.execute(
        """
        SELECT * FROM ladder_state
        WHERE result IS NULL
        ORDER BY attempt_id DESC, step DESC
        LIMIT 1
        """
    ).fetchone()
    return row


# -- Flat bet helpers ----------------------------------------------------------


def insert_flat_bet(
    conn: sqlite3.Connection,
    pick_id: int,
    amount: float,
    odds: int,
    result: str | None = None,
    profit_loss: float | None = None,
) -> int:
    """Insert a flat bet record. Returns the row id."""
    cursor = conn.execute(
        """
        INSERT INTO flat_bets (pick_id, amount, odds, result, profit_loss)
        VALUES (?, ?, ?, ?, ?)
        """,
        (pick_id, amount, odds, result, profit_loss),
    )
    conn.commit()
    return cursor.lastrowid


# -- Query helpers -------------------------------------------------------------


def get_today_parlays(conn: sqlite3.Connection, today: str | None = None) -> list[sqlite3.Row]:
    """Get all parlays created today."""
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    return conn.execute(
        """
        SELECT * FROM parlays
        WHERE date(created_at) = ?
        ORDER BY combined_edge DESC
        """,
        (today,),
    ).fetchall()


def get_games_by_date(conn: sqlite3.Connection, game_date: str) -> list[sqlite3.Row]:
    """Get all games for a given date."""
    return conn.execute(
        "SELECT * FROM games WHERE game_date = ? ORDER BY game_id",
        (game_date,),
    ).fetchall()
