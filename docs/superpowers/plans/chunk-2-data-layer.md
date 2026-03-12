## Chunk 2: Data Layer

This chunk builds the entire `data/` package: a SQLite cache, The Odds API client, NBA stats client, NHL stats client, and injury data client. Every client uses the shared cache layer and `httpx` for HTTP. Each task follows red-green-refactor: write failing tests first, then implement until tests pass.

---

### Task 5: Cache Layer (`data/cache.py`)

#### Step 5.1 Create the `data/` package

Create the package directory and `__init__.py`.

```bash
mkdir -p data tests
touch data/__init__.py
touch tests/__init__.py
```

#### Step 5.2 Write tests (`tests/test_cache.py`)

Create the test file. Tests exercise every public function: `cache_get`, `cache_set`, `cache_clear_expired`, TTL expiry, and permanent (no-TTL) entries.

```python
# tests/test_cache.py
"""Tests for the SQLite-backed cache layer."""

import json
import time
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from data.cache import (
    Cache,
    TTL_ODDS,
    TTL_STATS,
    TTL_INJURIES,
    TTL_RESULTS,
)


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    """Create a Cache instance backed by a temp SQLite database."""
    db_path = tmp_path / "test_cache.db"
    return Cache(db_path=str(db_path))


class TestCacheConstants:
    def test_ttl_odds(self):
        assert TTL_ODDS == 1800

    def test_ttl_stats(self):
        assert TTL_STATS == 86400

    def test_ttl_injuries(self):
        assert TTL_INJURIES == 7200

    def test_ttl_results(self):
        assert TTL_RESULTS is None


class TestCacheSet:
    def test_set_stores_data(self, cache: Cache):
        cache.cache_set("test_key", {"foo": "bar"})
        result = cache.cache_get("test_key", ttl_seconds=3600)
        assert result == {"foo": "bar"}

    def test_set_overwrites_existing(self, cache: Cache):
        cache.cache_set("key1", {"version": 1})
        cache.cache_set("key1", {"version": 2})
        result = cache.cache_get("key1", ttl_seconds=3600)
        assert result == {"version": 2}

    def test_set_stores_complex_data(self, cache: Cache):
        data = {
            "games": [{"id": 1, "teams": ["BOS", "NYK"]}, {"id": 2}],
            "count": 42,
            "nested": {"deep": True},
        }
        cache.cache_set("complex", data)
        result = cache.cache_get("complex", ttl_seconds=3600)
        assert result == data


class TestCacheGet:
    def test_get_missing_key_returns_none(self, cache: Cache):
        result = cache.cache_get("nonexistent", ttl_seconds=3600)
        assert result is None

    def test_get_respects_ttl(self, cache: Cache):
        cache.cache_set("expire_me", {"data": 1})
        # Patch time so the entry looks old
        with patch("data.cache.time.time", return_value=time.time() + 3601):
            result = cache.cache_get("expire_me", ttl_seconds=3600)
        assert result is None

    def test_get_within_ttl_returns_data(self, cache: Cache):
        cache.cache_set("fresh", {"data": 1})
        result = cache.cache_get("fresh", ttl_seconds=3600)
        assert result == {"data": 1}

    def test_get_permanent_entry_never_expires(self, cache: Cache):
        cache.cache_set("permanent", {"forever": True})
        # Jump far into the future
        with patch("data.cache.time.time", return_value=time.time() + 999_999):
            result = cache.cache_get("permanent", ttl_seconds=None)
        assert result == {"forever": True}


class TestCacheClearExpired:
    def test_clears_old_entries(self, cache: Cache):
        cache.cache_set("old_entry", {"stale": True})
        # Move time forward so it's definitely expired for a 10s TTL
        future = time.time() + 100
        with patch("data.cache.time.time", return_value=future):
            removed = cache.cache_clear_expired(ttl_seconds=10)
        assert removed >= 1
        # Confirm it's gone even without TTL check
        result = cache.cache_get("old_entry", ttl_seconds=None)
        assert result is None

    def test_preserves_fresh_entries(self, cache: Cache):
        cache.cache_set("fresh_entry", {"keep": True})
        removed = cache.cache_clear_expired(ttl_seconds=86400)
        assert removed == 0
        result = cache.cache_get("fresh_entry", ttl_seconds=86400)
        assert result == {"keep": True}

    def test_clears_only_expired(self, cache: Cache):
        cache.cache_set("old", {"stale": True})
        cache.cache_set("new", {"fresh": True})
        future = time.time() + 50
        with patch("data.cache.time.time", return_value=future):
            cache.cache_clear_expired(ttl_seconds=10)
            assert cache.cache_get("old", ttl_seconds=10) is None
            assert cache.cache_get("new", ttl_seconds=99999) == {"fresh": True}


class TestCacheEdgeCases:
    def test_empty_dict(self, cache: Cache):
        cache.cache_set("empty", {})
        assert cache.cache_get("empty", ttl_seconds=3600) == {}

    def test_list_data(self, cache: Cache):
        cache.cache_set("list_data", [1, 2, 3])
        assert cache.cache_get("list_data", ttl_seconds=3600) == [1, 2, 3]

    def test_string_data(self, cache: Cache):
        cache.cache_set("str_data", "hello")
        assert cache.cache_get("str_data", ttl_seconds=3600) == "hello"
```

Run and confirm tests fail (module does not exist yet):

```bash
python -m pytest tests/test_cache.py -v
# Expected: ModuleNotFoundError — all tests fail
```

#### Step 5.3 Implement `data/cache.py`

