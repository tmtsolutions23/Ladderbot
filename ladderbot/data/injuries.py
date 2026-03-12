"""ESPN injury feed client for LadderBot.

Fetches NBA and NHL injury reports from ESPN's public API.
Provides goalie status lookup for NHL teams.
"""
import logging
import sqlite3
import time
from typing import Any

import httpx

from ladderbot.data.cache import INJURIES_TTL, cache_get, cache_set

logger = logging.getLogger(__name__)

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# Retry settings
_MAX_RETRIES = 3
_BACKOFF_BASE = 2


class InjuryClientError(Exception):
    """Raised when injury data fetching fails."""
    pass


class InjuryClient:
    """Client for ESPN injury feeds.

    Args:
        db_conn: SQLite database connection for caching.
    """

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self.db_conn = db_conn

    def get_nba_injuries(self) -> list[dict]:
        """Fetch current NBA injury report.

        Returns:
            List of injury dicts with player, team, status, description.
        """
        return self._get_injuries("basketball", "nba")

    def get_nhl_injuries(self) -> list[dict]:
        """Fetch current NHL injury report.

        Returns:
            List of injury dicts with player, team, status, description.
        """
        return self._get_injuries("hockey", "nhl")

    def get_nhl_goalie_status(self, team: str) -> dict:
        """Look up the starting goalie status for an NHL team.

        Searches the NHL injury report for goalies on the given team.
        If no goalie is listed as injured, assumes the starter is healthy.

        Args:
            team: Team abbreviation (e.g., "BOS", "NYR").

        Returns:
            Dict with starter (str or None), status (str), and
            injured_goalies (list of injury dicts for goalies on the team).
        """
        injuries = self.get_nhl_injuries()

        # Filter injuries to goalies on the specified team
        team_upper = team.upper()
        goalie_injuries = [
            inj for inj in injuries
            if inj.get("team", "").upper() == team_upper
            and inj.get("position", "").upper() in ("G", "GOALIE", "GOALKEEPER")
        ]

        if not goalie_injuries:
            return {
                "starter": None,
                "status": "healthy",
                "injured_goalies": [],
            }

        return {
            "starter": None,
            "status": "goalie_injured",
            "injured_goalies": goalie_injuries,
        }

    def _get_injuries(self, sport: str, league: str) -> list[dict]:
        """Fetch injuries from ESPN API for a given sport/league.

        Args:
            sport: ESPN sport category (e.g., "basketball", "hockey").
            league: ESPN league key (e.g., "nba", "nhl").

        Returns:
            List of injury dicts.
        """
        cache_key = f"injuries_{league}"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=INJURIES_TTL)
        if cached is not None:
            return cached["injuries"]

        url = f"{_ESPN_BASE}/{sport}/{league}/injuries"
        data = self._request_with_retry(url)

        injuries = self._parse_injuries(data, league)
        cache_set(self.db_conn, cache_key, {"injuries": injuries})
        return injuries

    def _parse_injuries(self, data: dict, league: str) -> list[dict]:
        """Parse ESPN injury API response into a flat list.

        The ESPN API returns injuries grouped by team. This flattens
        them into individual injury records.
        """
        injuries = []

        for team_data in data.get("items", []):
            team_info = team_data.get("team", {})
            team_abbrev = team_info.get("abbreviation", "")
            team_name = team_info.get("displayName", "")

            for athlete_entry in team_data.get("injuries", []):
                athlete = athlete_entry.get("athlete", {})
                player_name = athlete.get("displayName", "")
                position = athlete.get("position", {}).get("abbreviation", "")

                status = athlete_entry.get("status", "")
                description = athlete_entry.get("details", {}).get(
                    "detail", athlete_entry.get("longComment", "")
                )
                injury_type = athlete_entry.get("details", {}).get("type", "")

                injuries.append({
                    "player": player_name,
                    "team": team_abbrev,
                    "team_name": team_name,
                    "position": position,
                    "status": status,
                    "description": description,
                    "injury_type": injury_type,
                    "league": league,
                })

        return injuries

    def _request_with_retry(self, url: str, params: dict | None = None) -> dict:
        """Make an HTTP GET request with retry and backoff.

        Returns:
            Parsed JSON response.

        Raises:
            InjuryClientError: After all retries exhausted.
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(url, params=params)
                    response.raise_for_status()
                    return response.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_error = exc
                wait = _BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "ESPN injury API request failed (attempt %d/%d): %s. "
                    "Retrying in %ds...",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise InjuryClientError(
            f"ESPN injury API failed after {_MAX_RETRIES} retries: {last_error}"
        )
