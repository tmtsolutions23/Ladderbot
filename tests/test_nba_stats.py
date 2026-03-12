"""Tests for the NBA stats client."""
import sqlite3
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from ladderbot.data.nba_stats import NBAStatsClient, _current_season
from ladderbot.data.cache import cache_set
from ladderbot.db.database import get_db


@pytest.fixture
def db(tmp_path):
    """Provide an initialized database connection."""
    conn = get_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    """Provide an NBAStatsClient instance."""
    return NBAStatsClient(db_conn=db)


# Sample DataFrames mimicking nba_api responses
SAMPLE_ADVANCED_DF = pd.DataFrame([
    {
        "TEAM_ID": 1610612738,
        "TEAM_NAME": "Boston Celtics",
        "TEAM_ABBREVIATION": "BOS",
        "OFF_RATING": 118.5,
        "DEF_RATING": 108.2,
        "NET_RATING": 10.3,
        "PACE": 99.8,
    },
    {
        "TEAM_ID": 1610612749,
        "TEAM_NAME": "Milwaukee Bucks",
        "TEAM_ABBREVIATION": "MIL",
        "OFF_RATING": 115.1,
        "DEF_RATING": 112.0,
        "NET_RATING": 3.1,
        "PACE": 100.5,
    },
])

SAMPLE_FOUR_FACTORS_DF = pd.DataFrame([
    {
        "TEAM_ID": 1610612738,
        "TEAM_NAME": "Boston Celtics",
        "EFG_PCT": 0.562,
        "FTA_RATE": 0.258,
        "TM_TOV_PCT": 12.8,
        "OREB_PCT": 25.1,
    },
    {
        "TEAM_ID": 1610612749,
        "TEAM_NAME": "Milwaukee Bucks",
        "EFG_PCT": 0.541,
        "FTA_RATE": 0.270,
        "TM_TOV_PCT": 13.5,
        "OREB_PCT": 28.2,
    },
])

SAMPLE_GAME_LOG_DF = pd.DataFrame([
    {
        "Game_ID": "0022500001",
        "GAME_DATE": "MAR 10, 2026",
        "MATCHUP": "BOS vs. MIL",
        "WL": "W",
        "PTS": 112,
    },
    {
        "Game_ID": "0022500002",
        "GAME_DATE": "MAR 08, 2026",
        "MATCHUP": "BOS @ NYK",
        "WL": "L",
        "PTS": 98,
    },
])

SAMPLE_SCOREBOARD_DF = pd.DataFrame([
    {
        "GAME_ID": "0022500100",
        "HOME_TEAM_ID": 1610612738,
        "VISITOR_TEAM_ID": 1610612749,
        "GAME_STATUS_TEXT": "7:00 PM ET",
    },
])


def _mock_endpoint(dataframe):
    """Create a mock nba_api endpoint that returns the given DataFrame."""
    endpoint = MagicMock()
    endpoint.get_data_frames.return_value = [dataframe]
    return endpoint


class TestCurrentSeason:
    @patch("ladderbot.data.nba_stats.datetime")
    def test_october_start(self, mock_dt):
        mock_dt.now.return_value = MagicMock(month=10, year=2025)
        assert _current_season() == "2025-26"

    @patch("ladderbot.data.nba_stats.datetime")
    def test_january(self, mock_dt):
        mock_dt.now.return_value = MagicMock(month=1, year=2026)
        assert _current_season() == "2025-26"

    @patch("ladderbot.data.nba_stats.datetime")
    def test_march(self, mock_dt):
        mock_dt.now.return_value = MagicMock(month=3, year=2026)
        assert _current_season() == "2025-26"

    @patch("ladderbot.data.nba_stats.datetime")
    def test_september(self, mock_dt):
        mock_dt.now.return_value = MagicMock(month=9, year=2026)
        assert _current_season() == "2025-26"


class TestGetTeamAdvancedStats:
    @patch("ladderbot.data.nba_stats.time.sleep")
    @patch("ladderbot.data.nba_stats.LeagueDashTeamStats", create=True)
    def test_returns_dataframe(self, mock_endpoint_cls, mock_sleep, client):
        with patch(
            "ladderbot.data.nba_stats.NBAStatsClient._call_with_retry",
            return_value=_mock_endpoint(SAMPLE_ADVANCED_DF),
        ):
            df = client.get_team_advanced_stats(season="2025-26")
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 2
            assert "OFF_RATING" in df.columns

    @patch("ladderbot.data.nba_stats.time.sleep")
    def test_caches_result(self, mock_sleep, client, db):
        with patch(
            "ladderbot.data.nba_stats.NBAStatsClient._call_with_retry",
            return_value=_mock_endpoint(SAMPLE_ADVANCED_DF),
        ) as mock_call:
            client.get_team_advanced_stats(season="2025-26")
            client.get_team_advanced_stats(season="2025-26")
            # Only called once — second call uses cache
            assert mock_call.call_count == 1

    def test_returns_cached_data(self, client, db):
        cache_set(
            db,
            "nba_team_advanced_2025-26",
            {"data": SAMPLE_ADVANCED_DF.to_dict(orient="records")},
        )
        df = client.get_team_advanced_stats(season="2025-26")
        assert len(df) == 2
        assert df.iloc[0]["TEAM_NAME"] == "Boston Celtics"


