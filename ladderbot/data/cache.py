"""SQLite-backed cache layer for LadderBot.

Provides key-value caching with TTL support for all API responses.
Uses a dedicated `cache` table with automatic expiration.
"""
import json
import sqlite3
import time

# TTL constants (seconds)
ODDS_TTL = 1800        # 30 minutes
STATS_TTL = 86400      # 24 hours
INJURIES_TTL = 7200    # 2 hours

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at REAL NOT NULL
)
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Create the cache table if it doesn't exist."""
    conn.execute(_CREATE_TABLE_SQL)
    conn.commit()


def cache_get(
    conn: sqlite3.Connection,
    key: str,
    ttl_seconds: int | None = None,
) -> dict | None:
    """Retrieve a cached value by key.

    Args:
        conn: SQLite database connection.
        key: Cache key string.
        ttl_seconds: Maximum age in seconds. If None, no expiration check.

    Returns:
        The cached dict, or None if not found or expired.
    """
    _ensure_table(conn)
    row = conn.execute(
        "SELECT data, created_at FROM cache WHERE key = ?", (key,)
    ).fetchone()

    if row is None:
        return None

    # Check TTL
    if ttl_seconds is not None:
        age = time.time() - row[1]
        if age > ttl_seconds:
            return None

    return json.loads(row[0])


def cache_set(conn: sqlite3.Connection, key: str, data: dict) -> None:
    """Store a value in the cache.

    Args:
        conn: SQLite database connection.
        key: Cache key string.
        data: Dictionary to cache (must be JSON-serializable).
    """
    _ensure_table(conn)
    conn.execute(
        """
        INSERT INTO cache (key, data, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            data = excluded.data,
            created_at = excluded.created_at
        """,
        (key, json.dumps(data), time.time()),
    )
    conn.commit()


def cache_clear_expired(conn: sqlite3.Connection) -> int:
    """Remove all expired entries from the cache.

    Uses the maximum TTL (STATS_TTL = 24h) as the expiration threshold.
    Entries older than STATS_TTL are considered expired regardless of type.

    Returns:
        Number of rows deleted.
    """
    _ensure_table(conn)
    cutoff = time.time() - STATS_TTL
    cursor = conn.execute(
        "DELETE FROM cache WHERE created_at < ?", (cutoff,)
    )
    conn.commit()
    return cursor.rowcount
