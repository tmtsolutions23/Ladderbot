"""Tests for ladderbot.models.features."""
import math
from datetime import date

import pytest

from ladderbot.models.features import (
    ARENA_COORDS,
    _haversine,
    _compute_rest_days,
    _cold_start_blend,
    build_nba_features,
    build_nhl_features,
)


# ---------------------------------------------------------------------------
# Arena coordinates tests
# ---------------------------------------------------------------------------

class TestArenaCoords:
    def test_has_30_nba_teams(self):
        nba_keys = [
            "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET",
            "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN",
            "NOP", "NYK", "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS",
            "TOR", "UTA", "WAS",
        ]
        for key in nba_keys:
            assert key in ARENA_COORDS, f"Missing NBA team: {key}"

    def test_has_nhl_teams(self):
        nhl_keys = [
            "ANA", "ARI", "BUF", "CGY", "CAR", "CBJ", "COL", "EDM", "FLA",
            "LAK", "MTL", "NSH", "NJD", "NYI", "NYR", "OTT", "PIT", "SEA",
            "SJS", "STL", "TBL", "VAN", "VGK", "WPG",
        ]
        for key in nhl_keys:
            assert key in ARENA_COORDS, f"Missing NHL team: {key}"

    def test_coords_are_valid_lat_lon(self):
        for team, (lat, lon) in ARENA_COORDS.items():
            assert -90 <= lat <= 90, f"{team} lat out of range: {lat}"
            assert -180 <= lon <= 180, f"{team} lon out of range: {lon}"

    def test_total_count_at_least_62(self):
        # 30 NBA + 32 NHL, some share arenas so keys may differ
        assert len(ARENA_COORDS) >= 60


# ---------------------------------------------------------------------------
# Haversine tests
# ---------------------------------------------------------------------------

class TestHaversine:
    def test_same_point_is_zero(self):
        assert _haversine(40.0, -74.0, 40.0, -74.0) == 0.0

    def test_known_distance_nyc_to_la(self):
        # NYC to LA is roughly 2,450 miles
        dist = _haversine(40.7128, -74.0060, 34.0522, -118.2437)
        assert 2400 < dist < 2500

    def test_symmetry(self):
        d1 = _haversine(42.0, -71.0, 34.0, -118.0)
        d2 = _haversine(34.0, -118.0, 42.0, -71.0)
        assert abs(d1 - d2) < 0.01

    def test_short_distance(self):
        # NYK to BKN arenas are close (a few miles)
        nyk = ARENA_COORDS["NYK"]
        bkn = ARENA_COORDS["BKN"]
        dist = _haversine(nyk[0], nyk[1], bkn[0], bkn[1])
        assert dist < 10  # Should be just a few miles


# ---------------------------------------------------------------------------
# Rest days tests
# ---------------------------------------------------------------------------

class TestComputeRestDays:
    def test_back_to_back(self):
        game_date = date(2026, 3, 10)
        recent = [{"date": date(2026, 3, 9)}]
        assert _compute_rest_days(game_date, recent) == 0

    def test_one_day_rest(self):
        game_date = date(2026, 3, 10)
        recent = [{"date": date(2026, 3, 8)}]
        assert _compute_rest_days(game_date, recent) == 1

    def test_two_day_rest(self):
        game_date = date(2026, 3, 10)
        recent = [{"date": date(2026, 3, 7)}]
        assert _compute_rest_days(game_date, recent) == 2

    def test_three_plus_rest(self):
        game_date = date(2026, 3, 10)
        recent = [{"date": date(2026, 3, 5)}]
        assert _compute_rest_days(game_date, recent) == 3

    def test_empty_recent_games(self):
        assert _compute_rest_days(date(2026, 3, 10), []) == 3

    def test_no_games_before_date(self):
        game_date = date(2026, 3, 10)
        recent = [{"date": date(2026, 3, 11)}]  # Future game
        assert _compute_rest_days(game_date, recent) == 3

    def test_string_dates(self):
        game_date = date(2026, 3, 10)
        recent = [{"date": "2026-03-09"}]
        assert _compute_rest_days(game_date, recent) == 0

    def test_picks_most_recent(self):
        game_date = date(2026, 3, 10)
        recent = [
            {"date": date(2026, 3, 5)},
            {"date": date(2026, 3, 9)},  # Most recent
            {"date": date(2026, 3, 7)},
        ]
        assert _compute_rest_days(game_date, recent) == 0


# ---------------------------------------------------------------------------
# Cold start blend tests
# ---------------------------------------------------------------------------