class TestGetTeamFourFactors:
    @patch("ladderbot.data.nba_stats.time.sleep")
    def test_returns_dataframe(self, mock_sleep, client):
        with patch(
            "ladderbot.data.nba_stats.NBAStatsClient._call_with_retry",
            return_value=_mock_endpoint(SAMPLE_FOUR_FACTORS_DF),
        ):
            df = client.get_team_four_factors(season="2025-26")
            assert isinstance(df, pd.DataFrame)
            assert "EFG_PCT" in df.columns
            assert len(df) == 2

    def test_returns_cached_data(self, client, db):
        cache_set(
            db,
            "nba_team_four_factors_2025-26",
            {"data": SAMPLE_FOUR_FACTORS_DF.to_dict(orient="records")},
        )
        df = client.get_team_four_factors(season="2025-26")
        assert len(df) == 2


class TestGetTeamGameLogs:
    def test_returns_game_logs(self, client, db):
        cache_set(
            db,
            "nba_game_logs_BOS_20",
            {"data": SAMPLE_GAME_LOG_DF.to_dict(orient="records")},
        )
        df = client.get_team_game_logs("BOS", last_n=20)
        assert len(df) == 2
        assert "PTS" in df.columns

    def test_returns_cached_game_logs(self, client, db):
        cache_set(
            db,
            "nba_game_logs_BOS_20",
            {"data": SAMPLE_GAME_LOG_DF.to_dict(orient="records")},
        )
        df = client.get_team_game_logs("BOS", last_n=20)
        assert len(df) == 2
        assert df.iloc[0]["WL"] == "W"


class TestGetTodaysGames:
    @patch("ladderbot.data.nba_stats.time.sleep")
    def test_returns_games(self, mock_sleep, client):
        with patch(
            "ladderbot.data.nba_stats.NBAStatsClient._call_with_retry",
            return_value=_mock_endpoint(SAMPLE_SCOREBOARD_DF),
        ):
            games = client.get_todays_games()
            assert len(games) == 1
            assert games[0]["game_id"] == "0022500100"
            assert games[0]["home_team_id"] == 1610612738

    @patch("ladderbot.data.nba_stats.datetime")
    def test_returns_cached_games(self, mock_dt, client, db):
        mock_dt.now.return_value.strftime.return_value = "2026-03-11"
        cached_games = [
            {
                "game_id": "0022500100",
                "home_team_id": 1610612738,
                "away_team_id": 1610612749,
                "game_date": "2026-03-11",
                "status": "7:00 PM ET",
            }
        ]
        cache_set(db, "nba_todays_games_2026-03-11", {"games": cached_games})
        games = client.get_todays_games()
        assert len(games) == 1


class TestRateLimiting:
    def test_rate_limit_enforced(self, client):
        """Rate limit should wait if calls are too close together."""
        client._last_call_time = 0.0  # Reset
        with patch("ladderbot.data.nba_stats.time.sleep") as mock_sleep, \
             patch("ladderbot.data.nba_stats.time.time", return_value=100.0):
            client._last_call_time = 99.5  # 0.5s ago
            client._rate_limit()
            # Should sleep for 0.25s (0.75 - 0.5)
            mock_sleep.assert_called_once()
            sleep_time = mock_sleep.call_args[0][0]
            assert 0.2 <= sleep_time <= 0.3


class TestRetryLogic:
    @patch("ladderbot.data.nba_stats.time.sleep")
    @patch("ladderbot.data.nba_stats.time.time", return_value=1000.0)
    def test_retries_on_429(self, mock_time, mock_sleep, client):
        mock_endpoint_cls = MagicMock()
        # First call raises 429, second succeeds
        mock_endpoint_cls.side_effect = [
            Exception("429 Too Many Requests"),
            _mock_endpoint(SAMPLE_ADVANCED_DF),
        ]

        result = client._call_with_retry(mock_endpoint_cls)
        assert result is not None
        assert mock_endpoint_cls.call_count == 2

    @patch("ladderbot.data.nba_stats.time.sleep")
    @patch("ladderbot.data.nba_stats.time.time", return_value=1000.0)
    def test_raises_non_rate_limit_errors(self, mock_time, mock_sleep, client):
        mock_endpoint_cls = MagicMock()
        mock_endpoint_cls.side_effect = ValueError("Something else broke")

        with pytest.raises(ValueError, match="Something else broke"):
            client._call_with_retry(mock_endpoint_cls)
