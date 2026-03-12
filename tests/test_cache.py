"""Tests for the SQLite-backed cache layer."""
import json
import sqlite3
import time
from unittest.mock import patch

import pytest

from ladderbot.data.cache import (
    ODDS_TTL,
    STATS_TTL,
    INJURIES_TTL,
    cache_get,
    cache_set,
    cache_clear_expired,
)


@pytest.fixture
def db():
    """Provide an in-memory SQLite connection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


class TestConstants:
    def test_odds_ttl(self):
        assert ODDS_TTL == 1800

    def test_stats_ttl(self):
        assert STATS_TTL == 86400

    def test_injuries_ttl(self):
        assert INJURIES_TTL == 7200


class TestCacheSet:
    def test_stores_value(self, db):
        cache_set(db, "test_key", {"value": 42})
        row = db.execute("SELECT * FROM cache WHERE key = ?", ("test_key",)).fetchone()
        assert row is not None
        assert json.loads(row["data"]) == {"value": 42}
        assert row["created_at"] > 0

    def test_overwrites_existing_key(self, db):
        cache_set(db, "key1", {"v": 1})
        cache_set(db, "key1", {"v": 2})
        rows = db.execute("SELECT * FROM cache WHERE key = ?", ("key1",)).fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0]["data"]) == {"v": 2}

    def test_stores_complex_data(self, db):
        data = {
            "games": [{"id": 1, "teams": ["BOS", "MIL"]}],
            "count": 5,
            "nested": {"a": [1, 2, 3]},
        }
        cache_set(db, "complex", data)
        result = cache_get(db, "complex")
        assert result == data

    def test_creates_table_automatically(self, db):
        # Table shouldn't exist yet
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cache'"
        ).fetchall()
        assert len(tables) == 0

        cache_set(db, "auto", {"v": 1})

        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cache'"
        ).fetchall()
        assert len(tables) == 1


class TestCacheGet:
    def test_returns_cached_value(self, db):
        cache_set(db, "key1", {"value": "hello"})
        result = cache_get(db, "key1")
        assert result == {"value": "hello"}

    def test_returns_none_for_missing_key(self, db):
        result = cache_get(db, "nonexistent")
        assert result is None

    def test_returns_value_within_ttl(self, db):
        cache_set(db, "odds", {"line": -160})
        result = cache_get(db, "odds", ttl_seconds=ODDS_TTL)
        assert result == {"line": -160}

    def test_returns_none_when_expired(self, db):
        cache_set(db, "old", {"v": 1})
        # Manually set created_at to the past
        old_time = time.time() - 3600  # 1 hour ago
        db.execute("UPDATE cache SET created_at = ? WHERE key = ?", (old_time, "old"))
        db.commit()

        # With 30-minute TTL, should be expired
        result = cache_get(db, "old", ttl_seconds=ODDS_TTL)
        assert result is None

    def test_returns_value_when_no_ttl(self, db):
        cache_set(db, "permanent", {"v": 1})
        # Set created_at far in the past
        old_time = time.time() - 999999
        db.execute(
            "UPDATE cache SET created_at = ? WHERE key = ?", (old_time, "permanent")
        )
        db.commit()

        # No TTL = never expires
        result = cache_get(db, "permanent", ttl_seconds=None)
        assert result == {"v": 1}

    def test_ttl_boundary(self, db):
        cache_set(db, "boundary", {"v": 1})
        # Set created_at to exactly TTL seconds ago
        exact_time = time.time() - ODDS_TTL - 1  # 1 second past expiry
        db.execute(
            "UPDATE cache SET created_at = ? WHERE key = ?", (exact_time, "boundary")
        )
        db.commit()

        result = cache_get(db, "boundary", ttl_seconds=ODDS_TTL)
        assert result is None


class TestCacheClearExpired:
    def test_clears_old_entries(self, db):
        cache_set(db, "fresh", {"v": 1})
        cache_set(db, "stale", {"v": 2})

        # Make stale entry very old
        old_time = time.time() - STATS_TTL - 100
        db.execute(
            "UPDATE cache SET created_at = ? WHERE key = ?", (old_time, "stale")
        )
        db.commit()

        deleted = cache_clear_expired(db)
        assert deleted == 1

        # Fresh should still be there
        assert cache_get(db, "fresh") == {"v": 1}
        # Stale should be gone
        assert cache_get(db, "stale") is None

    def test_returns_zero_when_nothing_expired(self, db):
        cache_set(db, "new1", {"v": 1})
        cache_set(db, "new2", {"v": 2})
        deleted = cache_clear_expired(db)
        assert deleted == 0

    def test_clears_all_expired(self, db):
        old_time = time.time() - STATS_TTL - 100
        for i in range(5):
            cache_set(db, f"old_{i}", {"v": i})
            db.execute(
                "UPDATE cache SET created_at = ? WHERE key = ?", (old_time, f"old_{i}")
            )
        db.commit()

        deleted = cache_clear_expired(db)
        assert deleted == 5

    def test_empty_cache_returns_zero(self, db):
        deleted = cache_clear_expired(db)
        assert deleted == 0


class TestCacheTableCreation:
    def test_get_creates_table(self, db):
        # Calling get on empty DB should create the table without error
        result = cache_get(db, "anything")
        assert result is None

    def test_clear_creates_table(self, db):
        deleted = cache_clear_expired(db)
        assert deleted == 0
