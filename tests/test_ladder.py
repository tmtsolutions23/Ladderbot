"""Tests for ladder state machine and shadow portfolio."""
import pytest

from ladderbot.db.database import get_db, insert_game, insert_pick, insert_parlay
from ladderbot.parlay.ladder import LadderTracker, ShadowPortfolio


@pytest.fixture
def db(tmp_path):
    """Provide an initialized database connection."""
    conn = get_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


@pytest.fixture
def config():
    return {
        "ladder": {
            "starting_amount": 10.0,
            "target_amount": 1000.0,
            "max_attempts": 50,
        }
    }


@pytest.fixture
def ladder(db, config):
    return LadderTracker(db, config)


@pytest.fixture
def shadow(db):
    return ShadowPortfolio(db)


def _seed_pick(db, game_id="nba_g1", odds=-160):
    """Insert a game and pick, return pick_id."""
    insert_game(db, game_id=game_id, sport="nba", home_team="BOS",
                away_team="MIL", game_date="2026-03-11")
    return insert_pick(db, game_id=game_id, market="h2h",
                       outcome="BOS", odds_at_pick=odds)


class TestLadderTracker:
    def test_initial_status_is_idle(self, ladder):
        assert ladder.status == LadderTracker.IDLE

    def test_initial_step_is_zero(self, ladder):
        assert ladder.current_step == 0

    def test_initial_bankroll(self, ladder):
        assert ladder.current_bankroll == 10.0

    def test_initial_attempt_number(self, ladder):
        assert ladder.attempt_number == 0

    def test_start_new_attempt(self, ladder):
        result = ladder.start_new_attempt()
        assert result["attempt_id"] == 1
        assert result["step"] == 1
        assert result["bankroll"] == 10.0
        assert ladder.status == LadderTracker.ACTIVE
        assert ladder.current_step == 1
        assert ladder.attempt_number == 1

    def test_win_advances_step(self, ladder):
        ladder.start_new_attempt()
        result = ladder.record_win(32.50)
        assert result["bankroll"] == 32.50
        assert result["complete"] is False
        assert ladder.current_step == 2
        assert ladder.current_bankroll == 32.50
        assert ladder.status == LadderTracker.ACTIVE

    def test_loss_resets_to_idle(self, ladder):
        ladder.start_new_attempt()
        result = ladder.record_loss()
        assert result["attempt_id"] == 1
        assert result["step_reached"] == 1
        assert ladder.status == LadderTracker.IDLE
        assert ladder.current_step == 0
        assert ladder.current_bankroll == 10.0

    def test_multiple_wins_to_complete(self, ladder):
        ladder.start_new_attempt()
        ladder.record_win(32.50)
        ladder.record_win(105.63)
        ladder.record_win(343.28)
        result = ladder.record_win(1115.67)
        assert result["complete"] is True
        assert ladder.status == LadderTracker.COMPLETE

    def test_loss_after_progress(self, ladder):
        ladder.start_new_attempt()
        ladder.record_win(32.50)
        ladder.record_win(105.63)
        ladder.record_loss()
        assert ladder.status == LadderTracker.IDLE

    def test_multiple_attempts(self, ladder):
        # Attempt 1: lose
        ladder.start_new_attempt()
        ladder.record_loss()
        assert ladder.attempt_number == 1

        # Attempt 2: lose
        ladder.start_new_attempt()
        ladder.record_loss()
        assert ladder.attempt_number == 2

        # Attempt 3: in progress
        ladder.start_new_attempt()
        assert ladder.attempt_number == 3
        assert ladder.status == LadderTracker.ACTIVE

    def test_place_bet(self, ladder, db):
        # Create a real parlay to satisfy FK constraint
        insert_game(db, "nba_g1", "nba", "BOS", "MIL", "2026-03-11")
        p1 = insert_pick(db, "nba_g1", "h2h", "BOS", -160)
        insert_game(db, "nba_g2", "nba", "LAL", "GSW", "2026-03-11")
        p2 = insert_pick(db, "nba_g2", "h2h", "LAL", -140)
        parlay_id = insert_parlay(db, p1, p2, 225, 0.05)

        ladder.start_new_attempt()
        result = ladder.place_bet(parlay_id=parlay_id)
        assert result["parlay_id"] == parlay_id
        assert result["step"] == 1

    def test_get_ladder_display(self, ladder):
        ladder.start_new_attempt()
        display = ladder.get_ladder_display()
        assert display["status"] == LadderTracker.ACTIVE
        assert display["current_step"] == 1
        assert display["current_bankroll"] == 10.0
        assert display["total_steps"] == 4
        assert display["attempt_number"] == 1
        assert display["starting_amount"] == 10.0
        assert display["target_amount"] == 1000.0

    def test_get_history(self, ladder):
        ladder.start_new_attempt()
        ladder.record_win(32.50)
        ladder.record_loss()

        ladder.start_new_attempt()
        ladder.record_loss()

        history = ladder.get_history()
        assert len(history) == 2
        assert history[0]["attempt_id"] == 1
        assert len(history[0]["steps"]) == 2
        assert history[1]["attempt_id"] == 2

    def test_total_steps(self, ladder):
        # $10 -> $1000 at 3.25 decimal = 4 steps
        assert ladder.total_steps == 4


class TestShadowPortfolio:
    def test_record_bet(self, shadow, db):
        pick_id = _seed_pick(db)
        bet_id = shadow.record_bet(pick_id, -160)
        assert bet_id is not None

    def test_record_win_result(self, shadow, db):
        pick_id = _seed_pick(db, odds=-160)
        shadow.record_bet(pick_id, -160)
        profit = shadow.record_result(pick_id, "won")
        # -160 -> decimal 1.625 -> profit = 10 * 0.625 = 6.25
        assert profit == pytest.approx(6.25, rel=1e-2)

    def test_record_loss_result(self, shadow, db):
        pick_id = _seed_pick(db)
        shadow.record_bet(pick_id, -160)
        profit = shadow.record_result(pick_id, "lost")
        assert profit == -10.0

    def test_get_stats_empty(self, shadow):
        stats = shadow.get_stats()
        assert stats["wins"] == 0
        assert stats["losses"] == 0
        assert stats["profit"] == 0.0
        assert stats["roi"] == 0.0

    def test_get_stats_with_results(self, shadow, db):
        p1 = _seed_pick(db, "nba_g1", -160)
        p2 = _seed_pick(db, "nba_g2", 120)

        shadow.record_bet(p1, -160)
        shadow.record_bet(p2, 120)
        shadow.record_result(p1, "won")
        shadow.record_result(p2, "lost")

        stats = shadow.get_stats()
        assert stats["wins"] == 1
        assert stats["losses"] == 1
        assert stats["total_bets"] == 2
        # Win: 10 * 0.625 = 6.25; Loss: -10 -> net: -3.75
        assert stats["profit"] == pytest.approx(-3.75, rel=1e-2)

    def test_by_sport_breakdown(self, shadow, db):
        insert_game(db, "nhl_g1", "nhl", "NYR", "BOS", "2026-03-11")
        p1 = insert_pick(db, "nhl_g1", "h2h", "NYR", 150)

        shadow.record_bet(p1, 150)
        shadow.record_result(p1, "won")

        stats = shadow.get_stats()
        assert "nhl" in stats["by_sport"]
        assert stats["by_sport"]["nhl"]["wins"] == 1