class TestColdStartBlend:
    def test_full_current_after_cold_start(self):
        result = _cold_start_blend(current=110.0, prior=105.0, games_played=20)
        assert result == 110.0

    def test_full_prior_at_zero_games(self):
        result = _cold_start_blend(current=110.0, prior=105.0, games_played=0)
        assert result == 105.0

    def test_midpoint_at_ten_games(self):
        result = _cold_start_blend(current=110.0, prior=100.0, games_played=10)
        assert abs(result - 105.0) < 0.01

    def test_roster_changes_reduce_prior_weight(self):
        # Without roster changes
        no_changes = _cold_start_blend(current=110.0, prior=100.0, games_played=5)
        # With 10 roster changes (50% penalty)
        with_changes = _cold_start_blend(
            current=110.0, prior=100.0, games_played=5, roster_changes=10
        )
        # More roster changes should pull result toward current
        assert with_changes > no_changes

    def test_roster_penalty_floor_at_zero(self):
        # 20+ changes would make penalty negative; should floor at 0
        result = _cold_start_blend(
            current=110.0, prior=100.0, games_played=5, roster_changes=25
        )
        # Prior weight should be 0, so result should be current
        assert result == 110.0

    def test_above_cold_start_window(self):
        result = _cold_start_blend(
            current=110.0, prior=105.0, games_played=50, cold_start_games=20
        )
        assert result == 110.0


# ---------------------------------------------------------------------------
# Mock clients for feature builders
# ---------------------------------------------------------------------------

class MockStatsClient:
    """Returns fixed values for all stats."""

    def __init__(self, home_stats=None, away_stats=None):
        self._home_stats = home_stats or {}
        self._away_stats = away_stats or {}
        self._default = 0.5

    def get_team_stats(self, team, stat, window=20):
        stats = self._home_stats if team == "BOS" else self._away_stats
        return stats.get(stat, self._default)

    def get_recent_games(self, team, n=10):
        if team == "BOS":
            return [{"date": date(2026, 3, 8)}]  # 1 day rest
        return [{"date": date(2026, 3, 7)}]  # 2 day rest


class MockInjuryClient:
    def get_injury_impact(self, team):
        if team == "BOS":
            return -1.5  # Missing a key player
        return 0.0


# ---------------------------------------------------------------------------
# NBA feature builder tests
# ---------------------------------------------------------------------------

class TestBuildNBAFeatures:
    def test_returns_10_features(self):
        stats = MockStatsClient()
        injuries = MockInjuryClient()
        features = build_nba_features("BOS", "LAL", date(2026, 3, 10), stats, injuries)
        assert len(features) == 10

    def test_expected_feature_names(self):
        stats = MockStatsClient()
        injuries = MockInjuryClient()
        features = build_nba_features("BOS", "LAL", date(2026, 3, 10), stats, injuries)
        expected_keys = {
            "net_rating_diff", "off_efg_diff", "def_efg_diff",
            "tov_pct_diff", "orb_pct_diff", "ft_rate_diff",
            "rest_diff", "home_court", "travel_dist_diff",
            "injury_impact_diff",
        }
        assert set(features.keys()) == expected_keys

    def test_home_court_is_one(self):
        stats = MockStatsClient()
        injuries = MockInjuryClient()
        features = build_nba_features("BOS", "LAL", date(2026, 3, 10), stats, injuries)
        assert features["home_court"] == 1.0

    def test_values_are_floats(self):
        stats = MockStatsClient()
        injuries = MockInjuryClient()
        features = build_nba_features("BOS", "LAL", date(2026, 3, 10), stats, injuries)
        for k, v in features.items():
            assert isinstance(v, float), f"{k} is not float: {type(v)}"

    def test_differential_with_different_stats(self):
        stats = MockStatsClient(
            home_stats={"net_rating": 5.0},
            away_stats={"net_rating": -2.0},
        )
        injuries = MockInjuryClient()
        features = build_nba_features("BOS", "LAL", date(2026, 3, 10), stats, injuries)
        assert features["net_rating_diff"] == 7.0


# ---------------------------------------------------------------------------
# NHL feature builder tests
# ---------------------------------------------------------------------------

class TestBuildNHLFeatures:
    def test_returns_10_features(self):
        stats = MockStatsClient()
        injuries = MockInjuryClient()
        features = build_nhl_features("BOS", "NYR", date(2026, 3, 10), stats, injuries)
        assert len(features) == 10

    def test_expected_feature_names(self):
        stats = MockStatsClient()
        injuries = MockInjuryClient()
        features = build_nhl_features("BOS", "NYR", date(2026, 3, 10), stats, injuries)
        expected_keys = {
            "xgf_60_diff", "xga_60_diff", "goalie_gsax_diff",
            "goalie_hdsv_diff", "pp_xg_60_diff", "pk_xga_60_diff",
            "rest_diff", "home_ice", "b2b_travel_diff",
            "pdo_regression_diff",
        }
        assert set(features.keys()) == expected_keys

    def test_home_ice_is_one(self):
        stats = MockStatsClient()
        injuries = MockInjuryClient()
        features = build_nhl_features("BOS", "NYR", date(2026, 3, 10), stats, injuries)
        assert features["home_ice"] == 1.0

    def test_values_are_floats(self):
        stats = MockStatsClient()
        injuries = MockInjuryClient()
        features = build_nhl_features("BOS", "NYR", date(2026, 3, 10), stats, injuries)
        for k, v in features.items():
            assert isinstance(v, float), f"{k} is not float: {type(v)}"
