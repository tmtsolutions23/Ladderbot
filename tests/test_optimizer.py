"""Tests for parlay optimizer."""
import pytest

from ladderbot.parlay.optimizer import find_best_parlays
from ladderbot.config import DEFAULT_CONFIG


def _make_bet(game_id, odds, model_prob, edge, sport="nba", market="h2h", outcome="BOS"):
    return {
        "game_id": game_id,
        "market": market,
        "outcome": outcome,
        "odds": odds,
        "model_prob": model_prob,
        "edge": edge,
        "sport": sport,
    }


class TestFindBestParlays:
    def test_basic_two_leg_parlay(self):
        """Two +EV bets from different games produce one valid parlay."""
        bets = [
            _make_bet("g1", -160, 0.642, 0.027),
            _make_bet("g2", 120, 0.481, 0.024, sport="nhl", market="totals", outcome="Over"),
        ]
        result = find_best_parlays(bets, DEFAULT_CONFIG)
        assert len(result) == 1
        p = result[0]
        assert p["leg1"]["game_id"] != p["leg2"]["game_id"]
        assert p["parlay_american"] >= 150
        assert p["parlay_american"] <= 300

    def test_same_game_excluded(self):
        """Bets from the same game should not be combined."""
        bets = [
            _make_bet("g1", -160, 0.642, 0.027, outcome="BOS"),
            _make_bet("g1", 120, 0.481, 0.024, market="totals", outcome="Over"),
        ]
        result = find_best_parlays(bets, DEFAULT_CONFIG)
        assert len(result) == 0

    def test_below_min_edge_filtered(self):
        """Legs below min_edge_per_leg should be filtered out."""
        bets = [
            _make_bet("g1", -160, 0.642, 0.027),
            _make_bet("g2", 120, 0.46, 0.005),  # Below 2% edge
        ]
        result = find_best_parlays(bets, DEFAULT_CONFIG)
        assert len(result) == 0

    def test_odds_out_of_range_filtered(self):
        """Parlays with combined odds outside +150/+300 are filtered."""
        # Two heavy favorites -> combined odds too low
        bets = [
            _make_bet("g1", -300, 0.80, 0.05),
            _make_bet("g2", -250, 0.75, 0.03),
        ]
        result = find_best_parlays(bets, DEFAULT_CONFIG)
        # -300 (1.333) * -250 (1.40) = 1.867 -> -115, below +150
        assert len(result) == 0

    def test_returns_top_3(self):
        """When more than 3 valid parlays exist, return only top 3."""
        bets = [
            _make_bet("g1", -160, 0.642, 0.027, outcome="BOS"),
            _make_bet("g2", 120, 0.481, 0.024, outcome="Over", market="totals"),
            _make_bet("g3", -150, 0.63, 0.03, outcome="NYK"),
            _make_bet("g4", 110, 0.50, 0.025, outcome="Under", market="totals"),
        ]
        result = find_best_parlays(bets, DEFAULT_CONFIG)
        assert len(result) <= 3

    def test_sorted_by_parlay_edge(self):
        """Results should be sorted by parlay_edge descending."""
        bets = [
            _make_bet("g1", -160, 0.642, 0.027, outcome="BOS"),
            _make_bet("g2", 120, 0.481, 0.024, outcome="Over", market="totals"),
            _make_bet("g3", -150, 0.65, 0.04, outcome="NYK"),
        ]
        result = find_best_parlays(bets, DEFAULT_CONFIG)
        if len(result) > 1:
            for i in range(len(result) - 1):
                assert result[i]["parlay_edge"] >= result[i + 1]["parlay_edge"]

    def test_empty_input(self):
        """Empty bet list returns empty result."""
        assert find_best_parlays([], DEFAULT_CONFIG) == []

    def test_single_bet(self):
        """Single bet cannot form a parlay."""
        bets = [_make_bet("g1", -160, 0.642, 0.027)]
        assert find_best_parlays(bets, DEFAULT_CONFIG) == []

    def test_cross_sport_allowed(self):
        """NBA + NHL cross-sport parlays are allowed."""
        bets = [
            _make_bet("g1", -160, 0.642, 0.027, sport="nba"),
            _make_bet("g2", 120, 0.481, 0.024, sport="nhl"),
        ]
        result = find_best_parlays(bets, DEFAULT_CONFIG)
        assert len(result) == 1

    def test_parlay_edge_calculation(self):
        """Verify parlay_edge = (prob1 * prob2 * decimal) - 1."""
        bets = [
            _make_bet("g1", -160, 0.642, 0.03),
            _make_bet("g2", 120, 0.481, 0.03),
        ]
        result = find_best_parlays(bets, DEFAULT_CONFIG)
        if result:
            p = result[0]
            expected_edge = (0.642 * 0.481 * p["parlay_decimal"]) - 1
            assert p["parlay_edge"] == pytest.approx(expected_edge, rel=1e-6)

    def test_custom_config_thresholds(self):
        """Custom config thresholds should be respected."""
        config = {
            "parlay": {
                "target_odds_min": 200,
                "target_odds_max": 250,
                "min_edge_per_leg": 0.05,
            }
        }
        bets = [
            _make_bet("g1", -160, 0.642, 0.06),
            _make_bet("g2", 120, 0.481, 0.06),
        ]
        result = find_best_parlays(bets, config)
        # -160 * +120 = ~+258 which is in 200-250 range? Let's check
        # 1.625 * 2.2 = 3.575 -> +258 -> above 250 -> filtered
        assert len(result) == 0