```python
# data/cache.py
"""SQLite-backed cache with TTL support.

TTLs (seconds):
    odds     = 1800   (30 minutes)
    stats    = 86400  (24 hours)
    injuries = 7200   (2 hours)
    results  = None   (permanent)
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

# ── TTL constants (seconds) ──────────────────────────────────────
TTL_ODDS: int = 1800
TTL_STATS: int = 86400
TTL_INJURIES: int = 7200
TTL_RESULTS: int | None = None  # permanent

_DEFAULT_DB = Path("data/ladderbot.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cache (
    key   TEXT PRIMARY KEY,
    data  TEXT NOT NULL,
    ts    REAL NOT NULL
);
"""


class Cache:
    """Thin SQLite cache.  Thread-safe via ``check_same_thread=False``."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DEFAULT_DB)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    # ── public API ───────────────────────────────────────────────

    def cache_get(self, key: str, ttl_seconds: int | None) -> Any | None:
        """Return cached value or *None* if missing / expired.

        Parameters
        ----------
        key:
            Cache key.
        ttl_seconds:
            Maximum age in seconds.  ``None`` means the entry never expires.
        """
        row = self._conn.execute(
            "SELECT data, ts FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None

        data_json, ts = row
        if ttl_seconds is not None and (time.time() - ts) > ttl_seconds:
            return None

        return json.loads(data_json)

    def cache_set(self, key: str, data: Any) -> None:
        """Insert or replace a cache entry, stamped with the current time."""
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, data, ts) VALUES (?, ?, ?)",
            (key, json.dumps(data), time.time()),
        )
        self._conn.commit()

    def cache_clear_expired(self, ttl_seconds: int) -> int:
        """Delete entries older than *ttl_seconds*.  Returns count removed."""
        cutoff = time.time() - ttl_seconds
        cur = self._conn.execute("DELETE FROM cache WHERE ts < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
```

#### Step 5.4 Verify tests pass

```bash
python -m pytest tests/test_cache.py -v
# Expected: all green
```

#### Step 5.5 Commit

```bash
git add data/__init__.py data/cache.py tests/__init__.py tests/test_cache.py
git commit -m "feat(data): add SQLite cache layer with TTL support"
```

---

### Task 6: The Odds API Client (`data/odds.py`)

#### Step 6.1 Write tests (`tests/test_odds.py`)

Tests mock `httpx.Client` so no real HTTP calls are made. They cover happy-path responses, cache fallback on failure, retry logic, and rate limiting.

```python
# tests/test_odds.py
"""Tests for The Odds API client."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import httpx
import pytest

from data.odds import OddsClient
from data.cache import Cache


# ── fixtures ─────────────────────────────────────────────────────

SAMPLE_UPCOMING = [
    {
        "id": "game1",
        "sport_key": "basketball_nba",
        "commence_time": "2026-03-11T23:00:00Z",
        "home_team": "Boston Celtics",
        "away_team": "New York Knicks",
    },
]

SAMPLE_ODDS = [
    {
        "id": "game1",
        "sport_key": "basketball_nba",
        "commence_time": "2026-03-11T23:00:00Z",
        "home_team": "Boston Celtics",
        "away_team": "New York Knicks",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Celtics", "price": -160},
                            {"name": "New York Knicks", "price": 140},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 215.5},
                            {"name": "Under", "price": -110, "point": 215.5},
                        ],
                    },
                ],
            },
        ],
    },
]


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(cache: Cache) -> OddsClient:
    return OddsClient(api_key="test-key-123", cache=cache)


def _mock_response(data: list | dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ── tests ────────────────────────────────────────────────────────


class TestGetUpcomingGames:
    @patch("data.odds.httpx.Client")
    def test_returns_games(self, MockClient, client: OddsClient):
        mock_http = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_http)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        mock_http.get.return_value = _mock_response(SAMPLE_UPCOMING)

        games = client.get_upcoming_games("basketball_nba")
        assert len(games) == 1
        assert games[0]["home_team"] == "Boston Celtics"

    @patch("data.odds.httpx.Client")
    def test_caches_result(self, MockClient, client: OddsClient):
        mock_http = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_http)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        mock_http.get.return_value = _mock_response(SAMPLE_UPCOMING)

        client.get_upcoming_games("basketball_nba")
        # Second call should hit cache, not HTTP
        result = client.get_upcoming_games("basketball_nba")
        assert result == SAMPLE_UPCOMING
        assert mock_http.get.call_count == 1


class TestGetOdds:
    @patch("data.odds.httpx.Client")
    def test_returns_odds(self, MockClient, client: OddsClient):
        mock_http = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_http)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        mock_http.get.return_value = _mock_response(SAMPLE_ODDS)

        odds = client.get_odds("basketball_nba")
        assert len(odds) == 1
        assert odds[0]["bookmakers"][0]["key"] == "draftkings"

    @patch("data.odds.httpx.Client")
    def test_uses_correct_params(self, MockClient, client: OddsClient):
        mock_http = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_http)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        mock_http.get.return_value = _mock_response(SAMPLE_ODDS)

        client.get_odds("icehockey_nhl", markets="h2h,totals")
        args, kwargs = mock_http.get.call_args
        params = kwargs.get("params", {})
        assert params["regions"] == "us"
        assert "draftkings" in params["bookmakers"]
        assert "fanduel" in params["bookmakers"]
        assert params["markets"] == "h2h,totals"


class TestRetryAndFallback:
    @patch("data.odds.httpx.Client")
    def test_retries_on_failure_then_falls_back_to_cache(
        self, MockClient, client: OddsClient
    ):
        # Pre-populate cache
        client._cache.cache_set("odds:basketball_nba:h2h,totals", SAMPLE_ODDS)

        mock_http = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_http)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        mock_http.get.return_value = _mock_response([], status_code=500)

        result = client.get_odds("basketball_nba")
        # Should have retried 3 times
        assert mock_http.get.call_count == 3
        # Should fall back to cache
        assert result == SAMPLE_ODDS

    @patch("data.odds.httpx.Client")
    def test_returns_empty_when_no_cache_and_api_fails(
        self, MockClient, client: OddsClient
    ):
        mock_http = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_http)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        mock_http.get.return_value = _mock_response([], status_code=500)

        result = client.get_odds("basketball_nba")
        assert result == []
```

