"""Tests for the ESPN injury feed client."""
import sqlite3
from unittest.mock import patch, MagicMock

import pytest
import httpx

from ladderbot.data.injuries import InjuryClient, InjuryClientError
from ladderbot.data.cache import cache_set, INJURIES_TTL
from ladderbot.db.database import get_db


@pytest.fixture
def db(tmp_path):
    """Provide an initialized database connection."""
    conn = get_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    """Provide an InjuryClient instance."""
    return InjuryClient(db_conn=db)


# -- Sample ESPN API responses --

SAMPLE_NBA_INJURIES_RESPONSE = {
    "items": [
        {
            "team": {
                "abbreviation": "BOS",
                "displayName": "Boston Celtics",
            },
            "injuries": [
                {
                    "athlete": {
                        "displayName": "Kristaps Porzingis",
                        "position": {"abbreviation": "C"},
                    },
                    "status": "Out",
                    "details": {
                        "detail": "Right ankle sprain",
                        "type": "Ankle",
                    },
                    "longComment": "",
                },
                {
                    "athlete": {
                        "displayName": "Jrue Holiday",
                        "position": {"abbreviation": "PG"},
                    },
                    "status": "Questionable",
                    "details": {
                        "detail": "Left knee soreness",
                        "type": "Knee",
                    },
                    "longComment": "",
                },
            ],
        },
        {
            "team": {
                "abbreviation": "MIL",
                "displayName": "Milwaukee Bucks",
            },
            "injuries": [
                {
                    "athlete": {
                        "displayName": "Khris Middleton",
                        "position": {"abbreviation": "SF"},
                    },
                    "status": "Doubtful",
                    "details": {
                        "detail": "Left ankle surgery recovery",
                        "type": "Ankle",
                    },
                    "longComment": "",
                },
            ],
        },
    ]
}

SAMPLE_NHL_INJURIES_RESPONSE = {
    "items": [
        {
            "team": {
                "abbreviation": "BOS",
                "displayName": "Boston Bruins",
            },
            "injuries": [
                {
                    "athlete": {
                        "displayName": "Jeremy Swayman",
                        "position": {"abbreviation": "G"},
                    },
                    "status": "Day-to-Day",
                    "details": {
                        "detail": "Lower body injury",
                        "type": "Lower Body",
                    },
                    "longComment": "",
                },
                {
                    "athlete": {
                        "displayName": "David Pastrnak",
                        "position": {"abbreviation": "RW"},
                    },
                    "status": "Out",
                    "details": {
                        "detail": "Upper body injury",
                        "type": "Upper Body",
                    },
                    "longComment": "",
                },
            ],
        },
        {
            "team": {
                "abbreviation": "NYR",
                "displayName": "New York Rangers",
            },
            "injuries": [],
        },
    ]
}


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


