"""The Odds API client for LadderBot.

Fetches real-time NBA/NHL odds from The Odds API.
Caches responses in SQLite and stores snapshots for historical tracking.
"""
import json
import logging
import sqlite3
import time
from typing import Any

import httpx

from ladderbot.data.cache import ODDS_TTL, cache_get, cache_set
from ladderbot.db.database import insert_odds_snapshot, insert_game

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.the-odds-api.com/v4/sports"

# Retry settings
_MAX_RETRIES = 3
_BACKOFF_BASE = 2  # seconds: 2, 4, 8


class OddsClientError(Exception):
    """Raised when the Odds API client encounters an unrecoverable error."""
    pass


class OddsClient:
    """Client for The Odds API.

    Args:
        api_key: The Odds API key.
        db_conn: SQLite database connection for caching and snapshot storage.
    """

    def __init__(self, api_key: str, db_conn: sqlite3.Connection) -> None:
        self.api_key = api_key
        self.db_conn = db_conn

    def get_upcoming_games(self, sport: str) -> list[dict]:
        """Fetch upcoming games for a sport.

        Args:
            sport: Sport key, e.g. "basketball_nba" or "icehockey_nhl".

        Returns:
            List of game dicts with id, sport_key, home_team, away_team,
            commence_time.
        """
        cache_key = f"odds_upcoming_{sport}"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=ODDS_TTL)
        if cached is not None:
            return cached["games"]

        url = f"{_BASE_URL}/{sport}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "american",
        }

        data = self._request_with_retry(url, params)
        games = []
        for event in data:
            game = {
                "id": event.get("id"),
                "sport_key": event.get("sport_key"),
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "commence_time": event.get("commence_time"),
            }
            games.append(game)

        cache_set(self.db_conn, cache_key, {"games": games})
        return games

    def get_odds(
        self, sport: str, markets: str = "h2h,totals"
    ) -> list[dict]:
        """Fetch odds for a sport with specified markets.

        Args:
            sport: Sport key, e.g. "basketball_nba" or "icehockey_nhl".
            markets: Comma-separated market types (h2h, spreads, totals).

        Returns:
            List of event dicts with bookmaker odds.
        """
        cache_key = f"odds_{sport}_{markets}"
        cached = cache_get(self.db_conn, cache_key, ttl_seconds=ODDS_TTL)
        if cached is not None:
            return cached["events"]

        url = f"{_BASE_URL}/{sport}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": markets,
            "oddsFormat": "american",
        }

        data = self._request_with_retry(url, params)

        # Store snapshots in database
        self._store_snapshots(data, sport)

        cache_set(self.db_conn, cache_key, {"events": data})
        return data

    def _store_snapshots(self, events: list[dict], sport: str) -> None:
        """Store odds snapshots in the database for historical tracking."""
        sport_short = "nba" if "nba" in sport else "nhl"
        for event in events:
            game_id = event.get("id", "")
            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")
            commence = event.get("commence_time", "")
            game_date = commence[:10] if commence else ""

            # Upsert the game record
            try:
                insert_game(
                    self.db_conn,
                    game_id=game_id,
                    sport=sport_short,
                    home_team=home_team,
                    away_team=away_team,
                    game_date=game_date,
                )
            except Exception:
                logger.debug("Game %s already exists or insert failed", game_id)

            # Store each bookmaker's odds
            for bookmaker in event.get("bookmakers", []):
                bk_name = bookmaker.get("key", "")
                for market in bookmaker.get("markets", []):
                    market_key = market.get("key", "")
                    for outcome in market.get("outcomes", []):
                        try:
                            insert_odds_snapshot(
                                self.db_conn,
                                game_id=game_id,
                                bookmaker=bk_name,
                                market=market_key,
                                outcome=outcome.get("name", ""),
                                price=outcome.get("price", 0),
                                point=outcome.get("point"),
                            )
                        except Exception:
                            logger.debug(
                                "Failed to store odds snapshot for %s", game_id
                            )

    def _request_with_retry(
        self, url: str, params: dict[str, Any]
    ) -> list[dict]:
        """Make an HTTP GET request with retry and exponential backoff.

        Args:
            url: Request URL.
            params: Query parameters.

        Returns:
            Parsed JSON response as a list of dicts.

        Raises:
            OddsClientError: After all retries are exhausted.
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
                    "Odds API request failed (attempt %d/%d): %s. "
                    "Retrying in %ds...",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise OddsClientError(
            f"Odds API request failed after {_MAX_RETRIES} retries: {last_error}"
        )