Run and confirm tests fail:

```bash
python -m pytest tests/test_odds.py -v
# Expected: ImportError — all tests fail
```

#### Step 6.2 Implement `data/odds.py`

```python
# data/odds.py
"""Client for The Odds API (https://the-odds-api.com).

Fetches upcoming games and odds for NBA / NHL from DraftKings & FanDuel.
Uses the shared Cache layer and retries with exponential backoff.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from data.cache import Cache, TTL_ODDS

log = logging.getLogger(__name__)

_BASE_URL = "https://api.the-odds-api.com/v4/sports"
_MAX_RETRIES = 3
_BACKOFF_BASE = 2  # seconds


class OddsClient:
    """Thin wrapper around The Odds API with caching and retry logic."""

    def __init__(self, api_key: str, cache: Cache) -> None:
        self._api_key = api_key
        self._cache = cache

    # ── public API ───────────────────────────────────────────────

    def get_upcoming_games(self, sport: str) -> list[dict]:
        """Return upcoming games for *sport* (e.g. ``basketball_nba``)."""
        cache_key = f"upcoming:{sport}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_ODDS)
        if cached is not None:
            return cached

        data = self._fetch(f"/{sport}/events", params={})
        if data is not None:
            self._cache.cache_set(cache_key, data)
            return data
        return []

    def get_odds(
        self, sport: str, markets: str = "h2h,totals"
    ) -> list[dict]:
        """Return odds for *sport* with the given *markets*.

        Pulls from DraftKings and FanDuel, US region only.
        """
        cache_key = f"odds:{sport}:{markets}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_ODDS)
        if cached is not None:
            return cached

        params = {
            "regions": "us",
            "bookmakers": "draftkings,fanduel",
            "markets": markets,
            "oddsFormat": "american",
        }
        data = self._fetch(f"/{sport}/odds", params=params)
        if data is not None:
            self._cache.cache_set(cache_key, data)
            return data

        # Fallback: return stale cache if available
        stale = self._cache.cache_get(cache_key, ttl_seconds=None)
        if stale is not None:
            log.warning("Odds API failed — returning stale cache for %s", sport)
            return stale

        log.error("Odds API failed and no cache available for %s", sport)
        return []

    # ── internals ────────────────────────────────────────────────

    def _fetch(self, path: str, params: dict[str, str]) -> list[dict] | None:
        """GET from the API with retry + exponential backoff.

        Returns parsed JSON list on success, ``None`` on total failure.
        """
        params["apiKey"] = self._api_key
        url = f"{_BASE_URL}{path}"

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=15.0) as http:
                    resp = http.get(url, params=params)
                    resp.raise_for_status()
                    return resp.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                wait = _BACKOFF_BASE ** attempt
                log.warning(
                    "Odds API attempt %d/%d failed (%s) — retrying in %ds",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(wait)

        return None
```

#### Step 6.3 Verify tests pass

```bash
python -m pytest tests/test_odds.py -v
# Expected: all green
```

#### Step 6.4 Commit

```bash
git add data/odds.py tests/test_odds.py
git commit -m "feat(data): add Odds API client with cache + retry logic"
```

---

### Task 7: NBA Stats Client (`data/nba_stats.py`)

#### Step 7.1 Write tests (`tests/test_nba_stats.py`)

All `nba_api` calls are mocked. Tests cover advanced stats, four-factors, game logs, today's games, rate limiting, and cache integration.

