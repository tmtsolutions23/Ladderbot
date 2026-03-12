## Chunk 1: Foundation

This chunk establishes the project skeleton, odds math library, database layer, and configuration system. Every subsequent chunk depends on these.

---

### Task 1: Project Scaffolding

**Goal**: Create the directory structure, dependency manifest, example config, and gitignore so that `pip install -e .` works immediately.

#### Step 1.1: Create `pyproject.toml`

```python
# File: pyproject.toml
```

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "ladderbot"
version = "0.1.0"
description = "Sports betting parlay ladder tool for NBA and NHL"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "httpx>=0.25.0",
    "pyyaml>=6.0",
    "numpy>=1.25.0",
    "scipy>=1.11.0",
    "scikit-learn>=1.3.0",
    "pandas>=2.1.0",
    "nba_api>=1.4.1",
    "schedule>=1.2.0",
    "jinja2>=3.1.0",
    "sse-starlette>=1.6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
]

[tool.setuptools.packages.find]
include = ["ladderbot*"]

[project.scripts]
ladderbot = "ladderbot.run:main"
```

#### Step 1.2: Create `config.example.yaml`

```yaml
# File: config.example.yaml

# API Keys
odds_api_key: "your-key-here"

# Discord
discord_webhook_url: "https://discord.com/api/webhooks/..."

# Ladder Settings
ladder:
  starting_amount: 10.00
  target_amount: 1000.00
  max_attempts: 50

# Parlay Settings
parlay:
  min_legs: 2
  max_legs: 2
  target_odds_min: 150
  target_odds_max: 300
  min_edge_per_leg: 0.02
  min_edge_cold_start: 0.03

# Model Settings
model:
  rolling_window: 20
  use_xgboost: false
  cold_start_games: 20

# Sports
sports:
  nba: true
  nhl: true

