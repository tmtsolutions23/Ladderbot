"""Tests for The Odds API client."""
import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest
import httpx

from ladderbot.data.odds import OddsClient, OddsClientError
from ladderbot.data.cache import cache_get, cache_set, ODDS_TTL
from ladderbot.db.database import get_db


# Sample API response mimicking The Odds API format
SAMPLE_ODDS_RESPONSE = [
    {
        "id": "game_001",
        "sport_key": "basketball_nba",
        "home_team": "Boston Celtics",
        "away_team": "Milwaukee Bucks",
        "commence_time": "2026-03-11T23:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Celtics", "price": -160},
                            {"name": "Milwaukee Bucks", "price": 135},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 224.5},
                            {"name": "Under", "price": -110, "point": 224.5},
                        ],
                    },
                ],
            }
        ],
    },
    {
        "id": "game_002",
        "sport_key": "basketball_nba",
        "home_team": "Denver Nuggets",
        "away_team": "Phoenix Suns",
        "commence_time": "2026-03-12T01:00:00Z",
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Denver Nuggets", "price": -180},
                            {"name": "Phoenix Suns", "price": 155},
                        ],
                    },
                ],
            }
        ],
    },
]


@pytest.fixture
def db(tmp_path):
    """Provide an initialized database connection."""
    conn = get_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    """Provide an OddsClient instance."""
    return OddsClient(api_key="test-key-12345", db_conn=db)


def _mock_response(data, status_code=200):
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = data
    response.raise_for_status.return_value = None
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=response,
        )
    return response


class TestGetUpcomingGames:
    @patch("ladderbot.data.odds.httpx.Client")
    def test_returns_games(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_ODDS_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        games = client.get_upcoming_games("basketball_nba")
        assert len(games) == 2
        assert games[0]["id"] == "game_001"
        assert games[0]["home_team"] == "Boston Celtics"
        assert games[1]["away_team"] == "Phoenix Suns"

    @patch("ladderbot.data.odds.httpx.Client")
    def test_caches_response(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_ODDS_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        # First call hits API
        games1 = client.get_upcoming_games("basketball_nba")
        # Second call should use cache (no new API call)
        games2 = client.get_upcoming_games("basketball_nba")

        assert games1 == games2
        # httpx.Client should only be instantiated once
        assert mock_client_cls.call_count == 1


class TestGetOdds:
    @patch("ladderbot.data.odds.httpx.Client")
    def test_returns_full_odds_data(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_ODDS_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        events = client.get_odds("basketball_nba")
        assert len(events) == 2
        # Full event data including bookmakers
        assert "bookmakers" in events[0]
        assert events[0]["bookmakers"][0]["key"] == "draftkings"

    @patch("ladderbot.data.odds.httpx.Client")
    def test_stores_snapshots_in_db(self, mock_client_cls, client, db):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_ODDS_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        client.get_odds("basketball_nba")

        # Check games were inserted
        games = db.execute("SELECT * FROM games").fetchall()
        assert len(games) == 2

        # Check odds snapshots were inserted
        snapshots = db.execute("SELECT * FROM odds_snapshots").fetchall()
        # game_001 has 4 outcomes (2 h2h + 2 totals), game_002 has 2 outcomes
        assert len(snapshots) == 6

    @patch("ladderbot.data.odds.httpx.Client")
    def test_caches_odds_response(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_ODDS_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        client.get_odds("basketball_nba", markets="h2h,totals")
        client.get_odds("basketball_nba", markets="h2h,totals")

        # Only one API call
        assert mock_client_cls.call_count == 1

    @patch("ladderbot.data.odds.httpx.Client")
    def test_different_markets_cached_separately(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_ODDS_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        client.get_odds("basketball_nba", markets="h2h")
        client.get_odds("basketball_nba", markets="totals")

        # Two different cache keys, so two API calls
        assert mock_client_cls.call_count == 2


class TestRetryLogic:
    @patch("ladderbot.data.odds.time.sleep")
    @patch("ladderbot.data.odds.httpx.Client")
    def test_retries_on_http_error(self, mock_client_cls, mock_sleep, client):
        mock_http = MagicMock()
        # First two calls fail, third succeeds
        fail_response = _mock_response([], status_code=500)
        success_response = _mock_response(SAMPLE_ODDS_RESPONSE)
        mock_http.get.side_effect = [fail_response, fail_response, success_response]
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        events = client.get_odds("basketball_nba")
        assert len(events) == 2
        assert mock_sleep.call_count == 2

    @patch("ladderbot.data.odds.time.sleep")
    @patch("ladderbot.data.odds.httpx.Client")
    def test_raises_after_max_retries(self, mock_client_cls, mock_sleep, client):
        mock_http = MagicMock()
        fail_response = _mock_response([], status_code=500)
        mock_http.get.return_value = fail_response
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        with pytest.raises(OddsClientError, match="failed after 3 retries"):
            client.get_odds("basketball_nba")

    @patch("ladderbot.data.odds.time.sleep")
    @patch("ladderbot.data.odds.httpx.Client")
    def test_exponential_backoff(self, mock_client_cls, mock_sleep, client):
        mock_http = MagicMock()
        fail_response = _mock_response([], status_code=429)
        mock_http.get.return_value = fail_response
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        with pytest.raises(OddsClientError):
            client.get_odds("basketball_nba")

        # Check backoff times: 2^1=2, 2^2=4, 2^3=8
        assert mock_sleep.call_args_list[0][0][0] == 2
        assert mock_sleep.call_args_list[1][0][0] == 4
        assert mock_sleep.call_args_list[2][0][0] == 8


class TestOddsClientInit:
    def test_stores_api_key(self, db):
        client = OddsClient(api_key="my-key", db_conn=db)
        assert client.api_key == "my-key"

    def test_stores_db_conn(self, db):
        client = OddsClient(api_key="my-key", db_conn=db)
        assert client.db_conn is db
