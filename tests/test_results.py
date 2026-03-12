"""Tests for results resolver."""
import pytest

from ladderbot.db.database import (
    get_db, insert_game, insert_pick, insert_odds_snapshot,
)
from ladderbot.tracking.results import ResultsResolver


@pytest.fixture
def db(tmp_path):
    conn = get_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


@pytest.fixture
def resolver(db):
    return ResultsResolver(db)


class TestCheckGameResults:
    def test_returns_final_games(self, resolver, db):
        insert_game(db, "nba_g1", "nba", "BOS", "MIL", "2026-03-11",
                     home_score=112, away_score=105, status="final")
        results = resolver.check_game_results("2026-03-11")
        assert len(results) == 1
        assert results[0]["home_score"] == 112

    def test_empty_date(self, resolver):
        results = resolver.check_game_results("2099-01-01")
        assert results == []


class TestResolvePicksMoneyline:
    def test_home_win(self, resolver, db):
        insert_game(db, "nba_g1", "nba", "BOS", "MIL", "2026-03-11",
                     home_score=112, away_score=105, status="final")
        insert_pick(db, "nba_g1", "h2h", "BOS", -160)

        results = resolver.check_game_results("2026-03-11")
        resolved = resolver.resolve_picks(results)
        assert len(resolved) == 1
        assert resolved[0]["result"] == "won"

    def test_home_loss(self, resolver, db):
        insert_game(db, "nba_g1", "nba", "BOS", "MIL", "2026-03-11",
                     home_score=100, away_score=110, status="final")
        insert_pick(db, "nba_g1", "h2h", "BOS", -160)

        results = resolver.check_game_results("2026-03-11")
        resolved = resolver.resolve_picks(results)
        assert len(resolved) == 1
        assert resolved[0]["result"] == "lost"

    def test_away_win(self, resolver, db):
        insert_game(db, "nba_g1", "nba", "BOS", "MIL", "2026-03-11",
                     home_score=100, away_score=110, status="final")
        insert_pick(db, "nba_g1", "h2h", "MIL", 140)

        results = resolver.check_game_results("2026-03-11")
        resolved = resolver.resolve_picks(results)
        assert len(resolved) == 1
        assert resolved[0]["result"] == "won"

    def test_skips_non_final(self, resolver, db):
        insert_game(db, "nba_g1", "nba", "BOS", "MIL", "2026-03-11",
                     status="scheduled")
        insert_pick(db, "nba_g1", "h2h", "BOS", -160)

        results = resolver.check_game_results("2026-03-11")
        resolved = resolver.resolve_picks(results)
        assert len(resolved) == 0


class TestResolvePicksTotals:
    def test_over_win(self, resolver, db):
        insert_game(db, "nhl_g1", "nhl", "NYR", "BOS", "2026-03-11",
                     home_score=4, away_score=3, status="final")
        insert_pick(db, "nhl_g1", "totals", "Over", 120)
        # Insert odds snapshot with point (the total line)
        insert_odds_snapshot(db, "nhl_g1", "draftkings", "totals", "Over", 120, point=5.5)

        results = resolver.check_game_results("2026-03-11")
        resolved = resolver.resolve_picks(results)
        assert len(resolved) == 1
        assert resolved[0]["result"] == "won"  # 4+3=7 > 5.5

    def test_under_win(self, resolver, db):
        insert_game(db, "nhl_g1", "nhl", "NYR", "BOS", "2026-03-11",
                     home_score=2, away_score=1, status="final")
        insert_pick(db, "nhl_g1", "totals", "Under", -110)
        insert_odds_snapshot(db, "nhl_g1", "draftkings", "totals", "Under", -110, point=5.5)

        results = resolver.check_game_results("2026-03-11")
        resolved = resolver.resolve_picks(results)
        assert len(resolved) == 1
        assert resolved[0]["result"] == "won"  # 2+1=3 < 5.5

    def test_over_loss(self, resolver, db):
        insert_game(db, "nhl_g1", "nhl", "NYR", "BOS", "2026-03-11",
                     home_score=2, away_score=1, status="final")
        insert_pick(db, "nhl_g1", "totals", "Over", 120)
        insert_odds_snapshot(db, "nhl_g1", "draftkings", "totals", "Over", 120, point=5.5)

        results = resolver.check_game_results("2026-03-11")
        resolved = resolver.resolve_picks(results)
        assert len(resolved) == 1
        assert resolved[0]["result"] == "lost"  # 2+1=3 < 5.5

    def test_totals_push(self, resolver, db):
        insert_game(db, "nhl_g1", "nhl", "NYR", "BOS", "2026-03-11",
                     home_score=3, away_score=3, status="final")
        insert_pick(db, "nhl_g1", "totals", "Over", 120)
        insert_odds_snapshot(db, "nhl_g1", "draftkings", "totals", "Over", 120, point=6.0)

        results = resolver.check_game_results("2026-03-11")
        resolved = resolver.resolve_picks(results)
        assert len(resolved) == 1
        assert resolved[0]["result"] == "push"  # 3+3=6 == 6.0

    def test_multiple_picks_resolved(self, resolver, db):
        insert_game(db, "nba_g1", "nba", "BOS", "MIL", "2026-03-11",
                     home_score=112, away_score=105, status="final")
        insert_game(db, "nhl_g1", "nhl", "NYR", "BOS", "2026-03-11",
                     home_score=4, away_score=3, status="final")
        insert_pick(db, "nba_g1", "h2h", "BOS", -160)
        insert_pick(db, "nhl_g1", "h2h", "NYR", -130)

        results = resolver.check_game_results("2026-03-11")
        resolved = resolver.resolve_picks(results)
        assert len(resolved) == 2
        assert all(r["result"] == "won" for r in resolved)
