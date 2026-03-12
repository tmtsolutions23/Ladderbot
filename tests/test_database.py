"""Tests for the database manager."""
import os
import sqlite3
import tempfile
from datetime import datetime, date

import pytest
from ladderbot.db.database import (
    get_db,
    insert_game,
    insert_odds_snapshot,
    insert_prediction,
    insert_pick,
    insert_parlay,
    update_parlay_placed,
    update_parlay_result,
    get_ladder_state,
    insert_ladder_state,
    insert_flat_bet,
    get_active_ladder,
)


@pytest.fixture
def db_path(tmp_path):
    """Provide a temporary database path."""
    return str(tmp_path / "test_ladderbot.db")


@pytest.fixture
def db(db_path):
    """Provide an initialized database connection."""
    conn = get_db(db_path)
    yield conn
    conn.close()


def _seed_game(db, game_id="nba_20260311_BOS_MIL"):
    """Insert a game record for FK satisfaction."""
    insert_game(
        db,
        game_id=game_id,
        sport="nba",
        home_team="BOS",
        away_team="MIL",
        game_date="2026-03-11",
    )


def _seed_picks(db):
    """Insert a game and two picks, returning (pick1_id, pick2_id)."""
    _seed_game(db, "nba_20260311_BOS_MIL")
    _seed_game(db, "nhl_20260311_NYR_BOS")
    pick1 = insert_pick(db, game_id="nba_20260311_BOS_MIL", market="h2h", outcome="BOS", odds_at_pick=-160)
    pick2 = insert_pick(db, game_id="nhl_20260311_NYR_BOS", market="totals", outcome="Over", odds_at_pick=120)
    return pick1, pick2


class TestGetDb:
    def test_creates_database_file(self, db_path):
        conn = get_db(db_path)
        assert os.path.exists(db_path)
        conn.close()

    def test_creates_all_tables(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        expected = {
            "games",
            "odds_snapshots",
            "model_predictions",
            "picks",
            "parlays",
            "ladder_state",
            "flat_bets",
            "team_stats",
            "goalie_confirmations",
        }
        assert expected.issubset(tables)

    def test_idempotent_schema(self, db_path):
        """Calling get_db twice should not raise or duplicate tables."""
        conn1 = get_db(db_path)
        conn1.close()
        conn2 = get_db(db_path)
        cursor = conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        # No duplicates
        assert len(tables) == len(set(tables))
        conn2.close()


class TestInsertGame:
    def test_insert_and_retrieve(self, db):
        insert_game(
            db,
            game_id="nba_20260311_BOS_MIL",
            sport="nba",
            home_team="BOS",
            away_team="MIL",
            game_date="2026-03-11",
        )
        row = db.execute(
            "SELECT * FROM games WHERE game_id = ?",
            ("nba_20260311_BOS_MIL",),
        ).fetchone()
        assert row is not None
        assert row["sport"] == "nba"
        assert row["home_team"] == "BOS"
        assert row["away_team"] == "MIL"
        assert row["status"] == "scheduled"

    def test_upsert_updates_score(self, db):
        insert_game(
            db,
            game_id="nba_20260311_BOS_MIL",
            sport="nba",
            home_team="BOS",
            away_team="MIL",
            game_date="2026-03-11",
        )
        insert_game(
            db,
            game_id="nba_20260311_BOS_MIL",
            sport="nba",
            home_team="BOS",
            away_team="MIL",
            game_date="2026-03-11",
            home_score=112,
            away_score=105,
            status="final",
        )
        row = db.execute(
            "SELECT * FROM games WHERE game_id = ?",
            ("nba_20260311_BOS_MIL",),
        ).fetchone()
        assert row["home_score"] == 112
        assert row["status"] == "final"


class TestInsertOddsSnapshot:
    def test_insert_and_retrieve(self, db):
        _seed_game(db)
        insert_odds_snapshot(
            db,
            game_id="nba_20260311_BOS_MIL",
            bookmaker="draftkings",
            market="h2h",
            outcome="BOS",
            price=-160,
        )
        rows = db.execute(
            "SELECT * FROM odds_snapshots WHERE game_id = ?",
            ("nba_20260311_BOS_MIL",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["price"] == -160
        assert rows[0]["bookmaker"] == "draftkings"


class TestInsertPrediction:
    def test_insert_and_retrieve(self, db):
        _seed_game(db)
        insert_prediction(
            db,
            game_id="nba_20260311_BOS_MIL",
            market="h2h",
            outcome="BOS",
            model_prob=0.642,
            book_prob=0.615,
            edge=0.027,
        )
        row = db.execute(
            "SELECT * FROM model_predictions WHERE game_id = ?",
            ("nba_20260311_BOS_MIL",),
        ).fetchone()
        assert row is not None
        assert abs(row["model_prob"] - 0.642) < 0.001


class TestParlayOperations:
    def test_insert_parlay(self, db):
        pick1, pick2 = _seed_picks(db)
        parlay_id = insert_parlay(
            db,
            leg1_pick_id=pick1,
            leg2_pick_id=pick2,
            combined_odds=257,
            combined_edge=0.048,
        )
        assert parlay_id is not None
        row = db.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()
        assert row["combined_odds"] == 257

    def test_update_placed(self, db):
        pick1, pick2 = _seed_picks(db)
        parlay_id = insert_parlay(
            db,
            leg1_pick_id=pick1,
            leg2_pick_id=pick2,
            combined_odds=257,
            combined_edge=0.048,
        )
        update_parlay_placed(
            db,
            parlay_id=parlay_id,
            fd_leg1_odds=-155,
            fd_leg2_odds=115,
            fd_parlay_odds=245,
            fd_edge=0.041,
            actual_stake=32.50,
        )
        row = db.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()
        assert row["placed"] == 1
        assert row["fd_parlay_odds"] == 245
        assert row["actual_stake"] == 32.50
        assert row["placed_at"] is not None

    def test_update_result(self, db):
        pick1, pick2 = _seed_picks(db)
        parlay_id = insert_parlay(
            db,
            leg1_pick_id=pick1,
            leg2_pick_id=pick2,
            combined_odds=257,
            combined_edge=0.048,
        )
        update_parlay_result(db, parlay_id=parlay_id, result="won", payout=116.19)
        row = db.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()
        assert row["result"] == "won"
        assert row["payout"] == 116.19


class TestLadderState:
    def test_insert_and_get(self, db):
        insert_ladder_state(
            db,
            attempt_id=1,
            step=1,
            bankroll=10.0,
            parlay_id=None,
            result=None,
        )
        state = get_ladder_state(db)
        assert state is not None
        assert state["attempt_id"] == 1
        assert state["step"] == 1
        assert state["bankroll"] == 10.0

    def test_get_active_ladder_empty(self, db):
        result = get_active_ladder(db)
        assert result is None

    def test_get_active_ladder(self, db):
        insert_ladder_state(db, attempt_id=1, step=1, bankroll=10.0)
        insert_ladder_state(db, attempt_id=1, step=2, bankroll=32.50)
        state = get_active_ladder(db)
        assert state["step"] == 2
        assert state["bankroll"] == 32.50


class TestFlatBet:
    def test_insert_flat_bet(self, db):
        _seed_game(db)
        pick_id = insert_pick(db, game_id="nba_20260311_BOS_MIL", market="h2h", outcome="BOS", odds_at_pick=-160)
        insert_flat_bet(db, pick_id=pick_id, amount=10.0, odds=257, result="won", profit_loss=25.70)
        row = db.execute("SELECT * FROM flat_bets WHERE pick_id = ?", (pick_id,)).fetchone()
        assert row["profit_loss"] == 25.70
