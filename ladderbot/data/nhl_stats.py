"""NHL stats client for LadderBot.

Fetches NHL schedule, standings, and game results from the NHL API,
plus advanced stats (xG, goalie GSAx) from MoneyPuck CSV downloads.
"""
import csv
import io
import logging
import sqlite3
import time
from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from ladderbot.data.cache import STATS_TTL, cache_get, cache_set

logger = logging.getLogger(__name__)

_NHL_API_BASE = "https://api-web.nhle.com/v1"
_MONEYPUCK_BASE = "https://moneypuck.com/moneypuck/playerData/seasonSummary"

# Current season tag for MoneyPuck URLs
_MONEYPUCK_SEASON = "2025"  # MoneyPuck uses start year of season

# Retry settings
_MAX_RETRIES = 3
_BACKOFF_BASE = 2


class NHLStatsError(Exception):
    """Raised when NHL stats fetching fails."""
    pass


class NHLStatsClient:
    """Client for NHL stats from NHL API and MoneyPuck.

    Args:
        db_conn: SQLite database connection for caching.
    """

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self.db_conn = db_conn

    def get_schedule(self, date_str: str | None = None) -> list[dict]:
        """Fetch NHL schedule for a given date.

        Args:
            date_str: Date in YYYY-MM-DD format. Defaults to today.

        Returns:
            List of game dicts with id, home_team, away_team, start_time, status.
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        cache_key = f"nhl_schedule_{date_str}"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=STATS_TTL)
        if cached is not None:
            return cached["games"]

        url = f"{_NHL_API_BASE}/schedule/{date_str}"
        data = self._request_with_retry(url)

        games = []
        for game_week in data.get("gameWeek", []):
            for game in game_week.get("games", []):
                parsed = {
                    "id": str(game.get("id", "")),
                    "home_team": game.get("homeTeam", {}).get("abbrev", ""),
                    "away_team": game.get("awayTeam", {}).get("abbrev", ""),
                    "start_time": game.get("startTimeUTC", ""),
                    "status": game.get("gameState", "scheduled"),
                    "venue": game.get("venue", {}).get("default", ""),
                }
                games.append(parsed)

        cache_set(self.db_conn, cache_key, {"games": games})
        return games

    def get_standings(self) -> list[dict]:
        """Fetch current NHL standings.

        Returns:
            List of team standing dicts with team, wins, losses, ot_losses,
            points, games_played, goal_diff.
        """
        cache_key = "nhl_standings"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=STATS_TTL)
        if cached is not None:
            return cached["standings"]

        url = f"{_NHL_API_BASE}/standings/now"
        data = self._request_with_retry(url)

        standings = []
        for team_data in data.get("standings", []):
            entry = {
                "team": team_data.get("teamAbbrev", {}).get("default", ""),
                "team_name": team_data.get("teamName", {}).get("default", ""),
                "wins": team_data.get("wins", 0),
                "losses": team_data.get("losses", 0),
                "ot_losses": team_data.get("otLosses", 0),
                "points": team_data.get("points", 0),
                "games_played": team_data.get("gamesPlayed", 0),
                "goal_diff": team_data.get("goalDifferential", 0),
                "goals_for": team_data.get("goalFor", 0),
                "goals_against": team_data.get("goalAgainst", 0),
            }
            standings.append(entry)

        cache_set(self.db_conn, cache_key, {"standings": standings})
        return standings

    def get_team_xg_stats(self) -> pd.DataFrame:
        """Download MoneyPuck team-level xG stats.

        Returns:
            DataFrame with team xG stats (xGF/60, xGA/60, CF%, FF%, etc.).
        """
        cache_key = "nhl_team_xg_stats"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=STATS_TTL)
        if cached is not None:
            return pd.DataFrame(cached["data"])

        url = f"{_MONEYPUCK_BASE}/{_MONEYPUCK_SEASON}/regular/teams.csv"
        csv_text = self._request_csv(url)
        df = pd.read_csv(io.StringIO(csv_text))

        cache_set(
            self.db_conn,
            cache_key,
            {"data": df.to_dict(orient="records")},
        )
        return df

    def get_goalie_stats(self) -> pd.DataFrame:
        """Download MoneyPuck goalie stats (GSAx, HDSV%, etc.).

        Returns:
            DataFrame with goalie stats.
        """
        cache_key = "nhl_goalie_stats"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=STATS_TTL)
        if cached is not None:
            return pd.DataFrame(cached["data"])

        url = f"{_MONEYPUCK_BASE}/{_MONEYPUCK_SEASON}/regular/goalies.csv"
        csv_text = self._request_csv(url)
        df = pd.read_csv(io.StringIO(csv_text))

        cache_set(
            self.db_conn,
            cache_key,
            {"data": df.to_dict(orient="records")},
        )
        return df

    def get_game_result(self, game_id: str) -> dict:
        """Fetch the result of a specific game.

        Args:
            game_id: NHL game ID string.

        Returns:
            Dict with game_id, home_team, away_team, home_score, away_score,
            status, period.
        """
        cache_key = f"nhl_game_result_{game_id}"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=STATS_TTL)
        if cached is not None:
            return cached["result"]

        url = f"{_NHL_API_BASE}/gamecenter/{game_id}/landing"
        data = self._request_with_retry(url)

        result = {
            "game_id": game_id,
            "home_team": data.get("homeTeam", {}).get("abbrev", ""),
            "away_team": data.get("awayTeam", {}).get("abbrev", ""),
            "home_score": data.get("homeTeam", {}).get("score", 0),
            "away_score": data.get("awayTeam", {}).get("score", 0),
            "status": data.get("gameState", ""),
            "period": data.get("periodDescriptor", {}).get("number", 0),
        }

        # Only cache final results permanently
        if result["status"] in ("FINAL", "OFF"):
            cache_set(self.db_conn, cache_key, {"result": result})

        return result

    def _request_with_retry(self, url: str, params: dict | None = None) -> dict:
        """Make an HTTP GET request with retry and backoff.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            NHLStatsError: After all retries exhausted.
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
                    "NHL API request failed (attempt %d/%d): %s. "
                    "Retrying in %ds...",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise NHLStatsError(
            f"NHL API request failed after {_MAX_RETRIES} retries: {last_error}"
        )

    def _request_csv(self, url: str) -> str:
        """Download a CSV file with retry.

        Returns:
            CSV content as string.

        Raises:
            NHLStatsError: After all retries exhausted.
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    return response.text
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_error = exc
                wait = _BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "MoneyPuck CSV download failed (attempt %d/%d): %s. "
                    "Retrying in %ds...",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise NHLStatsError(
            f"MoneyPuck CSV download failed after {_MAX_RETRIES} retries: {last_error}"
        )