class TestGetNBAInjuries:
    @patch("ladderbot.data.injuries.httpx.Client")
    def test_returns_injuries(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_NBA_INJURIES_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        injuries = client.get_nba_injuries()
        assert len(injuries) == 3
        assert injuries[0]["player"] == "Kristaps Porzingis"
        assert injuries[0]["team"] == "BOS"
        assert injuries[0]["status"] == "Out"
        assert injuries[0]["description"] == "Right ankle sprain"

    @patch("ladderbot.data.injuries.httpx.Client")
    def test_includes_all_fields(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_NBA_INJURIES_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        injuries = client.get_nba_injuries()
        inj = injuries[0]
        assert "player" in inj
        assert "team" in inj
        assert "status" in inj
        assert "description" in inj
        assert "position" in inj
        assert inj["league"] == "nba"

    @patch("ladderbot.data.injuries.httpx.Client")
    def test_caches_response(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_NBA_INJURIES_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        client.get_nba_injuries()
        client.get_nba_injuries()
        assert mock_client_cls.call_count == 1

    def test_returns_cached_injuries(self, client, db):
        cached = [
            {"player": "Test Player", "team": "BOS", "status": "Out",
             "description": "Test", "position": "C", "team_name": "Celtics",
             "injury_type": "Knee", "league": "nba"},
        ]
        cache_set(db, "injuries_nba", {"injuries": cached})
        injuries = client.get_nba_injuries()
        assert len(injuries) == 1
        assert injuries[0]["player"] == "Test Player"


class TestGetNHLInjuries:
    @patch("ladderbot.data.injuries.httpx.Client")
    def test_returns_injuries(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_NHL_INJURIES_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        injuries = client.get_nhl_injuries()
        assert len(injuries) == 2
        assert injuries[0]["player"] == "Jeremy Swayman"
        assert injuries[0]["team"] == "BOS"
        assert injuries[0]["position"] == "G"
        assert injuries[1]["player"] == "David Pastrnak"

    @patch("ladderbot.data.injuries.httpx.Client")
    def test_handles_team_with_no_injuries(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_NHL_INJURIES_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        injuries = client.get_nhl_injuries()
        # NYR has empty injuries list, so should only get BOS players
        nyr_injuries = [i for i in injuries if i["team"] == "NYR"]
        assert len(nyr_injuries) == 0


class TestGetNHLGoalieStatus:
    @patch("ladderbot.data.injuries.httpx.Client")
    def test_goalie_injured(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_NHL_INJURIES_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        status = client.get_nhl_goalie_status("BOS")
        assert status["status"] == "goalie_injured"
        assert len(status["injured_goalies"]) == 1
        assert status["injured_goalies"][0]["player"] == "Jeremy Swayman"

    @patch("ladderbot.data.injuries.httpx.Client")
    def test_no_goalie_injury(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_NHL_INJURIES_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        status = client.get_nhl_goalie_status("NYR")
        assert status["status"] == "healthy"
        assert len(status["injured_goalies"]) == 0

    @patch("ladderbot.data.injuries.httpx.Client")
    def test_case_insensitive_team(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_NHL_INJURIES_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        status = client.get_nhl_goalie_status("bos")
        assert status["status"] == "goalie_injured"

    @patch("ladderbot.data.injuries.httpx.Client")
    def test_unknown_team_returns_healthy(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response(SAMPLE_NHL_INJURIES_RESPONSE)
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        status = client.get_nhl_goalie_status("XYZ")
        assert status["status"] == "healthy"
        assert len(status["injured_goalies"]) == 0


class TestRetryLogic:
    @patch("ladderbot.data.injuries.time.sleep")
    @patch("ladderbot.data.injuries.httpx.Client")
    def test_retries_on_failure(self, mock_client_cls, mock_sleep, client):
        mock_http = MagicMock()
        fail = _mock_response({}, status_code=500)
        success = _mock_response(SAMPLE_NBA_INJURIES_RESPONSE)
        mock_http.get.side_effect = [fail, success]
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        injuries = client.get_nba_injuries()
        assert len(injuries) == 3

    @patch("ladderbot.data.injuries.time.sleep")
    @patch("ladderbot.data.injuries.httpx.Client")
    def test_raises_after_max_retries(self, mock_client_cls, mock_sleep, client):
        mock_http = MagicMock()
        fail = _mock_response({}, status_code=503)
        mock_http.get.return_value = fail
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        with pytest.raises(InjuryClientError, match="failed after 3 retries"):
            client.get_nba_injuries()

    @patch("ladderbot.data.injuries.time.sleep")
    @patch("ladderbot.data.injuries.httpx.Client")
    def test_exponential_backoff(self, mock_client_cls, mock_sleep, client):
        mock_http = MagicMock()
        fail = _mock_response({}, status_code=500)
        mock_http.get.return_value = fail
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        with pytest.raises(InjuryClientError):
            client.get_nba_injuries()

        assert mock_sleep.call_args_list[0][0][0] == 2
        assert mock_sleep.call_args_list[1][0][0] == 4
        assert mock_sleep.call_args_list[2][0][0] == 8


class TestEmptyResponse:
    @patch("ladderbot.data.injuries.httpx.Client")
    def test_empty_items(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response({"items": []})
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        injuries = client.get_nba_injuries()
        assert injuries == []

    @patch("ladderbot.data.injuries.httpx.Client")
    def test_missing_items_key(self, mock_client_cls, client):
        mock_http = MagicMock()
        mock_http.get.return_value = _mock_response({})
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        injuries = client.get_nba_injuries()
        assert injuries == []


class TestInjuryClientInit:
    def test_stores_db_conn(self, db):
        client = InjuryClient(db_conn=db)
        assert client.db_conn is db
