"""Tests for the NHL stats client."""
import sqlite3
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest
import httpx

from ladderbot.data.nhl_stats import NHLStatsClient, NHLStatsError
from ladderbot.data.cache import cache_set, STATS_TTL
from ladderbot.db.database import get_db


@pytest.fixture
def db(tmp_path):
    """Provide an initialized database connection."""
    conn = get_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    """Provide an NHLStatsClient instance."""
    return NHLStatsClient(db_conn=db)


# -- Sample API responses --

SAMPLE_SCHEDULE_RESPONSE = {
    "gameWeek": [
        {
            "date": "2026-03-11",
            "games": [
                {
                    "id": 2025020901,
                    "homeTeam": {"abbrev": "BOS", "name": {"default": "Bruins"}},
                    "awayTeam": {"abbrev": "NYR", "name": {"default": "Rangers"}},
                    "startTimeUTC": "2026-03-11T23:00:00Z",
                    "gameState": "FUT",
                    "venue": {"default": "TD Garden"},
                },
                {
                    "id": 2025020902,
                    "homeTeam": {"abbrev": "COL", "name": {"default": "Avalanche"}},
                    "awayTeam": {"abbrev": "DAL", "name": {"default": "Stars"}},
                    "startTimeUTC": "2026-03-12T01:00:00Z",
                    "gameState": "FUT",
                    "venue": {"default": "Ball Arena"},
                },
            ],
        }
    ]
}

SAMPLE_STANDINGS_RESPONSE = {
    "standings": [
        {
            "teamAbbrev": {"default": "WPG"},
            "teamName": {"default": "Jets"},
            "wins": 45,
            "losses": 18,
            "otLosses": 5,
            "points": 95,
            "gamesPlayed": 68,
            "goalDifferential": 52,
            "goalFor": 230,
            "goalAgainst": 178,
        },
        {
            "teamAbbrev": {"default": "CAR"},
            "teamName": {"default": "Hurricanes"},
            "wins": 42,
            "losses": 20,
            "otLosses": 6,
            "points": 90,
            "gamesPlayed": 68,
            "goalDifferential": 38,
            "goalFor": 215,
            "goalAgainst": 177,
        },
    ]
}

SAMPLE_GAME_RESULT_RESPONSE = {
    "homeTeam": {"abbrev": "BOS", "score": 4},
    "awayTeam": {"abbrev": "NYR", "score": 2},
    "gameState": "FINAL",
    "periodDescriptor": {"number": 3},
}

SAMPLE_TEAM_CSV = """team,situation,xGoalsFor,xGoalsAgainst,corsiPercentage,fenwickPercentage
BOS,5on5,2.8,2.1,52.5,53.1
NYR,5on5,2.6,2.4,50.2,49.8
COL,5on5,3.1,2.5,54.0,54.5
"""

SAMPLE_GOALIE_CSV = """name,team,situation,gsax,highDangerSavePercentage,evenStrengthSavePercentage,games_played
Jeremy Swayman,BOS,all,12.5,0.875,0.928,45
Igor Shesterkin,NYR,all,18.2,0.890,0.932,50
"""


def _mock_response(data, status_code=200, text=""):
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = data
    response.text = text
    response.raise_for_status.return_value = None
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=response,
        )
    return response