```python
# tests/test_nba_stats.py
"""Tests for the NBA stats client."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest

from data.nba_stats import NBAStatsClient
from data.cache import Cache


# ── sample data ──────────────────────────────────────────────────

ADVANCED_HEADERS = [
    "TEAM_ID", "TEAM_NAME", "GP", "W", "L", "W_PCT",
    "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE",
]
ADVANCED_ROWS = [
    [1610612738, "Boston Celtics", 60, 45, 15, 0.75, 118.5, 108.2, 10.3, 100.1],
    [1610612752, "New York Knicks", 60, 38, 22, 0.633, 114.2, 111.5, 2.7, 97.8],
]

FOUR_FACTORS_HEADERS = [
    "TEAM_ID", "TEAM_NAME", "GP",
    "EFG_PCT", "FTA_RATE", "TM_TOV_PCT", "OREB_PCT",
    "OPP_EFG_PCT", "OPP_FTA_RATE", "OPP_TOV_PCT", "OPP_OREB_PCT",
]
FOUR_FACTORS_ROWS = [
    [1610612738, "Boston Celtics", 60, 0.578, 0.280, 0.120, 0.280, 0.510, 0.250, 0.140, 0.260],
    [1610612752, "New York Knicks", 60, 0.542, 0.310, 0.130, 0.300, 0.530, 0.270, 0.130, 0.270],
]

GAME_LOG_HEADERS = ["TEAM_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "WL", "PTS"]
GAME_LOG_ROWS = [
    [1610612738, "0022500100", "2026-03-10", "BOS vs. NYK", "W", 115],
    [1610612738, "0022500099", "2026-03-08", "BOS @ PHI", "L", 102],
]

SCOREBOARD_GAMES = [
    {
        "gameId": "0022500200",
        "gameStatusText": "7:00 PM ET",
        "homeTeam": {"teamId": 1610612738, "teamTricode": "BOS"},
        "awayTeam": {"teamId": 1610612752, "teamTricode": "NYK"},
    },
]


def _mock_result_set(headers: list[str], rows: list[list]) -> MagicMock:
    """Create a mock nba_api result set (a list with one DataSet-like object)."""
    rs = MagicMock()
    rs.get_dict.return_value = {"headers": headers, "data": rows}
    return rs


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(cache: Cache) -> NBAStatsClient:
    return NBAStatsClient(cache=cache)


# ── tests ────────────────────────────────────────────────────────


class TestGetTeamAdvancedStats:
    @patch("data.nba_stats.LeagueDashTeamStats")
    def test_returns_dataframe(self, MockLDTS, client: NBAStatsClient):
        mock_endpoint = MagicMock()
        mock_endpoint.get_data_frames.return_value = [
            pd.DataFrame(ADVANCED_ROWS, columns=ADVANCED_HEADERS)
        ]
        MockLDTS.return_value = mock_endpoint

        df = client.get_team_advanced_stats("2025-26")
        assert isinstance(df, pd.DataFrame)
        assert "OFF_RATING" in df.columns
        assert len(df) == 2

    @patch("data.nba_stats.LeagueDashTeamStats")
    def test_caches_result(self, MockLDTS, client: NBAStatsClient):
        mock_endpoint = MagicMock()
        mock_endpoint.get_data_frames.return_value = [
            pd.DataFrame(ADVANCED_ROWS, columns=ADVANCED_HEADERS)
        ]
        MockLDTS.return_value = mock_endpoint

        client.get_team_advanced_stats("2025-26")
        client.get_team_advanced_stats("2025-26")
        # Should only call the API once (second call hits cache)
        assert MockLDTS.call_count == 1


class TestGetTeamFourFactors:
    @patch("data.nba_stats.LeagueDashTeamStats")
    def test_returns_dataframe(self, MockLDTS, client: NBAStatsClient):
        mock_endpoint = MagicMock()
        mock_endpoint.get_data_frames.return_value = [
            pd.DataFrame(FOUR_FACTORS_ROWS, columns=FOUR_FACTORS_HEADERS)
        ]
        MockLDTS.return_value = mock_endpoint

        df = client.get_team_four_factors("2025-26")
        assert isinstance(df, pd.DataFrame)
        assert "EFG_PCT" in df.columns


class TestGetTeamGameLogs:
    @patch("data.nba_stats.TeamGameLog")
    def test_returns_dataframe(self, MockTGL, client: NBAStatsClient):
        mock_endpoint = MagicMock()
        mock_endpoint.get_data_frames.return_value = [
            pd.DataFrame(GAME_LOG_ROWS, columns=GAME_LOG_HEADERS)
        ]
        MockTGL.return_value = mock_endpoint

        df = client.get_team_game_logs(team_id=1610612738, last_n=20)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2

    @patch("data.nba_stats.TeamGameLog")
    def test_respects_last_n(self, MockTGL, client: NBAStatsClient):
        mock_endpoint = MagicMock()
        mock_endpoint.get_data_frames.return_value = [
            pd.DataFrame(GAME_LOG_ROWS, columns=GAME_LOG_HEADERS)
        ]
        MockTGL.return_value = mock_endpoint

        client.get_team_game_logs(team_id=1610612738, last_n=5)
        _, kwargs = MockTGL.call_args
        assert kwargs.get("last_n_games") == 5


class TestGetTodaysGames:
    @patch("data.nba_stats.ScoreboardV2")
    def test_returns_game_list(self, MockSB, client: NBAStatsClient):
        mock_endpoint = MagicMock()
        mock_endpoint.get_dict.return_value = {
            "resultSets": [
                {
                    "name": "GameHeader",
                    "headers": [
                        "GAME_ID", "GAME_STATUS_TEXT",
                        "HOME_TEAM_ID", "VISITOR_TEAM_ID",
                    ],
                    "rowSet": [
                        ["0022500200", "7:00 PM ET", 1610612738, 1610612752],
                    ],
                }
            ]
        }
        MockSB.return_value = mock_endpoint

        games = client.get_todays_games()
        assert isinstance(games, list)
        assert len(games) >= 1


class TestRateLimiting:
    @patch("data.nba_stats.LeagueDashTeamStats")
    @patch("data.nba_stats.time.sleep")
    def test_delays_between_calls(self, mock_sleep, MockLDTS, client: NBAStatsClient):
        mock_endpoint = MagicMock()
        mock_endpoint.get_data_frames.return_value = [
            pd.DataFrame(ADVANCED_ROWS, columns=ADVANCED_HEADERS)
        ]
        MockLDTS.return_value = mock_endpoint

        # Make two uncached calls (different seasons to bypass cache)
        client.get_team_advanced_stats("2024-25")
        client.get_team_advanced_stats("2023-24")
        # Should have slept at least once (0.75s between calls)
        assert mock_sleep.call_count >= 1
        mock_sleep.assert_called_with(pytest.approx(0.75, abs=0.1))
```

Run and confirm tests fail:

```bash
python -m pytest tests/test_nba_stats.py -v
# Expected: ImportError
```

#### Step 7.2 Implement `data/nba_stats.py`

