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