class TestGetSchedule:
    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_returns_games(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_SCHEDULE_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        games = client.get_schedule("2026-03-11")
        assert len(games) == 2
        assert games[0]["home_team"] == "BOS"
        assert games[0]["away_team"] == "NYR"
        assert games[1]["home_team"] == "COL"

    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_caches_schedule(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_SCHEDULE_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        client.get_schedule("2026-03-11")
        client.get_schedule("2026-03-11")
        assert mock_client_cls.call_count == 1

    def test_returns_cached_schedule(self, client, db):
        cached_games = [
            {"id": "123", "home_team": "BOS", "away_team": "NYR",
             "start_time": "2026-03-11T23:00:00Z", "status": "FUT", "venue": "TD Garden"}
        ]
        cache_set(db, "nhl_schedule_2026-03-11", {"games": cached_games})
        games = client.get_schedule("2026-03-11")
        assert len(games) == 1
        assert games[0]["home_team"] == "BOS"


class TestGetStandings:
    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_returns_standings(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_STANDINGS_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        standings = client.get_standings()
        assert len(standings) == 2
        assert standings[0]["team"] == "WPG"
        assert standings[0]["wins"] == 45
        assert standings[0]["points"] == 95
        assert standings[1]["team"] == "CAR"

    def test_returns_cached_standings(self, client, db):
        cached = [{"team": "WPG", "wins": 45, "points": 95}]
        cache_set(db, "nhl_standings", {"standings": cached})
        standings = client.get_standings()
        assert standings[0]["team"] == "WPG"


class TestGetTeamXgStats:
    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_returns_dataframe(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response({}, text=SAMPLE_TEAM_CSV)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        df = client.get_team_xg_stats()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "xGoalsFor" in df.columns

    def test_returns_cached_xg_stats(self, client, db):
        data = [
            {"team": "BOS", "xGoalsFor": 2.8, "xGoalsAgainst": 2.1},
            {"team": "NYR", "xGoalsFor": 2.6, "xGoalsAgainst": 2.4},
        ]
        cache_set(db, "nhl_team_xg_stats", {"data": data})
        df = client.get_team_xg_stats()
        assert len(df) == 2
        assert df.iloc[0]["team"] == "BOS"


class TestGetGoalieStats:
    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_returns_dataframe(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response({}, text=SAMPLE_GOALIE_CSV)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        df = client.get_goalie_stats()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "gsax" in df.columns

    def test_returns_cached_goalie_stats(self, client, db):
        data = [
            {"name": "Jeremy Swayman", "team": "BOS", "gsax": 12.5},
            {"name": "Igor Shesterkin", "team": "NYR", "gsax": 18.2},
        ]
        cache_set(db, "nhl_goalie_stats", {"data": data})
        df = client.get_goalie_stats()
        assert len(df) == 2


class TestGetGameResult:
    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_returns_result(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_GAME_RESULT_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        result = client.get_game_result("2025020901")
        assert result["game_id"] == "2025020901"
        assert result["home_team"] == "BOS"
        assert result["home_score"] == 4
        assert result["away_score"] == 2
        assert result["status"] == "FINAL"

    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_caches_final_result(self, mock_client_cls, client, db):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_GAME_RESULT_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        client.get_game_result("2025020901")
        # Should be cached now
        cached = cache_set  # just verifying it was set
        result2 = client.get_game_result("2025020901")
        assert result2["home_score"] == 4
        # Only one HTTP call needed
        assert mock_client_cls.call_count == 1

    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_does_not_cache_live_game(self, mock_client_cls, client, db):
        live_response = {
            "homeTeam": {"abbrev": "BOS", "score": 2},
            "awayTeam": {"abbrev": "NYR", "score": 1},
            "gameState": "LIVE",
            "periodDescriptor": {"number": 2},
        }
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(live_response)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        result = client.get_game_result("2025020901")
        assert result["status"] == "LIVE"
        # Should not be cached
        from ladderbot.data.cache import cache_get
        cached = cache_get(db, "nhl_game_result_2025020901")
        assert cached is None


class TestRetryLogic:
    @patch("ladderbot.data.nhl_stats.time.sleep")
    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_retries_on_failure(self, mock_client_cls, mock_sleep, client):
        mock_http = MagicMock()
        fail = _mock_response({}, status_code=500)
        success = _mock_response(SAMPLE_STANDINGS_RESPONSE)
        mock_http.get.side_effect = [fail, success]
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        standings = client.get_standings()
        assert len(standings) == 2

    @patch("ladderbot.data.nhl_stats.time.sleep")
    @patch("ladderbot.data.nhl_stats.httpx.Client")
    def test_raises_after_max_retries(self, mock_client_cls, mock_sleep, client):
        mock_http = MagicMock()
        fail = _mock_response({}, status_code=500)
        mock_http.get.return_value = fail
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        with pytest.raises(NHLStatsError, match="failed after 3 retries"):
            client.get_standings()


class TestNHLStatsClientInit:
    def test_stores_db_conn(self, db):
        client = NHLStatsClient(db_conn=db)
        assert client.db_conn is db