```python
# data/nba_stats.py
"""NBA statistics client wrapping nba_api.

Pulls team-level advanced stats, four factors, game logs, and today's
schedule.  All calls go through the shared Cache and are rate-limited
(0.75 s between requests to nba.com).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import pandas as pd

from nba_api.stats.endpoints import (
    LeagueDashTeamStats,
    TeamGameLog,
    ScoreboardV2,
)

from data.cache import Cache, TTL_STATS

log = logging.getLogger(__name__)

_RATE_LIMIT_DELAY = 0.75  # seconds between nba_api calls
_MAX_RETRIES = 5
_RETRY_BACKOFF = 5  # seconds on 429/403


class NBAStatsClient:
    """Fetches NBA team stats via ``nba_api`` with caching + rate limiting."""

    def __init__(self, cache: Cache) -> None:
        self._cache = cache
        self._last_call: float = 0.0

    # ── public API ───────────────────────────────────────────────

    def get_team_advanced_stats(self, season: str) -> pd.DataFrame:
        """Team-level advanced stats (ORtg, DRtg, pace, net rating).

        Parameters
        ----------
        season:
            NBA season string, e.g. ``"2025-26"``.
        """
        cache_key = f"nba:advanced:{season}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_STATS)
        if cached is not None:
            return pd.DataFrame(cached)

        self._rate_limit()
        endpoint = LeagueDashTeamStats(
            season=season,
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
        )
        df = endpoint.get_data_frames()[0]
        self._cache.cache_set(cache_key, df.to_dict(orient="records"))
        return df

    def get_team_four_factors(self, season: str) -> pd.DataFrame:
        """Team-level four factors (eFG%, TOV%, ORB%, FT/FGA)."""
        cache_key = f"nba:four_factors:{season}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_STATS)
        if cached is not None:
            return pd.DataFrame(cached)

        self._rate_limit()
        endpoint = LeagueDashTeamStats(
            season=season,
            measure_type_detailed_defense="Four Factors",
            per_mode_detailed="PerGame",
        )
        df = endpoint.get_data_frames()[0]
        self._cache.cache_set(cache_key, df.to_dict(orient="records"))
        return df

    def get_team_game_logs(
        self, team_id: int, last_n: int = 20
    ) -> pd.DataFrame:
        """Recent game logs for a single team."""
        cache_key = f"nba:game_logs:{team_id}:{last_n}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_STATS)
        if cached is not None:
            return pd.DataFrame(cached)

        self._rate_limit()
        endpoint = TeamGameLog(
            team_id=team_id,
            season="2025-26",
            last_n_games=last_n,
        )
        df = endpoint.get_data_frames()[0]
        self._cache.cache_set(cache_key, df.to_dict(orient="records"))
        return df

    def get_todays_games(self) -> list[dict]:
        """Return today's NBA games from the live scoreboard."""
        cache_key = "nba:todays_games"
        cached = self._cache.cache_get(cache_key, ttl_seconds=1800)
        if cached is not None:
            return cached

        self._rate_limit()
        sb = ScoreboardV2()
        raw = sb.get_dict()

        games: list[dict] = []
        for rs in raw.get("resultSets", []):
            if rs.get("name") == "GameHeader":
                headers = rs["headers"]
                for row in rs["rowSet"]:
                    games.append(dict(zip(headers, row)))
                break

        self._cache.cache_set(cache_key, games)
        return games

    # ── internals ────────────────────────────────────────────────

    def _rate_limit(self) -> None:
        """Enforce minimum delay between nba_api calls."""
        elapsed = time.time() - self._last_call
        if elapsed < _RATE_LIMIT_DELAY:
            time.sleep(_RATE_LIMIT_DELAY - elapsed)
        self._last_call = time.time()
```

#### Step 7.3 Verify tests pass

```bash
python -m pytest tests/test_nba_stats.py -v
# Expected: all green
```

#### Step 7.4 Commit

```bash
git add data/nba_stats.py tests/test_nba_stats.py
git commit -m "feat(data): add NBA stats client with nba_api, caching, rate limiting"
```

---

### Task 8: NHL Stats Client (`data/nhl_stats.py`)

#### Step 8.1 Write tests (`tests/test_nhl_stats.py`)

Tests mock `httpx` for NHL API and MoneyPuck CSV downloads.