# Schedule
run_time: "11:00"
pre_game_refresh: 120
scheduler: "manual"
```

#### Step 1.3: Create `.gitignore`

```gitignore
# File: .gitignore
data/*.db
config.yaml
__pycache__/
*.pyc
.env
*.egg-info/
dist/
build/
.pytest_cache/
```

#### Step 1.4: Create directory structure and `__init__.py` files

Run these commands:

```bash
mkdir -p ladderbot/data
mkdir -p ladderbot/models
mkdir -p ladderbot/parlay
mkdir -p ladderbot/alerts
mkdir -p ladderbot/tracking
mkdir -p ladderbot/web/routes
mkdir -p ladderbot/web/static
mkdir -p ladderbot/db
mkdir -p ladderbot/utils
mkdir -p tests
mkdir -p data
```

Create empty `__init__.py` in each package:

```bash
touch ladderbot/__init__.py
touch ladderbot/data/__init__.py
touch ladderbot/models/__init__.py
touch ladderbot/parlay/__init__.py
touch ladderbot/alerts/__init__.py
touch ladderbot/tracking/__init__.py
touch ladderbot/web/__init__.py
touch ladderbot/web/routes/__init__.py
touch ladderbot/db/__init__.py
touch ladderbot/utils/__init__.py
touch tests/__init__.py
```

Create a placeholder `ladderbot/run.py`:

```python
# File: ladderbot/run.py
"""LadderBot entry point."""


def main():
    print("LadderBot v0.1.0 — run 'python run.py --help' for usage")


if __name__ == "__main__":
    main()
```

#### Step 1.5: Verify

```bash
pip install -e ".[dev]"
python -c "import ladderbot; print('OK')"
```

#### Step 1.6: Commit

```bash
git init
git add pyproject.toml config.example.yaml .gitignore ladderbot/ tests/ data/
git commit -m "scaffold: project structure, dependencies, example config"
```

---

### Task 2: Odds Math Utilities

**Goal**: A pure-math module with zero external dependencies (beyond stdlib) that handles all odds conversions, edge calculations, and confidence classification. This is the most heavily reused module in the project.

#### Step 2.1: Write tests first

```python
# File: tests/test_odds.py
"""Tests for odds math utilities."""
import pytest
from ladderbot.utils.odds import (
    american_to_decimal,
    decimal_to_american,
    implied_probability,
    parlay_decimal_odds,
    parlay_american_odds,
    calculate_edge,
    classify_confidence,
    ladder_steps_needed,
)


class TestAmericanToDecimal:
    def test_positive_odds(self):
        assert american_to_decimal(200) == pytest.approx(3.0)

    def test_negative_odds(self):
        assert american_to_decimal(-150) == pytest.approx(2.6667, rel=1e-3)

    def test_even_money_positive(self):
        assert american_to_decimal(100) == pytest.approx(2.0)

    def test_heavy_favorite(self):
        assert american_to_decimal(-300) == pytest.approx(1.3333, rel=1e-3)

    def test_big_underdog(self):
        assert american_to_decimal(500) == pytest.approx(6.0)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            american_to_decimal(0)


class TestDecimalToAmerican:
    def test_positive_american(self):
        assert decimal_to_american(3.0) == 200

    def test_negative_american(self):
        assert decimal_to_american(1.5) == -200

    def test_even_money(self):
        assert decimal_to_american(2.0) == 100

    def test_heavy_favorite(self):
        assert decimal_to_american(1.25) == -400

    def test_below_one_raises(self):
        with pytest.raises(ValueError):
            decimal_to_american(0.9)

    def test_exactly_one_raises(self):
        with pytest.raises(ValueError):
            decimal_to_american(1.0)


class TestImpliedProbability:
    def test_even_money(self):
        assert implied_probability(100) == pytest.approx(0.5)

    def test_favorite(self):
        # -200 implies 200/(200+100) = 66.67%
        assert implied_probability(-200) == pytest.approx(0.6667, rel=1e-3)

    def test_underdog(self):
        # +200 implies 100/(200+100) = 33.33%
        assert implied_probability(200) == pytest.approx(0.3333, rel=1e-3)

    def test_heavy_favorite(self):
        # -400 implies 400/500 = 80%
        assert implied_probability(-400) == pytest.approx(0.8)

    def test_slight_underdog(self):
        # +110 implies 100/210 = 47.62%
        assert implied_probability(110) == pytest.approx(0.4762, rel=1e-3)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            implied_probability(0)


class TestParlayDecimalOdds:
    def test_two_legs(self):
        # 1.625 * 2.20 = 3.575
        assert parlay_decimal_odds([1.625, 2.20]) == pytest.approx(3.575)

    def test_three_legs(self):
        assert parlay_decimal_odds([2.0, 2.0, 2.0]) == pytest.approx(8.0)

    def test_single_leg(self):
        assert parlay_decimal_odds([3.0]) == pytest.approx(3.0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parlay_decimal_odds([])


class TestParlayAmericanOdds:
    def test_two_positive_legs(self):
        # -160 (1.625) * +120 (2.20) = 3.575 -> +257 (rounded)
        result = parlay_american_odds([-160, 120])
        assert result == 258  # (3.575 - 1) * 100 = 257.5 -> round to 258

    def test_two_favorites(self):
        # -150 (1.667) * -130 (1.769) = 2.949 -> +195
        result = parlay_american_odds([-150, -130])
        assert result == 195

    def test_zero_leg_raises(self):
        with pytest.raises(ValueError):
            parlay_american_odds([0, 100])


class TestCalculateEdge:
    def test_positive_edge(self):
        # Model says 64%, book implies 61.5% (-160)
        edge = calculate_edge(0.642, -160)
        # implied_prob(-160) = 160/260 = 0.6154
        assert edge == pytest.approx(0.0266, rel=1e-2)

    def test_negative_edge(self):
        # Model says 40%, book implies 50% (+100)
        edge = calculate_edge(0.40, 100)
        assert edge == pytest.approx(-0.10, rel=1e-2)

    def test_zero_edge(self):
        # Model says 50%, book implies 50% (+100)
        edge = calculate_edge(0.50, 100)
        assert edge == pytest.approx(0.0)


class TestClassifyConfidence:
    def test_low(self):
        assert classify_confidence(0.025, cold_start=False) == "LOW"

    def test_medium(self):
        assert classify_confidence(0.04, cold_start=False) == "MEDIUM"

    def test_high(self):
        assert classify_confidence(0.06, cold_start=False) == "HIGH"

    def test_boundary_low_medium(self):
        assert classify_confidence(0.03, cold_start=False) == "MEDIUM"

    def test_boundary_medium_high(self):
        assert classify_confidence(0.05, cold_start=False) == "HIGH"

    def test_cold_start_caps_at_medium(self):
        # Even 8% edge should be capped at MEDIUM during cold start
        assert classify_confidence(0.08, cold_start=True) == "MEDIUM"

    def test_cold_start_low_stays_low(self):
        assert classify_confidence(0.025, cold_start=True) == "LOW"

    def test_below_threshold(self):
        assert classify_confidence(0.01, cold_start=False) == "LOW"


class TestLadderStepsNeeded:
    def test_standard_ladder(self):
        # $10 -> $1000 at +225 (3.25 decimal)
        # ceil(log(1000/10) / log(3.25)) = ceil(4.612/1.179) = ceil(3.912) = 4
        assert ladder_steps_needed(10.0, 1000.0, 3.25) == 4

    def test_even_money(self):
        # $10 -> $1000 at 2.0 decimal
        # ceil(log(100) / log(2)) = ceil(6.644) = 7
        assert ladder_steps_needed(10.0, 1000.0, 2.0) == 7

    def test_already_at_target(self):
        assert ladder_steps_needed(1000.0, 1000.0, 3.0) == 0

    def test_above_target(self):
        assert ladder_steps_needed(1500.0, 1000.0, 3.0) == 0

    def test_one_step(self):
        # $500 -> $1000 at 3.0 decimal -> ceil(log(2)/log(3)) = ceil(0.631) = 1
        assert ladder_steps_needed(500.0, 1000.0, 3.0) == 1

    def test_odds_of_one_raises(self):
        with pytest.raises(ValueError):
            ladder_steps_needed(10.0, 1000.0, 1.0)
```

#### Step 2.2: Verify tests fail

```bash
pytest tests/test_odds.py -v
# Expected: ModuleNotFoundError — ladderbot.utils.odds does not exist yet
```

#### Step 2.3: Implement `ladderbot/utils/odds.py`

```python
# File: ladderbot/utils/odds.py
"""Odds math utilities for LadderBot.

All conversions follow standard sportsbook conventions:
- American odds: +200 means $200 profit on $100 bet; -200 means bet $200 to profit $100
- Decimal odds: total return per $1 bet (includes stake); always > 1.0
- Implied probability: 1 / decimal_odds (no-vig single-outcome probability)
"""
import math


def american_to_decimal(american: int) -> float:
    """Convert American odds to decimal odds.

    Args:
        american: American odds (e.g., -160, +200). Must not be 0.

    Returns:
        Decimal odds (always > 1.0).

    Raises:
        ValueError: If american is 0.
    """
    if american == 0:
        raise ValueError("American odds cannot be 0")
    if american > 0:
        return 1 + american / 100
    else:
        return 1 + 100 / abs(american)


def decimal_to_american(decimal: float) -> int:
    """Convert decimal odds to American odds.

    Args:
        decimal: Decimal odds (must be > 1.0).

    Returns:
        American odds as integer (rounded).

    Raises:
        ValueError: If decimal <= 1.0.
    """
    if decimal <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {decimal}")
    if decimal >= 2.0:
        return round((decimal - 1) * 100)
    else:
        return round(-100 / (decimal - 1))


def implied_probability(american: int) -> float:
    """Convert American odds to implied probability (no-vig).

    Args:
        american: American odds. Must not be 0.

    Returns:
        Probability between 0 and 1.

    Raises:
        ValueError: If american is 0.
    """
    if american == 0:
        raise ValueError("American odds cannot be 0")
    if american > 0:
        return 100 / (american + 100)
    else:
        return abs(american) / (abs(american) + 100)


def parlay_decimal_odds(legs: list[float]) -> float:
    """Calculate combined parlay decimal odds by multiplying legs.

    Args:
        legs: List of decimal odds for each leg.

    Returns:
        Combined decimal odds.

    Raises:
        ValueError: If legs is empty.
    """
    if not legs:
        raise ValueError("Must provide at least one leg")
    result = 1.0
    for leg in legs:
        result *= leg
    return result


def parlay_american_odds(legs: list[int]) -> int:
    """Calculate combined parlay American odds from individual American legs.

    Converts each leg to decimal, multiplies, converts back to American.

    Args:
        legs: List of American odds for each leg.

    Returns:
        Combined American odds as integer.

    Raises:
        ValueError: If any leg is 0 or legs is empty.
    """
    if not legs:
        raise ValueError("Must provide at least one leg")
    decimal_legs = [american_to_decimal(leg) for leg in legs]
    combined = parlay_decimal_odds(decimal_legs)
    return decimal_to_american(combined)


def calculate_edge(model_prob: float, book_odds: int) -> float:
    """Calculate edge: model probability minus book implied probability.

    Args:
        model_prob: Model's predicted probability (0 to 1).
        book_odds: Book's American odds for the outcome.

    Returns:
        Edge as a float (e.g., 0.05 = 5% edge).
    """
    book_prob = implied_probability(book_odds)
    return model_prob - book_prob


def classify_confidence(edge: float, cold_start: bool) -> str:
    """Classify edge into LOW / MEDIUM / HIGH confidence.

    Thresholds:
        LOW:    edge < 3.0%
        MEDIUM: 3.0% <= edge < 5.0%
        HIGH:   edge >= 5.0%

    During cold start, HIGH is capped at MEDIUM.

    Args:
        edge: Edge as a float (e.g., 0.05 = 5%).
        cold_start: Whether the model is in cold-start mode.

    Returns:
        One of "LOW", "MEDIUM", "HIGH".
    """
    if edge < 0.03:
        return "LOW"
    elif edge < 0.05:
        return "MEDIUM"
    else:
        if cold_start:
            return "MEDIUM"
        return "HIGH"


def ladder_steps_needed(start: float, target: float, decimal_odds: float) -> int:
    """Calculate number of consecutive wins needed to reach target from start.

    Uses: ceil(log(target / start) / log(decimal_odds))

    Args:
        start: Starting bankroll.
        target: Target bankroll.
        decimal_odds: Decimal odds per step.

    Returns:
        Number of steps needed (0 if already at or above target).

    Raises:
        ValueError: If decimal_odds <= 1.0.
    """
    if decimal_odds <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {decimal_odds}")
    if start >= target:
        return 0
    return math.ceil(math.log(target / start) / math.log(decimal_odds))
```

#### Step 2.4: Verify tests pass

```bash
pytest tests/test_odds.py -v
# Expected: all 30+ tests pass
```

#### Step 2.5: Commit

```bash
git add ladderbot/utils/odds.py tests/test_odds.py
git commit -m "feat: odds math utilities with full test coverage"
```

---

### Task 3: Database Schema and Manager

**Goal**: Define the SQLite schema matching the spec (with FanDuel web-dashboard columns) and a database manager that auto-creates the DB and provides CRUD helpers.

#### Step 3.1: Write tests first

```python
# File: tests/test_database.py
"""Tests for the database manager."""
import os
import sqlite3
import tempfile
from datetime import datetime, date

import pytest
from ladderbot.db.database import (
    get_db,
    insert_game,
    insert_odds_snapshot,
    insert_prediction,
    insert_parlay,
    update_parlay_placed,
    update_parlay_result,
    get_ladder_state,
    insert_ladder_state,
    insert_flat_bet,
    get_active_ladder,
)


@pytest.fixture
def db_path(tmp_path):
    """Provide a temporary database path."""
    return str(tmp_path / "test_ladderbot.db")


@pytest.fixture
def db(db_path):
    """Provide an initialized database connection."""
    conn = get_db(db_path)
    yield conn
    conn.close()


class TestGetDb:
    def test_creates_database_file(self, db_path):
        conn = get_db(db_path)
        assert os.path.exists(db_path)
        conn.close()

    def test_creates_all_tables(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        expected = {
            "games",
            "odds_snapshots",
            "model_predictions",
            "picks",
            "parlays",
            "ladder_state",
            "flat_bets",
            "team_stats",
            "goalie_confirmations",
        }
        assert expected.issubset(tables)

    def test_idempotent_schema(self, db_path):
        """Calling get_db twice should not raise or duplicate tables."""
        conn1 = get_db(db_path)
        conn1.close()
        conn2 = get_db(db_path)
        cursor = conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        # No duplicates
        assert len(tables) == len(set(tables))
        conn2.close()


class TestInsertGame:
    def test_insert_and_retrieve(self, db):
        insert_game(
            db,
            game_id="nba_20260311_BOS_MIL",
            sport="nba",
            home_team="BOS",
            away_team="MIL",
            game_date="2026-03-11",
        )
        row = db.execute(
            "SELECT * FROM games WHERE game_id = ?",
            ("nba_20260311_BOS_MIL",),
        ).fetchone()
        assert row is not None
        assert row["sport"] == "nba"
        assert row["home_team"] == "BOS"
        assert row["away_team"] == "MIL"
        assert row["status"] == "scheduled"

    def test_upsert_updates_score(self, db):
        insert_game(
            db,
            game_id="nba_20260311_BOS_MIL",
            sport="nba",
            home_team="BOS",
            away_team="MIL",
            game_date="2026-03-11",
        )
        insert_game(
            db,
            game_id="nba_20260311_BOS_MIL",
            sport="nba",
            home_team="BOS",
            away_team="MIL",
            game_date="2026-03-11",
            home_score=112,
            away_score=105,
            status="final",
        )
        row = db.execute(
            "SELECT * FROM games WHERE game_id = ?",
            ("nba_20260311_BOS_MIL",),
        ).fetchone()
        assert row["home_score"] == 112
        assert row["status"] == "final"


class TestInsertOddsSnapshot:
    def test_insert_and_retrieve(self, db):
        insert_odds_snapshot(
            db,
            game_id="nba_20260311_BOS_MIL",
            bookmaker="draftkings",
            market="h2h",
            outcome="BOS",
            price=-160,
        )
        rows = db.execute(
            "SELECT * FROM odds_snapshots WHERE game_id = ?",
            ("nba_20260311_BOS_MIL",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["price"] == -160
        assert rows[0]["bookmaker"] == "draftkings"


class TestInsertPrediction:
    def test_insert_and_retrieve(self, db):
        insert_prediction(
            db,
            game_id="nba_20260311_BOS_MIL",
            market="h2h",
            outcome="BOS",
            model_prob=0.642,
            book_prob=0.615,
            edge=0.027,
        )
        row = db.execute(
            "SELECT * FROM model_predictions WHERE game_id = ?",
            ("nba_20260311_BOS_MIL",),
        ).fetchone()
        assert row is not None
        assert abs(row["model_prob"] - 0.642) < 0.001


class TestParlayOperations:
    def test_insert_parlay(self, db):
        parlay_id = insert_parlay(
            db,
            leg1_pick_id=1,
            leg2_pick_id=2,
            combined_odds=257,
            combined_edge=0.048,
        )
        assert parlay_id is not None
        row = db.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()
        assert row["combined_odds"] == 257

    def test_update_placed(self, db):
        parlay_id = insert_parlay(
            db,
            leg1_pick_id=1,
            leg2_pick_id=2,
            combined_odds=257,
            combined_edge=0.048,
        )
        update_parlay_placed(
            db,
            parlay_id=parlay_id,
            fd_leg1_odds=-155,
            fd_leg2_odds=115,
            fd_parlay_odds=245,
            fd_edge=0.041,
            actual_stake=32.50,
        )
        row = db.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()
        assert row["placed"] == 1
        assert row["fd_parlay_odds"] == 245
        assert row["actual_stake"] == 32.50
        assert row["placed_at"] is not None

    def test_update_result(self, db):
        parlay_id = insert_parlay(
            db,
            leg1_pick_id=1,
            leg2_pick_id=2,
            combined_odds=257,
            combined_edge=0.048,
        )
        update_parlay_result(db, parlay_id=parlay_id, result="won", payout=116.19)
        row = db.execute(
            "SELECT * FROM parlays WHERE parlay_id = ?", (parlay_id,)
        ).fetchone()
        assert row["result"] == "won"
        assert row["payout"] == 116.19


class TestLadderState:
    def test_insert_and_get(self, db):
        insert_ladder_state(
            db,
            attempt_id=1,
            step=1,
            bankroll=10.0,
            parlay_id=None,
            result=None,
        )
        state = get_ladder_state(db)
        assert state is not None
        assert state["attempt_id"] == 1
        assert state["step"] == 1
        assert state["bankroll"] == 10.0

    def test_get_active_ladder_empty(self, db):
        result = get_active_ladder(db)
        assert result is None

    def test_get_active_ladder(self, db):
        insert_ladder_state(db, attempt_id=1, step=1, bankroll=10.0)
        insert_ladder_state(db, attempt_id=1, step=2, bankroll=32.50)
        state = get_active_ladder(db)
        assert state["step"] == 2
        assert state["bankroll"] == 32.50


class TestFlatBet:
    def test_insert_flat_bet(self, db):
        insert_flat_bet(db, pick_id=1, amount=10.0, odds=257, result="won", profit_loss=25.70)
        row = db.execute("SELECT * FROM flat_bets WHERE pick_id = ?", (1,)).fetchone()
        assert row["profit_loss"] == 25.70
```

#### Step 3.2: Verify tests fail

```bash
pytest tests/test_database.py -v
# Expected: ModuleNotFoundError
```

#### Step 3.3: Create `ladderbot/db/schema.sql`

```sql
-- File: ladderbot/db/schema.sql
-- LadderBot database schema

CREATE TABLE IF NOT EXISTS games (
    game_id     TEXT PRIMARY KEY,
    sport       TEXT NOT NULL,       -- 'nba' or 'nhl'
    home_team   TEXT NOT NULL,
    away_team   TEXT NOT NULL,
    game_date   TEXT NOT NULL,       -- ISO date YYYY-MM-DD
    home_score  INTEGER,
    away_score  INTEGER,
    status      TEXT NOT NULL DEFAULT 'scheduled'  -- scheduled, in_progress, final
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     TEXT NOT NULL,
    bookmaker   TEXT NOT NULL,        -- 'draftkings', 'fanduel', etc.
    market      TEXT NOT NULL,        -- 'h2h', 'spreads', 'totals'
    outcome     TEXT NOT NULL,        -- team abbrev, 'Over', 'Under'
    price       INTEGER NOT NULL,     -- American odds
    point       REAL,                 -- spread or total line (e.g., -3.5, 5.5)
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE TABLE IF NOT EXISTS model_predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     TEXT NOT NULL,
    market      TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    model_prob  REAL NOT NULL,
    book_prob   REAL NOT NULL,
    edge        REAL NOT NULL,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE TABLE IF NOT EXISTS picks (
    pick_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    parlay_id   INTEGER,
    game_id     TEXT NOT NULL,
    market      TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    odds_at_pick INTEGER NOT NULL,
    closing_odds INTEGER,
    clv         REAL,
    result      TEXT,                 -- 'won', 'lost', 'push', NULL if pending
    FOREIGN KEY (game_id) REFERENCES games(game_id),
    FOREIGN KEY (parlay_id) REFERENCES parlays(parlay_id)
);

CREATE TABLE IF NOT EXISTS parlays (
    parlay_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    leg1_pick_id    INTEGER,
    leg2_pick_id    INTEGER,
    combined_odds   INTEGER NOT NULL,
    combined_edge   REAL NOT NULL,
    result          TEXT,              -- 'won', 'lost', NULL if pending
    payout          REAL,
    -- FanDuel verification columns (web dashboard)
    fd_leg1_odds    INTEGER,
    fd_leg2_odds    INTEGER,
    fd_parlay_odds  INTEGER,
    fd_edge         REAL,
    placed          INTEGER NOT NULL DEFAULT 0,   -- boolean: 0 or 1
    placed_at       TEXT,
    skipped         INTEGER NOT NULL DEFAULT 0,   -- boolean: 0 or 1
    skip_reason     TEXT,
    actual_stake    REAL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (leg1_pick_id) REFERENCES picks(pick_id),
    FOREIGN KEY (leg2_pick_id) REFERENCES picks(pick_id)
);

CREATE TABLE IF NOT EXISTS ladder_state (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id  INTEGER NOT NULL,
    step        INTEGER NOT NULL,
    bankroll    REAL NOT NULL,
    parlay_id   INTEGER,
    result      TEXT,                 -- 'won', 'lost', NULL if in progress
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parlay_id) REFERENCES parlays(parlay_id)
);

CREATE TABLE IF NOT EXISTS flat_bets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pick_id     INTEGER NOT NULL,
    amount      REAL NOT NULL,
    odds        INTEGER NOT NULL,
    result      TEXT,                 -- 'won', 'lost', 'push'
    profit_loss REAL,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (pick_id) REFERENCES picks(pick_id)
);

CREATE TABLE IF NOT EXISTS team_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team        TEXT NOT NULL,
    sport       TEXT NOT NULL,
    stat_name   TEXT NOT NULL,
    stat_value  REAL NOT NULL,
    stat_date   TEXT NOT NULL,       -- ISO date
    window_size INTEGER,             -- rolling window games
    timestamp   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS goalie_confirmations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      TEXT NOT NULL,
    team         TEXT NOT NULL,
    goalie_name  TEXT NOT NULL,
    confirmed_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_odds_game_id ON odds_snapshots(game_id);
CREATE INDEX IF NOT EXISTS idx_odds_timestamp ON odds_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_predictions_game_id ON model_predictions(game_id);
CREATE INDEX IF NOT EXISTS idx_picks_parlay_id ON picks(parlay_id);
CREATE INDEX IF NOT EXISTS idx_picks_game_id ON picks(game_id);
CREATE INDEX IF NOT EXISTS idx_ladder_attempt ON ladder_state(attempt_id);
CREATE INDEX IF NOT EXISTS idx_team_stats_team ON team_stats(team, sport, stat_date);
CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date);
CREATE INDEX IF NOT EXISTS idx_parlays_created ON parlays(created_at);
```

#### Step 3.4: Implement `ladderbot/db/database.py`

```python
# File: ladderbot/db/database.py
"""Database manager for LadderBot.

Provides connection factory and CRUD helpers for all tables.
Uses SQLite with WAL mode for concurrent read access from the web dashboard.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# Path to schema.sql relative to this file
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Default database path
_DEFAULT_DB_PATH = str(Path(__file__).parent.parent.parent / "data" / "ladderbot.db")


def get_db(db_path: str | None = None) -> sqlite3.Connection:
    """Get a database connection, creating the DB and tables if needed.

    Args:
        db_path: Path to the SQLite database file. Defaults to data/ladderbot.db.

    Returns:
        sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    if db_path is None:
        db_path = _DEFAULT_DB_PATH

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Run schema if tables don't exist
    _init_schema(conn)

    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Execute schema.sql to create tables if they don't exist."""
    schema_sql = _SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)


# ── Game helpers ──────────────────────────────────────────────────────────────


def insert_game(
    conn: sqlite3.Connection,
    game_id: str,
    sport: str,
    home_team: str,
    away_team: str,
    game_date: str,
    home_score: int | None = None,
    away_score: int | None = None,
    status: str = "scheduled",
) -> None:
    """Insert or update a game record."""
    conn.execute(
        """
        INSERT INTO games (game_id, sport, home_team, away_team, game_date, home_score, away_score, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_id) DO UPDATE SET
            home_score = COALESCE(excluded.home_score, games.home_score),
            away_score = COALESCE(excluded.away_score, games.away_score),
            status = excluded.status
        """,
        (game_id, sport, home_team, away_team, game_date, home_score, away_score, status),
    )
    conn.commit()


# ── Odds helpers ──────────────────────────────────────────────────────────────


def insert_odds_snapshot(
    conn: sqlite3.Connection,
    game_id: str,
    bookmaker: str,
    market: str,
    outcome: str,
    price: int,
    point: float | None = None,
) -> int:
    """Insert an odds snapshot. Returns the row id."""
    cursor = conn.execute(
        """
        INSERT INTO odds_snapshots (game_id, bookmaker, market, outcome, price, point)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (game_id, bookmaker, market, outcome, price, point),
    )
    conn.commit()
    return cursor.lastrowid


# ── Prediction helpers ────────────────────────────────────────────────────────


def insert_prediction(
    conn: sqlite3.Connection,
    game_id: str,
    market: str,
    outcome: str,
    model_prob: float,
    book_prob: float,
    edge: float,
) -> int:
    """Insert a model prediction. Returns the row id."""
    cursor = conn.execute(
        """
        INSERT INTO model_predictions (game_id, market, outcome, model_prob, book_prob, edge)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (game_id, market, outcome, model_prob, book_prob, edge),
    )
    conn.commit()
    return cursor.lastrowid


# ── Pick helpers ──────────────────────────────────────────────────────────────


def insert_pick(
    conn: sqlite3.Connection,
    game_id: str,
    market: str,
    outcome: str,
    odds_at_pick: int,
    parlay_id: int | None = None,
) -> int:
    """Insert a pick. Returns the pick_id."""
    cursor = conn.execute(
        """
        INSERT INTO picks (parlay_id, game_id, market, outcome, odds_at_pick)
        VALUES (?, ?, ?, ?, ?)
        """,
        (parlay_id, game_id, market, outcome, odds_at_pick),
    )
    conn.commit()
    return cursor.lastrowid


# ── Parlay helpers ────────────────────────────────────────────────────────────


def insert_parlay(
    conn: sqlite3.Connection,
    leg1_pick_id: int,
    leg2_pick_id: int,
    combined_odds: int,
    combined_edge: float,
) -> int:
    """Insert a parlay. Returns the parlay_id."""
    cursor = conn.execute(
        """
        INSERT INTO parlays (leg1_pick_id, leg2_pick_id, combined_odds, combined_edge)
        VALUES (?, ?, ?, ?)
        """,
        (leg1_pick_id, leg2_pick_id, combined_odds, combined_edge),
    )
    conn.commit()
    return cursor.lastrowid


def update_parlay_placed(
    conn: sqlite3.Connection,
    parlay_id: int,
    fd_leg1_odds: int,
    fd_leg2_odds: int,
    fd_parlay_odds: int,
    fd_edge: float,
    actual_stake: float,
) -> None:
    """Mark a parlay as placed with FanDuel odds."""
    conn.execute(
        """
        UPDATE parlays SET
            fd_leg1_odds = ?,
            fd_leg2_odds = ?,
            fd_parlay_odds = ?,
            fd_edge = ?,
            placed = 1,
            placed_at = datetime('now'),
            actual_stake = ?
        WHERE parlay_id = ?
        """,
        (fd_leg1_odds, fd_leg2_odds, fd_parlay_odds, fd_edge, actual_stake, parlay_id),
    )
    conn.commit()


def update_parlay_skipped(
    conn: sqlite3.Connection,
    parlay_id: int,
    skip_reason: str = "user_choice",
) -> None:
    """Mark a parlay as skipped."""
    conn.execute(
        """
        UPDATE parlays SET skipped = 1, skip_reason = ?
        WHERE parlay_id = ?
        """,
        (skip_reason, parlay_id),
    )
    conn.commit()


def update_parlay_result(
    conn: sqlite3.Connection,
    parlay_id: int,
    result: str,
    payout: float | None = None,
) -> None:
    """Update a parlay's result."""
    conn.execute(
        """
        UPDATE parlays SET result = ?, payout = ?
        WHERE parlay_id = ?
        """,
        (result, payout, parlay_id),
    )
    conn.commit()


# ── Ladder helpers ────────────────────────────────────────────────────────────


def insert_ladder_state(
    conn: sqlite3.Connection,
    attempt_id: int,
    step: int,
    bankroll: float,
    parlay_id: int | None = None,
    result: str | None = None,
) -> int:
    """Insert a ladder state row. Returns the row id."""
    cursor = conn.execute(
        """
        INSERT INTO ladder_state (attempt_id, step, bankroll, parlay_id, result)
        VALUES (?, ?, ?, ?, ?)
        """,
        (attempt_id, step, bankroll, parlay_id, result),
    )
    conn.commit()
    return cursor.lastrowid


def get_ladder_state(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """Get the most recent ladder state row."""
    return conn.execute(
        "SELECT * FROM ladder_state ORDER BY id DESC LIMIT 1"
    ).fetchone()


def get_active_ladder(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """Get the latest ladder state that has no terminal result (i.e., still in progress).

    Returns the most recent state row for the latest attempt. Returns None
    if no ladder state exists.
    """
    row = conn.execute(
        """
        SELECT * FROM ladder_state
        ORDER BY attempt_id DESC, step DESC
        LIMIT 1
        """
    ).fetchone()
    return row


# ── Flat bet helpers ──────────────────────────────────────────────────────────


def insert_flat_bet(
    conn: sqlite3.Connection,
    pick_id: int,
    amount: float,
    odds: int,
    result: str | None = None,
    profit_loss: float | None = None,
) -> int:
    """Insert a flat bet record. Returns the row id."""
    cursor = conn.execute(
        """
        INSERT INTO flat_bets (pick_id, amount, odds, result, profit_loss)
        VALUES (?, ?, ?, ?, ?)
        """,
        (pick_id, amount, odds, result, profit_loss),
    )
    conn.commit()
    return cursor.lastrowid


# ── Query helpers ─────────────────────────────────────────────────────────────


def get_today_parlays(conn: sqlite3.Connection, today: str | None = None) -> list[sqlite3.Row]:
    """Get all parlays created today."""
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    return conn.execute(
        """
        SELECT * FROM parlays
        WHERE date(created_at) = ?
        ORDER BY combined_edge DESC
        """,
        (today,),
    ).fetchall()


def get_games_by_date(conn: sqlite3.Connection, game_date: str) -> list[sqlite3.Row]:
    """Get all games for a given date."""
    return conn.execute(
        "SELECT * FROM games WHERE game_date = ? ORDER BY game_id",
        (game_date,),
    ).fetchall()
```

#### Step 3.5: Verify tests pass

```bash
pytest tests/test_database.py -v
# Expected: all tests pass
```

#### Step 3.6: Commit

```bash
git add ladderbot/db/schema.sql ladderbot/db/database.py tests/test_database.py
git commit -m "feat: database schema and manager with CRUD helpers"
```

---

### Task 4: Config Loader

**Goal**: A config module that loads `config.yaml` with sensible defaults, validates that required API keys are present, and provides a first-run wizard when no config file exists.

#### Step 4.1: Write tests first

```python
# File: tests/test_config.py
"""Tests for config loader."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from ladderbot.config import load_config, validate_config, ConfigError, DEFAULT_CONFIG


@pytest.fixture
def config_dir(tmp_path):
    """Provide a temp directory for config files."""
    return tmp_path


@pytest.fixture
def valid_config_file(config_dir):
    """Write a valid config.yaml and return its path."""
    config = {
        "odds_api_key": "test-key-12345",
        "discord_webhook_url": "https://discord.com/api/webhooks/123/abc",
        "ladder": {
            "starting_amount": 10.0,
            "target_amount": 1000.0,
            "max_attempts": 50,
        },
        "parlay": {
            "min_legs": 2,
            "max_legs": 2,
            "target_odds_min": 150,
            "target_odds_max": 300,
            "min_edge_per_leg": 0.02,
            "min_edge_cold_start": 0.03,
        },
        "model": {
            "rolling_window": 20,
            "use_xgboost": False,
            "cold_start_games": 20,
        },
        "sports": {
            "nba": True,
            "nhl": True,
        },
        "run_time": "11:00",
        "pre_game_refresh": 120,
        "scheduler": "manual",
    }
    path = config_dir / "config.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


class TestLoadConfig:
    def test_loads_valid_config(self, valid_config_file):
        config = load_config(valid_config_file)
        assert config["odds_api_key"] == "test-key-12345"
        assert config["discord_webhook_url"] == "https://discord.com/api/webhooks/123/abc"

    def test_applies_defaults_for_missing_sections(self, config_dir):
        """A minimal config with just required fields should get defaults filled in."""
        minimal = {
            "odds_api_key": "key-123",
            "discord_webhook_url": "https://discord.com/api/webhooks/1/x",
        }
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(minimal))
        config = load_config(str(path))
        assert config["ladder"]["starting_amount"] == 10.0
        assert config["ladder"]["target_amount"] == 1000.0
        assert config["parlay"]["min_edge_per_leg"] == 0.02
        assert config["model"]["rolling_window"] == 20
        assert config["sports"]["nba"] is True
        assert config["scheduler"] == "manual"

    def test_file_not_found_raises(self, config_dir):
        with pytest.raises(FileNotFoundError):
            load_config(str(config_dir / "nonexistent.yaml"))

    def test_user_values_override_defaults(self, config_dir):
        custom = {
            "odds_api_key": "key-123",
            "discord_webhook_url": "https://discord.com/api/webhooks/1/x",
            "ladder": {"starting_amount": 25.0},
            "parlay": {"min_edge_per_leg": 0.05},
        }
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(custom))
        config = load_config(str(path))
        assert config["ladder"]["starting_amount"] == 25.0
        assert config["parlay"]["min_edge_per_leg"] == 0.05
        # Other defaults still present
        assert config["ladder"]["target_amount"] == 1000.0


class TestValidateConfig:
    def test_missing_odds_api_key(self, config_dir):
        bad = {"discord_webhook_url": "https://discord.com/api/webhooks/1/x"}
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(bad))
        config = load_config(str(path))
        with pytest.raises(ConfigError, match="odds_api_key"):
            validate_config(config)

    def test_missing_discord_webhook(self, config_dir):
        bad = {"odds_api_key": "key-123"}
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(bad))
        config = load_config(str(path))
        with pytest.raises(ConfigError, match="discord_webhook_url"):
            validate_config(config)

    def test_placeholder_api_key_rejected(self, config_dir):
        bad = {
            "odds_api_key": "your-key-here",
            "discord_webhook_url": "https://discord.com/api/webhooks/1/x",
        }
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(bad))
        config = load_config(str(path))
        with pytest.raises(ConfigError, match="odds_api_key"):
            validate_config(config)

    def test_placeholder_webhook_rejected(self, config_dir):
        bad = {
            "odds_api_key": "real-key",
            "discord_webhook_url": "https://discord.com/api/webhooks/...",
        }
        path = config_dir / "config.yaml"
        path.write_text(yaml.dump(bad))
        config = load_config(str(path))
        with pytest.raises(ConfigError, match="discord_webhook_url"):
            validate_config(config)

    def test_valid_config_passes(self, valid_config_file):
        config = load_config(valid_config_file)
        validate_config(config)  # Should not raise


class TestDefaultConfig:
    def test_default_config_has_all_sections(self):
        assert "ladder" in DEFAULT_CONFIG
        assert "parlay" in DEFAULT_CONFIG
        assert "model" in DEFAULT_CONFIG
        assert "sports" in DEFAULT_CONFIG
        assert "run_time" in DEFAULT_CONFIG
        assert "scheduler" in DEFAULT_CONFIG
```

#### Step 4.2: Verify tests fail

```bash
pytest tests/test_config.py -v
# Expected: ModuleNotFoundError
```

#### Step 4.3: Implement `ladderbot/config.py`

```python
# File: ladderbot/config.py
"""Configuration loader for LadderBot.

Loads config.yaml, merges with defaults, validates required fields.
Provides a first-run wizard if config.yaml is missing.
"""
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid."""
    pass


# Default configuration — all optional fields with sensible values
DEFAULT_CONFIG: dict[str, Any] = {
    "odds_api_key": "",
    "discord_webhook_url": "",
    "ladder": {
        "starting_amount": 10.0,
        "target_amount": 1000.0,
        "max_attempts": 50,
    },
    "parlay": {
        "min_legs": 2,
        "max_legs": 2,
        "target_odds_min": 150,
        "target_odds_max": 300,
        "min_edge_per_leg": 0.02,
        "min_edge_cold_start": 0.03,
    },
    "model": {
        "rolling_window": 20,
        "use_xgboost": False,
        "cold_start_games": 20,
    },
    "sports": {
        "nba": True,
        "nhl": True,
    },
    "run_time": "11:00",
    "pre_game_refresh": 120,
    "scheduler": "manual",
}

# Placeholder values that indicate the user hasn't configured the field
_PLACEHOLDERS = {
    "odds_api_key": {"your-key-here", ""},
    "discord_webhook_url": {"https://discord.com/api/webhooks/...", ""},
}

# Default config file path (project root)
_DEFAULT_CONFIG_PATH = str(Path(__file__).parent.parent / "config.yaml")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override values win."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load config from YAML file and merge with defaults.

    Args:
        config_path: Path to config.yaml. Defaults to project root config.yaml.

    Returns:
        Merged configuration dictionary.

    Raises:
        FileNotFoundError: If config file does not exist.
    """
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        user_config = yaml.safe_load(f) or {}

    return _deep_merge(DEFAULT_CONFIG, user_config)


def validate_config(config: dict[str, Any]) -> None:
    """Validate that required fields are present and not placeholders.

    Args:
        config: Configuration dictionary to validate.

    Raises:
        ConfigError: If a required field is missing or still a placeholder.
    """
    # Check odds_api_key
    api_key = config.get("odds_api_key", "")
    if not api_key or api_key in _PLACEHOLDERS["odds_api_key"]:
        raise ConfigError(
            "odds_api_key is required. Get a free key at https://the-odds-api.com"
        )

    # Check discord_webhook_url
    webhook = config.get("discord_webhook_url", "")
    if not webhook or webhook in _PLACEHOLDERS["discord_webhook_url"]:
        raise ConfigError(
            "discord_webhook_url is required. Create a webhook in Discord: "
            "Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy URL"
        )


def first_run_wizard(config_path: str | None = None) -> dict[str, Any]:
    """Interactive wizard to create config.yaml on first run.

    Prompts the user for required fields and writes the config file.

    Args:
        config_path: Where to write config.yaml. Defaults to project root.

    Returns:
        The created configuration dictionary.
    """
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    print("=" * 60)
    print("  LADDERBOT — First-Run Setup")
    print("=" * 60)
    print()
    print("No config.yaml found. Let's create one.")
    print()

    # Get API key
    print("1. The Odds API key (free at https://the-odds-api.com)")
    api_key = input("   API key: ").strip()
    while not api_key or api_key in _PLACEHOLDERS["odds_api_key"]:
        print("   Please enter a valid API key.")
        api_key = input("   API key: ").strip()

    print()

    # Get Discord webhook
    print("2. Discord webhook URL")
    print("   (Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy URL)")
    webhook = input("   Webhook URL: ").strip()
    while not webhook or webhook in _PLACEHOLDERS["discord_webhook_url"]:
        print("   Please enter a valid webhook URL.")
        webhook = input("   Webhook URL: ").strip()

    print()

    # Build config
    config = deepcopy(DEFAULT_CONFIG)
    config["odds_api_key"] = api_key
    config["discord_webhook_url"] = webhook

    # Write file
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"Config written to {config_path}")
    print("Edit this file to customize ladder, parlay, and model settings.")
    print()

    return config


def get_config(config_path: str | None = None, interactive: bool = True) -> dict[str, Any]:
    """High-level config loader: load, validate, or run wizard.

    Args:
        config_path: Path to config.yaml.
        interactive: If True and config missing, run first-run wizard.
                     If False and config missing, raise FileNotFoundError.

    Returns:
        Validated configuration dictionary.
    """
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    if not Path(config_path).exists():
        if interactive:
            return first_run_wizard(config_path)
        else:
            raise FileNotFoundError(f"Config file not found: {config_path}")

    config = load_config(config_path)
    validate_config(config)
    return config
```

#### Step 4.4: Verify tests pass

```bash
pytest tests/test_config.py -v
# Expected: all tests pass
```

#### Step 4.5: Commit

```bash
git add ladderbot/config.py tests/test_config.py
git commit -m "feat: config loader with defaults, validation, and first-run wizard"
```

---

### Post-Chunk Verification

After all four tasks are complete, run the full test suite to confirm nothing is broken:

```bash
pytest tests/ -v
```

Expected result: all tests in `test_odds.py`, `test_database.py`, and `test_config.py` pass. The project installs cleanly with `pip install -e ".[dev]"` and all imports resolve.

**Files created in this chunk:**

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package manifest and dependencies |
| `config.example.yaml` | Template config for users |
| `.gitignore` | Ignore DB, secrets, cache |
| `ladderbot/__init__.py` (+ 8 sub-packages) | Package structure |
| `ladderbot/run.py` | Placeholder entry point |
| `ladderbot/utils/odds.py` | Odds math library |
| `ladderbot/db/schema.sql` | Full SQLite schema |
| `ladderbot/db/database.py` | DB connection + CRUD helpers |
| `ladderbot/config.py` | Config loader + validator + wizard |
| `tests/test_odds.py` | 30+ odds math tests |
| `tests/test_database.py` | 15+ database tests |
| `tests/test_config.py` | 10+ config tests |
