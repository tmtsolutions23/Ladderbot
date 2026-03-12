"""Tests for CLV tracker."""
import pytest

from ladderbot.db.database import get_db, insert_game, insert_pick
from ladderbot.tracking.clv import CLVTracker


@pytest.fixture
def db(tmp_path):
    conn = get_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


@pytest.fixture
def clv(db):
    return CLVTracker(db)


def _seed_pick(db, game_id="nba_g1", odds=-160, market="h2h", outcome="BOS"):
    insert_game(db, game_id, "nba", "BOS", "MIL", "2026-03-11")
    return insert_pick(db, game_id, market, outcome, odds)


class TestCLVTracker:
    def test_record_pick(self, clv, db):
        pick_id = _seed_pick(db)
        clv.record_pick(pick_id, "nba_g1", "h2h", -160)
        row = db.execute("SELECT odds_at_pick FROM picks WHERE pick_id = ?",
                         (pick_id,)).fetchone()
        assert row["odds_at_pick"] == -160

    def test_record_closing_odds(self, clv, db):
        pick_id = _seed_pick(db)
        updated = clv.record_closing_odds("nba_g1", "h2h", -170)
        assert updated == 1
        row = db.execute("SELECT closing_odds FROM picks WHERE pick_id = ?",
                         (pick_id,)).fetchone()
        assert row["closing_odds"] == -170

    def test_positive_clv(self, clv, db):
        """Got -160, closed at -170 -> we got better odds (positive CLV)."""
        pick_id = _seed_pick(db, odds=-160)
        clv.record_closing_odds("nba_g1", "h2h", -170)
        result = clv.compute_clv(pick_id)
        # pick_implied(-160) = 160/260 = 0.6154
        # closing_implied(-170) = 170/270 = 0.6296
        # CLV = 0.6296 - 0.6154 = +0.0143
        assert result is not None
        assert result > 0
        assert result == pytest.approx(0.0143, abs=0.005)

    def test_negative_clv(self, clv, db):
        """Got -160, closed at -150 -> we got worse odds (negative CLV)."""
        pick_id = _seed_pick(db, odds=-160)
        clv.record_closing_odds("nba_g1", "h2h", -150)
        result = clv.compute_clv(pick_id)
        # pick_implied(-160) = 0.6154
        # closing_implied(-150) = 150/250 = 0.60
        # CLV = 0.60 - 0.6154 = -0.0154
        assert result is not None
        assert result < 0

    def test_compute_clv_no_closing(self, clv, db):
        """No closing odds -> return None."""
        pick_id = _seed_pick(db)
        result = clv.compute_clv(pick_id)
        assert result is None

    def test_compute_clv_nonexistent(self, clv):
        result = clv.compute_clv(9999)
        assert result is None

    def test_rolling_clv(self, clv, db):
        """Rolling CLV averages over last n picks."""
        for i in range(5):
            gid = f"nba_g{i}"
            pid = _seed_pick(db, game_id=gid, odds=-160)
            # Alternating closing odds: -170 (positive CLV) and -150 (negative)
            closing = -170 if i % 2 == 0 else -150
            clv.record_closing_odds(gid, "h2h", closing)
            clv.compute_clv(pid)

        avg = clv.get_rolling_clv(n=5)
        assert avg is not None
        # 3 positive + 2 negative -> small positive overall
        # Not testing exact value, just that it returns a number

    def test_rolling_clv_empty(self, clv):
        assert clv.get_rolling_clv() is None

    def test_get_clv_trend(self, clv, db):
        for i in range(3):
            gid = f"nba_g{i}"
            pid = _seed_pick(db, game_id=gid, odds=-160)
            clv.record_closing_odds(gid, "h2h", -170)
            clv.compute_clv(pid)

        trend = clv.get_clv_trend()
        assert len(trend) == 3
        for entry in trend:
            assert "pick_id" in entry
            assert "clv" in entry
            assert entry["clv"] > 0