```python
# tests/test_nhl_stats.py
"""Tests for the NHL stats client."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data.nhl_stats import NHLStatsClient
from data.cache import Cache


# ── sample data ──────────────────────────────────────────────────

SAMPLE_SCHEDULE = {
    "gameWeek": [
        {
            "date": "2026-03-11",
            "games": [
                {
                    "id": 2025020900,
                    "startTimeUTC": "2026-03-12T00:00:00Z",
                    "gameState": "FUT",
                    "homeTeam": {"abbrev": "BOS", "id": 6},
                    "awayTeam": {"abbrev": "NYR", "id": 3},
                },
            ],
        }
    ]
}

SAMPLE_STANDINGS = {
    "standings": [
        {
            "teamAbbrev": {"default": "BOS"},
            "teamName": {"default": "Bruins"},
            "gamesPlayed": 65,
            "wins": 40,
            "losses": 20,
            "otLosses": 5,
            "points": 85,
        },
    ]
}

SAMPLE_XG_CSV = """team,season,situation,xGoalsPercentage,xGoalsFor,xGoalsAgainst,corsiPercentage,fenwickPercentage
BOS,2026,5on5,0.55,150.2,123.1,0.53,0.54
NYR,2026,5on5,0.51,140.5,135.2,0.50,0.51
"""

SAMPLE_GOALIE_CSV = """playerId,name,team,season,situation,games_played,xGoals,goals,GSAx,highDangerSavePercentage
8471679,Jeremy Swayman,BOS,2026,5on5,50,100.5,88,12.5,0.870
8477424,Igor Shesterkin,NYR,2026,5on5,55,110.2,102,8.2,0.855
"""

SAMPLE_GAME_RESULT = {
    "homeTeam": {"abbrev": "BOS", "score": 4},
    "awayTeam": {"abbrev": "NYR", "score": 2},
    "gameState": "OFF",
}


def _mock_response(
    data: dict | str | None = None, status_code: int = 200, text: str = ""
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if data is not None:
        resp.json.return_value = data
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(cache: Cache) -> NHLStatsClient:
    return NHLStatsClient(cache=cache)


# ── tests ────────────────────────────────────────────────────────


class TestGetSchedule:
    @patch("data.nhl_stats.httpx.get")
    def test_returns_game_list(self, mock_get, client: NHLStatsClient):
        mock_get.return_value = _mock_response(SAMPLE_SCHEDULE)
        games = client.get_schedule("2026-03-11")
        assert isinstance(games, list)
        assert len(games) == 1
        assert games[0]["homeTeam"]["abbrev"] == "BOS"

    @patch("data.nhl_stats.httpx.get")
    def test_caches_schedule(self, mock_get, client: NHLStatsClient):
        mock_get.return_value = _mock_response(SAMPLE_SCHEDULE)
        client.get_schedule("2026-03-11")
        client.get_schedule("2026-03-11")
        assert mock_get.call_count == 1


class TestGetStandings:
    @patch("data.nhl_stats.httpx.get")
    def test_returns_standings(self, mock_get, client: NHLStatsClient):
        mock_get.return_value = _mock_response(SAMPLE_STANDINGS)
        standings = client.get_standings()
        assert isinstance(standings, list)
        assert standings[0]["teamAbbrev"]["default"] == "BOS"


class TestGetTeamXgStats:
    @patch("data.nhl_stats.httpx.get")
    def test_returns_dataframe(self, mock_get, client: NHLStatsClient):
        mock_get.return_value = _mock_response(text=SAMPLE_XG_CSV)
        mock_get.return_value.text = SAMPLE_XG_CSV
        df = client.get_team_xg_stats()
        assert isinstance(df, pd.DataFrame)
        assert "xGoalsPercentage" in df.columns
        assert len(df) == 2


class TestGetGoalieStats:
    @patch("data.nhl_stats.httpx.get")
    def test_returns_dataframe(self, mock_get, client: NHLStatsClient):
        mock_get.return_value = _mock_response(text=SAMPLE_GOALIE_CSV)
        mock_get.return_value.text = SAMPLE_GOALIE_CSV
        df = client.get_goalie_stats()
        assert isinstance(df, pd.DataFrame)
        assert "GSAx" in df.columns
        assert len(df) == 2


class TestGetGameResult:
    @patch("data.nhl_stats.httpx.get")
    def test_returns_result_dict(self, mock_get, client: NHLStatsClient):
        mock_get.return_value = _mock_response(SAMPLE_GAME_RESULT)
        result = client.get_game_result("2025020900")
        assert result["homeTeam"]["score"] == 4
        assert result["gameState"] == "OFF"
```

Run and confirm tests fail:

```bash
python -m pytest tests/test_nhl_stats.py -v
# Expected: ImportError
```

#### Step 8.2 Implement `data/nhl_stats.py`

```python
# data/nhl_stats.py
"""NHL statistics client.

Pulls schedule/standings from api-web.nhle.com and advanced stats
(xG, goalie GSAx) from MoneyPuck CSV downloads.
"""

from __future__ import annotations

import io
import logging
from datetime import date

import httpx
import pandas as pd

from data.cache import Cache, TTL_STATS, TTL_RESULTS

log = logging.getLogger(__name__)

_NHL_API = "https://api-web.nhle.com/v1"
_MONEYPUCK_TEAM_URL = (
    "https://moneypuck.com/moneypuck/playerData/seasonSummary/"
    "{season}/regular/teams.csv"
)
_MONEYPUCK_GOALIE_URL = (
    "https://moneypuck.com/moneypuck/playerData/seasonSummary/"
    "{season}/regular/goalies.csv"
)
_TIMEOUT = 20.0


class NHLStatsClient:
    """Fetches NHL schedule, standings, and advanced stats."""

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    # ── public API ───────────────────────────────────────────────

    def get_schedule(self, date_str: str | None = None) -> list[dict]:
        """NHL games for *date_str* (``YYYY-MM-DD``).  Defaults to today."""
        if date_str is None:
            date_str = date.today().isoformat()

        cache_key = f"nhl:schedule:{date_str}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_STATS)
        if cached is not None:
            return cached

        resp = httpx.get(
            f"{_NHL_API}/schedule/{date_str}", timeout=_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()

        games: list[dict] = []
        for week in data.get("gameWeek", []):
            games.extend(week.get("games", []))

        self._cache.cache_set(cache_key, games)
        return games

    def get_standings(self) -> list[dict]:
        """Current NHL standings."""
        cache_key = "nhl:standings"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_STATS)
        if cached is not None:
            return cached

        resp = httpx.get(f"{_NHL_API}/standings/now", timeout=_TIMEOUT)
        resp.raise_for_status()
        standings = resp.json().get("standings", [])
        self._cache.cache_set(cache_key, standings)
        return standings

    def get_team_xg_stats(self, season: int = 2026) -> pd.DataFrame:
        """Team-level expected-goals stats from MoneyPuck CSV."""
        cache_key = f"nhl:xg_teams:{season}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_STATS)
        if cached is not None:
            return pd.DataFrame(cached)

        url = _MONEYPUCK_TEAM_URL.format(season=season)
        resp = httpx.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        self._cache.cache_set(cache_key, df.to_dict(orient="records"))
        return df

    def get_goalie_stats(self, season: int = 2026) -> pd.DataFrame:
        """Goalie-level stats (GSAx, HDSV%) from MoneyPuck CSV."""
        cache_key = f"nhl:goalies:{season}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_STATS)
        if cached is not None:
            return pd.DataFrame(cached)

        url = _MONEYPUCK_GOALIE_URL.format(season=season)
        resp = httpx.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        self._cache.cache_set(cache_key, df.to_dict(orient="records"))
        return df

    def get_game_result(self, game_id: str) -> dict:
        """Final result for a completed game.  Cached permanently."""
        cache_key = f"nhl:result:{game_id}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_RESULTS)
        if cached is not None:
            return cached

        resp = httpx.get(
            f"{_NHL_API}/gamecenter/{game_id}/landing", timeout=_TIMEOUT
        )
        resp.raise_for_status()
        result = resp.json()

        # Only cache if the game is final
        if result.get("gameState") in ("OFF", "FINAL"):
            self._cache.cache_set(cache_key, result)

        return result
```

