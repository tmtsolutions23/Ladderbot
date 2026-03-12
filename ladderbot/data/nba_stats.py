"""NBA stats client for LadderBot.

Wraps the nba_api package to fetch team advanced stats, Four Factors,
game logs, and today's schedule. Implements rate limiting and caching.
"""
import logging
import sqlite3
import time
from datetime import datetime
from typing import Any

import pandas as pd

from ladderbot.data.cache import STATS_TTL, cache_get, cache_set

logger = logging.getLogger(__name__)

# Rate limiting
_CALL_DELAY = 0.75  # seconds between nba_api calls
_MAX_RETRIES = 5
_RETRY_BACKOFF = 5  # seconds on 429/403


def _current_season() -> str:
    """Return the current NBA season string, e.g. '2025-26'."""
    now = datetime.now()
    # NBA season starts in October. If we're in Oct-Dec, season is year-year+1.
    # If Jan-Sep, season is (year-1)-year.
    if now.month >= 10:
        start_year = now.year
    else:
        start_year = now.year - 1
    end_year_short = str(start_year + 1)[-2:]
    return f"{start_year}-{end_year_short}"


class NBAStatsClient:
    """Client for NBA stats via nba_api.

    Args:
        db_conn: SQLite database connection for caching.
    """

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self.db_conn = db_conn
        self._last_call_time: float = 0.0

    def _rate_limit(self) -> None:
        """Enforce minimum delay between nba_api calls."""
        elapsed = time.time() - self._last_call_time
        if elapsed < _CALL_DELAY:
            time.sleep(_CALL_DELAY - elapsed)
        self._last_call_time = time.time()

    def _call_with_retry(self, endpoint_cls: type, **kwargs: Any) -> Any:
        """Call an nba_api endpoint with retry on 429/403.

        Args:
            endpoint_cls: The nba_api endpoint class (e.g., LeagueDashTeamStats).
            **kwargs: Keyword arguments to pass to the endpoint constructor.

        Returns:
            The endpoint instance.

        Raises:
            Exception: If all retries are exhausted.
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            self._rate_limit()
            try:
                result = endpoint_cls(**kwargs)
                return result
            except Exception as exc:
                last_error = exc
                error_str = str(exc).lower()
                if "429" in error_str or "403" in error_str or "rate" in error_str:
                    wait = _RETRY_BACKOFF * (attempt + 1)
                    logger.warning(
                        "nba_api rate limited (attempt %d/%d): %s. "
                        "Retrying in %ds...",
                        attempt + 1,
                        _MAX_RETRIES,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    raise
        raise last_error  # type: ignore[misc]

    def get_team_advanced_stats(
        self, season: str | None = None
    ) -> pd.DataFrame:
        """Fetch team advanced stats (ORtg, DRtg, pace, net rating).

        Args:
            season: NBA season string, e.g. "2025-26". Defaults to current.

        Returns:
            DataFrame with team advanced stats.
        """
        if season is None:
            season = _current_season()

        cache_key = f"nba_team_advanced_{season}"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=STATS_TTL)
        if cached is not None:
            return pd.DataFrame(cached["data"])

        from nba_api.stats.endpoints import LeagueDashTeamStats

        endpoint = self._call_with_retry(
            LeagueDashTeamStats,
            season=season,
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
        )
        df = endpoint.get_data_frames()[0]

        cache_set(
            self.db_conn,
            cache_key,
            {"data": df.to_dict(orient="records")},
        )
        return df

    def get_team_four_factors(
        self, season: str | None = None
    ) -> pd.DataFrame:
        """Fetch team Four Factors stats (eFG%, TOV%, ORB%, FT/FGA).

        Args:
            season: NBA season string. Defaults to current.

        Returns:
            DataFrame with team Four Factors stats.
        """
        if season is None:
            season = _current_season()

        cache_key = f"nba_team_four_factors_{season}"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=STATS_TTL)
        if cached is not None:
            return pd.DataFrame(cached["data"])

        from nba_api.stats.endpoints import LeagueDashTeamStats

        endpoint = self._call_with_retry(
            LeagueDashTeamStats,
            season=season,
            measure_type_detailed_defense="Four Factors",
            per_mode_detailed="PerGame",
        )
        df = endpoint.get_data_frames()[0]

        cache_set(
            self.db_conn,
            cache_key,
            {"data": df.to_dict(orient="records")},
        )
        return df

    def get_team_game_logs(
        self, team_abbrev: str, last_n: int = 20
    ) -> pd.DataFrame:
        """Fetch recent game logs for a team.

        Args:
            team_abbrev: Team abbreviation, e.g. "BOS".
            last_n: Number of recent games to fetch.

        Returns:
            DataFrame with game log data.
        """
        cache_key = f"nba_game_logs_{team_abbrev}_{last_n}"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=STATS_TTL)
        if cached is not None:
            return pd.DataFrame(cached["data"])

        from nba_api.stats.endpoints import TeamGameLog
        from nba_api.stats.static import teams as nba_teams

        # Look up team ID from abbreviation
        team_list = nba_teams.find_teams_by_abbreviation(team_abbrev)
        if not team_list:
            raise ValueError(f"Unknown team abbreviation: {team_abbrev}")
        team_id = team_list[0]["id"]

        season = _current_season()
        endpoint = self._call_with_retry(
            TeamGameLog,
            team_id=team_id,
            season=season,
        )
        df = endpoint.get_data_frames()[0]

        # Limit to last N games
        df = df.head(last_n)

        cache_set(
            self.db_conn,
            cache_key,
            {"data": df.to_dict(orient="records")},
        )
        return df

    def get_todays_games(self) -> list[dict]:
        """Fetch today's NBA games from the scoreboard.

        Returns:
            List of game dicts with game_id, home_team, away_team,
            game_date, status.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        cache_key = f"nba_todays_games_{today}"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=STATS_TTL)
        if cached is not None:
            return cached["games"]

        from nba_api.stats.endpoints import ScoreboardV2

        endpoint = self._call_with_retry(
            ScoreboardV2,
            game_date=today,
        )
        df = endpoint.get_data_frames()[0]

        games = []
        for _, row in df.iterrows():
            game = {
                "game_id": str(row.get("GAME_ID", "")),
                "home_team_id": int(row.get("HOME_TEAM_ID", 0)),
                "away_team_id": int(row.get("VISITOR_TEAM_ID", 0)),
                "game_date": today,
                "status": str(row.get("GAME_STATUS_TEXT", "scheduled")),
            }
            games.append(game)

        cache_set(self.db_conn, cache_key, {"games": games})
        return games
