"""Tests for ladderbot.models.value."""
import pytest

from ladderbot.models.value import find_ev_bets, recalculate_edge_with_fd_odds


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def _make_games():
    return [
        {"game_id": "g1", "sport": "nba", "home": "BOS", "away": "LAL"},
        {"game_id": "g2", "sport": "nhl", "home": "NYR", "away": "PIT"},
    ]


def _make_predictions():
    return {
        "g1": {"home_win_prob": 0.65, "predicted_total": 220.0},
        "g2": {"home_win_prob": 0.55, "predicted_total": 6.0},
    }


def _make_odds():
    return {
        "g1": {
            "home_ml": -150,  # implied 60%, edge = 5%
            "away_ml": 130,   # implied 43.5%, away prob = 35%
            "total_line": 215.0,
            "over_odds": -110,
            "under_odds": -110,
        },
        "g2": {
            "home_ml": -120,  # implied 54.5%, edge = 0.5% (below threshold)
            "away_ml": 100,   # implied 50%, away prob = 45%
            "total_line": 5.5,
            "over_odds": -105,
            "under_odds": -115,
        },
    }


# ---------------------------------------------------------------------------
# find_ev_bets tests
# ---------------------------------------------------------------------------

class TestFindEvBets:
    def test_finds_positive_ev_bets(self):
        bets = find_ev_bets(_make_games(), _make_predictions(), _make_odds())
        assert len(bets) > 0
        # All returned bets should have positive edge
        for bet in bets:
            assert bet["edge"] > 0

    def test_filters_by_threshold(self):
        config = {"min_edge_per_leg": 0.04}
        bets = find_ev_bets(
            _make_games(), _make_predictions(), _make_odds(), config
        )
        for bet in bets:
            assert bet["edge"] >= 0.04

    def test_sorted_by_edge_descending(self):
        bets = find_ev_bets(_make_games(), _make_predictions(), _make_odds())
        if len(bets) > 1:
            for i in range(len(bets) - 1):
                assert bets[i]["edge"] >= bets[i + 1]["edge"]

    def test_bet_has_required_keys(self):
        bets = find_ev_bets(_make_games(), _make_predictions(), _make_odds())
        required = {
            "game_id", "sport", "market", "outcome",
            "model_prob", "book_odds", "book_implied_prob",
            "edge", "confidence", "decimal_odds",
        }
        for bet in bets:
            assert required.issubset(set(bet.keys())), (
                f"Missing keys: {required - set(bet.keys())}"
            )

    def test_handles_totals(self):
        bets = find_ev_bets(_make_games(), _make_predictions(), _make_odds())
        totals_bets = [b for b in bets if b["market"] == "totals"]
        # Should have found at least one totals bet if edge exists
        # Even if none qualifies, the function should not crash
        for tb in totals_bets:
            assert "total_line" in tb
            assert "predicted_total" in tb

    def test_respects_min_confidence(self):
        """Model prob must be >= min_confidence."""
        config = {"min_confidence": 0.60}
        bets = find_ev_bets(
            _make_games(), _make_predictions(), _make_odds(), config
        )
        for bet in bets:
            assert bet["model_prob"] >= 0.60

    def test_respects_max_confidence(self):
        """Model prob must be <= max_confidence."""
        config = {"max_confidence": 0.50}
        bets = find_ev_bets(
            _make_games(), _make_predictions(), _make_odds(), config
        )
        for bet in bets:
            assert bet["model_prob"] <= 0.50

    def test_cold_start_widens_threshold(self):
        # With cold_start, min_edge should be 3% (default cold_start threshold)
        config = {"cold_start": True}
        bets_cold = find_ev_bets(
            _make_games(), _make_predictions(), _make_odds(), config
        )
        for bet in bets_cold:
            assert bet["edge"] >= 0.03

    def test_empty_games(self):
        bets = find_ev_bets([], _make_predictions(), _make_odds())
        assert bets == []

    def test_missing_predictions(self):
        bets = find_ev_bets(_make_games(), {}, _make_odds())
        assert bets == []

    def test_missing_odds(self):
        bets = find_ev_bets(_make_games(), _make_predictions(), {})
        assert bets == []


# ---------------------------------------------------------------------------
# recalculate_edge_with_fd_odds tests
# ---------------------------------------------------------------------------

class TestRecalculateEdge:
    def test_basic_recalculation(self):
        pick = {
            "model_prob": 0.65,
            "book_odds": -150,
            "edge": 0.05,
        }
        result = recalculate_edge_with_fd_odds(pick, -140)
        assert "fd_edge" in result
        assert "still_plus_ev" in result
        assert "original_edge" in result
        assert result["original_edge"] == 0.05

    def test_worse_odds_reduces_edge(self):
        pick = {
            "model_prob": 0.65,
            "book_odds": -150,
            "edge": 0.05,
        }
        result = recalculate_edge_with_fd_odds(pick, -200)
        assert result["fd_edge"] < result["original_edge"]

    def test_better_odds_increases_edge(self):
        pick = {
            "model_prob": 0.65,
            "book_odds": -150,
            "edge": 0.05,
        }
        result = recalculate_edge_with_fd_odds(pick, -130)
        assert result["fd_edge"] > result["original_edge"]

    def test_still_plus_ev_flag(self):
        pick = {
            "model_prob": 0.55,
            "book_odds": -110,
            "edge": 0.025,
        }
        # Much worse odds should kill the edge
        result = recalculate_edge_with_fd_odds(pick, -200)
        assert result["still_plus_ev"] is False

    def test_fd_odds_preserved(self):
        pick = {
            "model_prob": 0.65,
            "book_odds": -150,
            "edge": 0.05,
        }
        result = recalculate_edge_with_fd_odds(pick, -155)
        assert result["fd_odds"] == -155
        assert result["original_odds"] == -150