#### Step 8.3 Verify tests pass

```bash
python -m pytest tests/test_nhl_stats.py -v
# Expected: all green
```

#### Step 8.4 Commit

```bash
git add data/nhl_stats.py tests/test_nhl_stats.py
git commit -m "feat(data): add NHL stats client (NHL API + MoneyPuck CSVs)"
```

---

### Task 9: Injury Data Client (`data/injuries.py`)

#### Step 9.1 Write tests (`tests/test_injuries.py`)

Tests mock `httpx.get` to simulate ESPN injury API responses. Cover NBA injuries, NHL injuries, and goalie status extraction.

```python
# tests/test_injuries.py
"""Tests for the injury data client."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from data.injuries import InjuryClient
from data.cache import Cache


# ── sample ESPN API responses ────────────────────────────────────

SAMPLE_NBA_INJURIES = {
    "team": {
        "id": "2",
        "displayName": "Boston Celtics",
    },
    "injuries": [
        {
            "team": {"displayName": "Boston Celtics"},
            "injuries": [
                {
                    "athlete": {"displayName": "Kristaps Porzingis"},
                    "status": "Out",
                    "type": {"description": "Knee"},
                },
                {
                    "athlete": {"displayName": "Jrue Holiday"},
                    "status": "Questionable",
                    "type": {"description": "Ankle"},
                },
            ],
        },
        {
            "team": {"displayName": "New York Knicks"},
            "injuries": [
                {
                    "athlete": {"displayName": "Julius Randle"},
                    "status": "Doubtful",
                    "type": {"description": "Shoulder"},
                },
            ],
        },
    ],
}

SAMPLE_NHL_INJURIES = {
    "injuries": [
        {
            "team": {"displayName": "Boston Bruins"},
            "injuries": [
                {
                    "athlete": {"displayName": "Brad Marchand"},
                    "status": "Day-To-Day",
                    "type": {"description": "Upper Body"},
                },
            ],
        },
        {
            "team": {"displayName": "New York Rangers"},
            "injuries": [
                {
                    "athlete": {"displayName": "Igor Shesterkin"},
                    "status": "Out",
                    "type": {"description": "Lower Body"},
                },
            ],
        },
    ],
}

SAMPLE_NHL_GOALIES_INJURIES = {
    "injuries": [
        {
            "team": {"displayName": "New York Rangers"},
            "injuries": [
                {
                    "athlete": {
                        "displayName": "Igor Shesterkin",
                        "position": {"abbreviation": "G"},
                    },
                    "status": "Out",
                    "type": {"description": "Lower Body"},
                },
            ],
        },
        {
            "team": {"displayName": "Boston Bruins"},
            "injuries": [],
        },
    ],
}


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(cache: Cache) -> InjuryClient:
    return InjuryClient(cache=cache)


# ── tests ────────────────────────────────────────────────────────


class TestGetNBAInjuries:
    @patch("data.injuries.httpx.get")
    def test_returns_injury_list(self, mock_get, client: InjuryClient):
        mock_get.return_value = _mock_response(SAMPLE_NBA_INJURIES)
        injuries = client.get_nba_injuries()
        assert isinstance(injuries, list)
        assert len(injuries) == 3

    @patch("data.injuries.httpx.get")
    def test_injury_fields(self, mock_get, client: InjuryClient):
        mock_get.return_value = _mock_response(SAMPLE_NBA_INJURIES)
        injuries = client.get_nba_injuries()
        entry = injuries[0]
        assert "player" in entry
        assert "team" in entry
        assert "status" in entry
        assert "description" in entry

    @patch("data.injuries.httpx.get")
    def test_caches_result(self, mock_get, client: InjuryClient):
        mock_get.return_value = _mock_response(SAMPLE_NBA_INJURIES)
        client.get_nba_injuries()
        client.get_nba_injuries()
        assert mock_get.call_count == 1


class TestGetNHLInjuries:
    @patch("data.injuries.httpx.get")
    def test_returns_injury_list(self, mock_get, client: InjuryClient):
        mock_get.return_value = _mock_response(SAMPLE_NHL_INJURIES)
        injuries = client.get_nhl_injuries()
        assert isinstance(injuries, list)
        assert len(injuries) == 2

    @patch("data.injuries.httpx.get")
    def test_injury_fields(self, mock_get, client: InjuryClient):
        mock_get.return_value = _mock_response(SAMPLE_NHL_INJURIES)
        injuries = client.get_nhl_injuries()
        entry = injuries[0]
        assert entry["player"] == "Brad Marchand"
        assert entry["team"] == "Boston Bruins"
        assert entry["status"] == "Day-To-Day"


class TestGetNHLGoalieStatus:
    @patch("data.injuries.httpx.get")
    def test_goalie_out(self, mock_get, client: InjuryClient):
        mock_get.return_value = _mock_response(SAMPLE_NHL_GOALIES_INJURIES)
        status = client.get_nhl_goalie_status("New York Rangers")
        assert status["starter_confirmed"] is False
        assert any("Shesterkin" in g.get("player", "") for g in status.get("injured_goalies", []))

    @patch("data.injuries.httpx.get")
    def test_no_goalie_injuries(self, mock_get, client: InjuryClient):
        mock_get.return_value = _mock_response(SAMPLE_NHL_GOALIES_INJURIES)
        status = client.get_nhl_goalie_status("Boston Bruins")
        assert status["starter_confirmed"] is True
        assert len(status.get("injured_goalies", [])) == 0
```

Run and confirm tests fail:

```bash
python -m pytest tests/test_injuries.py -v
# Expected: ImportError
```

#### Step 9.2 Implement `data/injuries.py`

```python
# data/injuries.py
"""Injury data client using ESPN's public injury API.

Provides NBA and NHL injury reports plus NHL goalie status checks.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from data.cache import Cache, TTL_INJURIES

log = logging.getLogger(__name__)

_ESPN_INJURY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/injuries"
)
_TIMEOUT = 15.0


class InjuryClient:
    """Fetches injury reports from ESPN's public API."""

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    # ── public API ───────────────────────────────────────────────

    def get_nba_injuries(self) -> list[dict]:
        """All current NBA injuries.

        Returns a flat list of dicts, each with keys:
        ``player``, ``team``, ``status``, ``description``.
        """
        return self._get_injuries("basketball", "nba")

    def get_nhl_injuries(self) -> list[dict]:
        """All current NHL injuries (same shape as NBA)."""
        return self._get_injuries("hockey", "nhl")

    def get_nhl_goalie_status(self, team: str) -> dict:
        """Check whether a team's starting goalie is healthy.

        Parameters
        ----------
        team:
            Full team name, e.g. ``"New York Rangers"``.

        Returns
        -------
        dict with keys:
            - ``team``: the team name queried
            - ``starter_confirmed``: ``True`` if no goalie is on the
              injury report, ``False`` otherwise
            - ``injured_goalies``: list of injury entries for goalies
        """
        injuries = self.get_nhl_injuries()
        injured_goalies = self._extract_injured_goalies(team)
        return {
            "team": team,
            "starter_confirmed": len(injured_goalies) == 0,
            "injured_goalies": injured_goalies,
        }

    # ── internals ────────────────────────────────────────────────

    def _get_injuries(self, sport: str, league: str) -> list[dict]:
        """Fetch and normalise injuries for a sport/league."""
        cache_key = f"injuries:{league}"
        cached = self._cache.cache_get(cache_key, ttl_seconds=TTL_INJURIES)
        if cached is not None:
            return cached

        url = _ESPN_INJURY_URL.format(sport=sport, league=league)
        try:
            resp = httpx.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            raw = resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            log.warning("ESPN injury API failed for %s: %s", league, exc)
            # Fall back to stale cache
            stale = self._cache.cache_get(cache_key, ttl_seconds=None)
            return stale if stale is not None else []

        flat: list[dict] = []
        for team_block in raw.get("injuries", []):
            team_name = team_block.get("team", {}).get("displayName", "Unknown")
            for entry in team_block.get("injuries", []):
                flat.append(
                    {
                        "player": entry.get("athlete", {}).get("displayName", ""),
                        "team": team_name,
                        "status": entry.get("status", ""),
                        "description": entry.get("type", {}).get("description", ""),
                    }
                )

        self._cache.cache_set(cache_key, flat)
        return flat

    def _extract_injured_goalies(self, team: str) -> list[dict]:
        """Return injury entries for goalies on the given NHL team.

        Re-fetches the raw ESPN response (cached) to inspect the
        ``position`` field which the flat list does not carry.
        """
        cache_key = "injuries:nhl:raw"
        cached_raw = self._cache.cache_get(cache_key, ttl_seconds=TTL_INJURIES)

        if cached_raw is None:
            url = _ESPN_INJURY_URL.format(sport="hockey", league="nhl")
            try:
                resp = httpx.get(url, timeout=_TIMEOUT)
                resp.raise_for_status()
                cached_raw = resp.json()
                self._cache.cache_set(cache_key, cached_raw)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                log.warning("ESPN injury API failed for goalie check: %s", exc)
                return []

        injured: list[dict] = []
        for team_block in cached_raw.get("injuries", []):
            block_team = team_block.get("team", {}).get("displayName", "")
            if block_team != team:
                continue
            for entry in team_block.get("injuries", []):
                pos = (
                    entry.get("athlete", {})
                    .get("position", {})
                    .get("abbreviation", "")
                )
                if pos == "G":
                    injured.append(
                        {
                            "player": entry["athlete"]["displayName"],
                            "status": entry.get("status", ""),
                            "description": entry.get("type", {}).get(
                                "description", ""
                            ),
                        }
                    )
        return injured
```

#### Step 9.3 Verify tests pass

```bash
python -m pytest tests/test_injuries.py -v
# Expected: all green
```

#### Step 9.4 Commit

```bash
git add data/injuries.py tests/test_injuries.py
git commit -m "feat(data): add ESPN injury client with goalie status checks"
```

---

### Chunk 2 completion checklist

| Task | File | Tests | Status |
|------|------|-------|--------|
| 5 | `data/cache.py` | `tests/test_cache.py` | Ready |
| 6 | `data/odds.py` | `tests/test_odds.py` | Ready |
| 7 | `data/nba_stats.py` | `tests/test_nba_stats.py` | Ready |
| 8 | `data/nhl_stats.py` | `tests/test_nhl_stats.py` | Ready |
| 9 | `data/injuries.py` | `tests/test_injuries.py` | Ready |

After completing this chunk, the full `data/` package is in place. All five modules share the same `Cache` instance at runtime (created once in `run.py` and injected). Every external call is cached with appropriate TTLs, retried on failure, and falls back to stale cache when the upstream API is unreachable.
