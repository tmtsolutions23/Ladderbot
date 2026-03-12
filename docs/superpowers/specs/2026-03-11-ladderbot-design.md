# LadderBot Design Spec

## Overview

LadderBot is a Python tool with CLI, web dashboard, and Discord alerts that identifies +EV 2-leg cross-game parlays for NBA and NHL and tracks a rolling ladder from $10 to $1,000. It combines statistical modeling with a parlay optimizer to find the mathematically best bets each day. The web dashboard lets users verify FanDuel odds against DraftKings, mark bets as placed, and visually track ladder progression and model performance.

## Goals

- **Primary**: Identify 2-leg cross-game parlays at +200/+250 (target range +150/+300) where both legs are individually +EV
- **Secondary**: Track ladder progression ($10 -> $1,000 in ~4-5 steps), shadow flat-bet performance, and Closing Line Value (CLV)
- **Tertiary**: Provide a CLI dashboard for exploring model predictions, value ratings, and historical performance

## Ladder Strategy

### Mathematical Foundation

- **Target parlay odds**: +200 to +250 (decimal 3.00-3.50)
- **Why 2 legs**: 2-leg parlays carry ~9% vig (vs 13% for 3-leg, 17% for 4-leg). Vig compounds per leg, so fewer legs = less house edge eroding our edge.
- **Why +200/+250**: At +225 (decimal 3.25), only 4 consecutive wins are needed to reach $1,000 from $10. This is the sweet spot between payout-per-step and achievable hit rate. The step count is dynamically calculated based on actual parlay odds: `steps = ceil(log(target/bankroll) / log(decimal_odds))`.
- **Legs composition**: Mix of moderate favorites (-130 to -180 range), slight underdogs (+100 to +150), and plus-money totals — where edges are empirically largest.

### Ladder Progression (at +225)

| Step | Bet     | Win      | Balance   |
|------|---------|----------|-----------|
| 1    | $10.00  | $22.50   | $32.50    |
| 2    | $32.50  | $73.13   | $105.63   |
| 3    | $105.63 | $237.66  | $343.28   |
| 4    | $343.28 | $772.39  | $1,115.67 |

4 consecutive wins. At a realistic ~32% hit rate per parlay (consistent with +5% flat-bet ROI target), P(success) = 0.32^4 = 1.05% per attempt. The ladder is expected to be roughly breakeven on its own — the real value comes from the shadow flat-bet portfolio proving the model has edge, with the ladder providing upside optionality.

### Bankroll Approach

- Each ladder attempt costs $10 (or configured starting amount)
- The $10 should represent 2-5% of total bankroll committed to the strategy
- A shadow flat-bet portfolio tracks model performance independent of ladder variance
- Both portfolios are tracked and reported to separate model skill from ladder luck

## Architecture

```
ladderbot/
├── run.py                    # One-command entry point
├── config.yaml               # API keys, Discord webhook, preferences
├── config.example.yaml       # Template config (committed to repo)
├── requirements.txt          # All dependencies
├── pyproject.toml             # Package config + dependency install
│
├── data/
│   ├── odds.py               # The Odds API client — NBA/NHL lines
│   ├── nba_stats.py          # nba_api wrapper — team/player stats
│   ├── nhl_stats.py          # NHL API + MoneyPuck CSV — xG, GSAx
│   ├── injuries.py           # Injury/lineup scraping (Rotowire/ESPN)
│   └── cache.py              # SQLite cache layer for all API responses
│
├── models/
│   ├── nba_model.py          # Logistic regression: Four Factors + situational
│   ├── nhl_model.py          # Logistic regression: xG + goalie + situational
│   ├── nhl_totals.py         # Dixon-Coles modified Poisson for NHL totals
│   ├── value.py              # Edge detection: model prob vs book implied prob
│   ├── features.py           # Feature engineering pipeline
│   └── calibration.py        # Brier score, calibration curves, Platt scaling
│
├── parlay/
│   ├── optimizer.py          # Finds best 2-leg combos in +150/+300 range
│   └── ladder.py             # Ladder state machine + shadow flat-bet tracker
│
├── alerts/
│   ├── discord.py            # Discord webhook client
│   └── formatter.py          # Pick formatting with edge/confidence display
│
├── tracking/
│   ├── clv.py                # Closing Line Value tracker
│   ├── results.py            # Game result resolution + P/L calculation
│   └── performance.py        # Historical performance dashboard
│
├── web/
│   ├── app.py                # FastAPI backend — REST API for dashboard
│   ├── static/
│   │   ├── index.html        # Single-page app (vanilla JS + Tailwind)
│   │   ├── app.js            # Dashboard logic, odds input, bet tracking
│   │   └── style.css         # Custom styles beyond Tailwind
│   └── routes/
│       ├── picks.py          # GET /picks, POST /picks/{id}/verify-odds, POST /picks/{id}/place
│       ├── ladder.py         # GET /ladder, GET /ladder/history
│       ├── dashboard.py      # GET /dashboard (performance data)
│       └── odds.py           # POST /odds/verify (manual FD odds input)
│
├── db/
│   └── schema.sql            # Single SQLite database for cache + persistent data
│
└── tests/
    ├── test_models.py        # Model accuracy tests
    ├── test_optimizer.py     # Parlay combination tests
    └── test_value.py         # Edge detection tests
```

## Data Layer

### The Odds API (odds.py)

- **Purpose**: Real-time NBA/NHL odds from FanDuel, DraftKings, and other US books
- **Markets**: moneylines (h2h), spreads, totals
- **Caching strategy**: Cache odds snapshots every 30 minutes. Only re-fetch if a game is within 2 hours of tip-off (odds move most near game time).
- **Budget**: Free tier (500 req/month) may suffice with aggressive caching. If not, paid tier at $79/month.
- **Key fields stored**: sport, game_id, bookmaker, market_type, outcome, price, timestamp

### NBA Stats (nba_stats.py)

- **Source**: `nba_api` Python package
- **Data pulled**:
  - Team dashboard stats with `MeasureType=Advanced` (ORtg, DRtg, pace, net rating)
  - Team dashboard stats with `MeasureType=Four Factors` (eFG%, TOV%, ORB%, FT/FGA — offense and defense)
  - Team game logs (recent form, rolling averages)
  - Player game logs (for injury-impact estimation)
  - Schedule/scoreboard (today's games)
- **Rate limiting**: 0.75s delay between requests, retry with backoff on 429/403
- **Refresh**: Full team stats refresh once daily. Game-day odds refresh more frequently.

### NHL Stats (nhl_stats.py)

- **Sources**: NHL API (`api-web.nhle.com`) + MoneyPuck CSV downloads
- **NHL API data**: schedules, rosters, game results, standings
- **MoneyPuck data**:
  - Team-level: 5v5 xGF/60, xGA/60, CF%, FF%, HDCF%, score-close variants
  - Goalie-level: GSAx, HDSV%, even-strength SV%, games played
  - Shot-level: individual shot xG values (for building/validating our own xG)
- **Refresh**: MoneyPuck CSVs downloaded once daily (updated morning after games). NHL API for schedule/scores as needed.

### Injury Data (injuries.py)

- **Source**: ESPN or Rotowire injury feeds (scrape HTML)
- **Purpose**: nba_api injury endpoint is unreliable. Need external source.
- **Data**: player name, team, status (out/doubtful/questionable/probable), injury description
- **NBA impact**: Missing a top player swings spreads 3-7 points. Critical for accurate modeling.
- **NHL impact**: Goalie confirmation is the single biggest line-mover. Must detect starter vs backup.

### Cache Layer (cache.py)

- **Storage**: SQLite database at `data/ladderbot.db`
- **Purpose**: Minimize API calls, stay within rate limits, preserve historical data for backtesting
- **TTL by data type**:
  - Odds: 30 minutes (or 5 minutes within 2 hours of game time)
  - Team stats: 24 hours
  - MoneyPuck CSVs: 24 hours
  - Injury reports: 2 hours
  - Game results: permanent (historical record)
- **Bonus**: All cached odds become historical odds data for future backtesting

## Models

### NBA Model (nba_model.py)

**Algorithm**: Logistic regression (primary). XGBoost available as optional upgrade, enabled only if it beats LR by >1% AUC on held-out season data.

**Features** (per team, computed as differential home minus away):

| Feature | Source | Stability |
|---------|--------|-----------|
| Pace-adjusted net rating (rolling 20-game) | nba_api Advanced | Stabilizes ~20 games |
| Offensive eFG% (rolling 15-game) | nba_api Four Factors | Stabilizes ~15 games |
| Defensive eFG% allowed (rolling 15-game) | nba_api Four Factors | Stabilizes ~15 games |
| TOV% differential | nba_api Four Factors | Stabilizes ~15 games |
| ORB% differential | nba_api Four Factors | Stabilizes ~10 games |
| FT rate differential | nba_api Four Factors | Stabilizes ~10 games |
| Rest days (0=B2B, 1=1day, 2=2day, 3+=3+) | Schedule | Immediate |
| Home court flag | Schedule | Immediate |
| Travel distance (miles in last 5 days) | Schedule + geography lookup | Immediate |
| Injury impact (sum of missing player EPM) | Injuries + player ratings | Immediate |

**Output**: P(home_win), which implies P(away_win) = 1 - P(home_win)

**For totals**: Separate linear regression on same features → predicted total points. Compare to book total for over/under edge.

**Calibration**: Platt scaling applied to raw model outputs. Validated with calibration curves binned at 5% intervals.

### NHL Model (nhl_model.py)

**Algorithm**: Logistic regression (primary).

**Features** (per team, computed as differential):

| Feature | Source | Stability |
|---------|--------|-----------|
| 5v5 xGF/60 (score-close, rolling 20-game) | MoneyPuck | Stabilizes ~20 games |
| 5v5 xGA/60 (score-close, rolling 20-game) | MoneyPuck | Stabilizes ~20 games |
| Goalie GSAx (rolling, confirmed starter) | MoneyPuck | Stabilizes ~15 starts |
| Goalie HDSV% (confirmed starter) | MoneyPuck | Stabilizes ~15 starts |
| PP xG/60 | MoneyPuck | Stabilizes ~25 games |
| PK xGA/60 | MoneyPuck | Stabilizes ~25 games |
| Rest differential (team rest days minus opponent rest days) | Schedule | Immediate |
| Home ice flag | Schedule | Immediate |
| Back-to-back flag (with travel distance) | Schedule | Immediate |
| PDO regression signal (current PDO minus 100) | MoneyPuck | Early season only |

**Output**: P(home_win)

**Goalie-sensitive**: Model re-runs when goalie confirmation comes in (typically 30-60 min before puck drop). Discord alert updates if pick changes.

### NHL Totals Model (nhl_totals.py)

**Algorithm**: Dixon-Coles modified bivariate Poisson

- Standard Poisson underestimates extreme outcomes in hockey
- Dixon-Coles corrects for low-score inflation (0-0, 1-0, 0-1, 1-1 are more common than Poisson predicts)
- Models home and away goal-scoring rates as correlated Poisson processes

**Inputs**: Combined xGF rates, goalie GSAx, pace proxy (shots/60), special teams rates, rest factors

**Output**: P(over) and P(under) for the book's posted total line

### Edge Detection (value.py)

For every bet opportunity:

```
model_prob = model's predicted probability of outcome
book_prob = 1 / decimal_odds (implied probability from book)
edge = model_prob - book_prob

if edge > MIN_EDGE_THRESHOLD (default 2.0%):
    mark as +EV candidate
```

**Thresholds**:
- Minimum edge per leg: 2.0% (configurable)
- Minimum model confidence: 0.30 (don't bet on things model is very uncertain about)
- Maximum model confidence: 0.75 (extremely heavy favorites rarely offer value)

### Cold-Start Mode (features.py)

For the first 20 games of each season:
- Weight prior-season team metrics at `(20 - games_played) / 20`
- Weight current-season metrics at `games_played / 20`
- Apply roster-change penalty: reduce prior-season weight by 5% per significant roster move. Defined as: NBA — any player who averaged 20+ minutes/game last season being traded/signed/waived. NHL — starting goalie change or any top-6 forward / top-4 defenseman traded/signed.
- Widen MIN_EDGE_THRESHOLD to 3.0% during cold start (require more edge to bet on uncertain data)
- Flag all cold-start picks with reduced confidence in Discord alerts

### Calibration (calibration.py)

- **Brier score**: Computed rolling over last 100 predictions per sport
- **Calibration curves**: Predicted probability binned at 5% intervals vs actual outcome frequency
- **Platt scaling**: Sigmoid recalibration applied to raw model outputs (trained on validation set)
- **Temporal check**: Separate calibration metrics for early-season (games 1-25) vs mid/late-season
- **Auto-alert**: If Brier score degrades by >10% from baseline, Discord alert warns that model may need retraining

## Error Handling & Fallbacks

### API Failures

| Source | Failure Mode | Behavior |
|--------|-------------|----------|
| The Odds API | HTTP error / timeout | Retry 3x with exponential backoff (2s, 4s, 8s). If still failing, use last cached odds (if < 2 hours old). If no valid cache, skip odds-dependent picks and send Discord alert: "Odds API unavailable — no picks today." |
| nba_api | 429/403 rate limit | Back off 5s, retry up to 5x. If blocked, use cached stats (< 24h old). If no cache, skip NBA picks. |
| MoneyPuck | CSV download fails | Use cached CSV (< 48h old). If no cache, skip NHL picks. |
| NHL API | Endpoint changed / down | Use cached schedule data. Log warning. |
| Discord webhook | Delivery failure | Retry 3x. If failing, log picks to `picks.log` as fallback. Print to terminal. |

### Zero Picks Found

When the optimizer finds no valid parlays on a given day (common on light schedules or early season):
- Send Discord alert: "No +EV parlays found today. [X] games analyzed, best edge was [Y]% (below [Z]% threshold)."
- Ladder stays in current state (IDLE or ACTIVE — no action taken)
- Log the analysis for performance tracking
- Do NOT lower thresholds to force a pick — no pick is better than a bad pick

### Odds Verification Warning

Since the system uses DraftKings odds as a proxy for FanDuel:
- Discord alerts include a note: "Verify odds on FanDuel before placing. DK odds shown."
- If FanDuel odds are worse by more than 15 cents, the edge may be gone — user should skip the bet
- Future enhancement: scrape FanDuel odds directly for comparison

## Confidence Classification

Picks are labeled with a confidence level derived from edge magnitude:

| Label | Edge Range | Display |
|-------|-----------|---------|
| LOW | 2.0% - 3.0% | Confidence: LOW |
| MEDIUM | 3.0% - 5.0% | Confidence: MEDIUM |
| HIGH | 5.0%+ | Confidence: HIGH |

During cold-start mode (first 20 games), all picks are capped at MEDIUM regardless of edge.

## Parlay Optimizer (optimizer.py)

### How It Works

1. Collect all +EV single-bet candidates across NBA and NHL
2. Generate all valid 2-leg combinations where:
   - Both legs are from **different games** (cross-game only)
   - Combined parlay odds fall within **+150 to +300** range (target +200/+250)
   - Both legs individually have edge >= MIN_EDGE_THRESHOLD
3. Score each combination:
   ```
   parlay_edge = (leg1_model_prob * leg2_model_prob * parlay_decimal_odds) - 1
   ```
   This is the true expected value of the parlay assuming leg independence (which is valid for cross-game bets).
4. Rank by `parlay_edge` descending
5. Return top 3 parlays

### Leg Mixing Rules

- NBA + NHL cross-sport parlays are allowed (legs are independent)
- Two NBA games or two NHL games are allowed (different games = independent)
- Same-game parlays are NOT supported (correlation pricing is too complex and vig too high)

### Parlay Odds Calculation

```
parlay_decimal = leg1_decimal * leg2_decimal
parlay_american = (parlay_decimal - 1) * 100  # if positive
```

Example: Celtics -160 (1.625) + Rangers/Bruins OVER 5.5 +120 (2.20)
- Parlay decimal: 1.625 * 2.20 = 3.575
- Parlay American: +257.5

**Important**: Sportsbooks may apply additional parlay vig beyond individual leg odds. The calculated parlay odds are the theoretical maximum — the actual offered odds on FanDuel may be slightly worse. The Discord alert shows calculated odds; the user should compare against the actual offered parlay odds and skip if they differ by more than 15 cents.

## Ladder State Machine (ladder.py)

### States

```
IDLE → ACTIVE → WON → next step (ACTIVE) or COMPLETE
                 ↘ LOST → RESET (back to IDLE, new $10)
```

### Tracked Data

- Current step number (dynamically calculated: `ceil(log(target/start) / log(avg_parlay_decimal))`)
- Current bankroll (starts at $10)
- Bet placed (parlay details, odds, timestamp)
- Result (win/loss, actual payout)
- Total attempts (how many ladders started)
- Total invested (attempts * $10)
- Best ladder reached (highest step achieved)

### Shadow Flat-Bet Portfolio

In parallel, every parlay pick is tracked as if a flat $10 bet were placed:
- Same picks, same odds, flat $10 per bet
- Tracks: total bets, wins, losses, profit/loss, ROI%, CLV
- Purpose: isolates model quality from ladder variance
- Reported alongside ladder results in Discord and CLI

## CLV Tracking (clv.py)

### Why CLV Matters

Closing Line Value is the single best predictor of long-term profitability. If you consistently bet lines that move in your favor before close, you have real edge.

### Implementation

1. When a pick is generated, log: `{game_id, market, outcome, odds_at_pick, timestamp}`
2. 5 minutes before game start, fetch closing odds for the same market
3. Compute: `CLV = closing_implied_prob - pick_implied_prob`
   - Positive CLV = you got better odds than closing (good)
   - Negative CLV = you got worse odds than closing (bad)
4. Track rolling average CLV over last 50, 100, 200 bets
5. If rolling CLV is consistently negative, alert via Discord that model may not be beating the market

## Discord Alerts (discord.py + formatter.py)

### Webhook Setup

User creates a webhook in their Discord server (takes 30 seconds, no bot approval needed) and pastes the URL into `config.yaml`.

### Alert Format

```
LADDERBOT — Step 2 of 4
Current Bankroll: $32.50 | Betting: $32.50

LEG 1: Celtics ML (-160) | Edge: +3.1%
  Model: 64.2% | Book: 61.5% | Confidence: HIGH

LEG 2: Avalanche/Stars OVER 5.5 (+120) | Edge: +2.4%
  Model: 48.1% | Book: 45.5% | Goalie: Oettinger confirmed

PARLAY: +257 | Combined Edge: +4.8%

Win: $32.50 -> $116.19 (Step 3)
Loss: Reset to $10 (Attempt #4)

Shadow Portfolio: 12W-8L | +$34.50 | ROI: +17.3% | CLV: +1.2%

NOTE: Odds shown from DraftKings. Verify on FanDuel before placing.
```

### Alert Types

- **PICK**: New parlay identified (sent when top pick is found)
- **UPDATE**: Goalie confirmation or line movement changed the pick
- **RESULT**: Game finished — win/loss, new ladder state
- **DAILY SUMMARY**: End-of-day recap of all picks, results, portfolio status
- **MODEL ALERT**: Calibration degraded, CLV trending negative, or cold-start warning

## Configuration (config.yaml)

```yaml
# API Keys
odds_api_key: "your-key-here"

# Discord
discord_webhook_url: "https://discord.com/api/webhooks/..."

# Ladder Settings
ladder:
  starting_amount: 10.00
  target_amount: 1000.00
  max_attempts: 50          # stop after N failed attempts

# Parlay Settings
parlay:
  min_legs: 2
  max_legs: 2
  target_odds_min: 150      # +150 American
  target_odds_max: 300      # +300 American
  min_edge_per_leg: 0.02    # 2% minimum edge
  min_edge_cold_start: 0.03 # 3% during first 20 games

# Model Settings
model:
  rolling_window: 20        # games for rolling averages
  use_xgboost: false        # set true to enable XGBoost upgrade
  cold_start_games: 20      # games before full-weight current season

# Sports
sports:
  nba: true
  nhl: true

# Schedule
run_time: "11:00"           # daily run time (local)
pre_game_refresh: 120       # minutes before game to re-check odds
scheduler: "manual"         # "manual" (run yourself), "daemon" (run.py stays alive), or "cron" (prints crontab line)
```

### Scheduling Options

- **Manual** (default): User runs `python run.py` whenever they want picks. Simplest, no background processes.
- **Daemon mode**: `python run.py --daemon` stays alive, runs the pipeline at `run_time` daily and re-checks odds `pre_game_refresh` minutes before each game. Uses Python `schedule` library internally.
- **Cron/Task Scheduler**: `python run.py --install-schedule` prints the appropriate crontab line (Linux/Mac) or creates a Windows Task Scheduler entry to run daily at `run_time`.

## Database Schema (schema.sql)

### Core Tables

- **games**: game_id, sport, home_team, away_team, date, home_score, away_score, status
- **odds_snapshots**: game_id, bookmaker, market, outcome, price, timestamp
- **model_predictions**: game_id, market, outcome, model_prob, book_prob, edge, timestamp
- **picks**: pick_id, parlay_id, game_id, market, outcome, odds_at_pick, closing_odds, clv, result
- **parlays**: parlay_id, leg1_pick_id, leg2_pick_id, combined_odds, combined_edge, result, payout
- **ladder_state**: attempt_id, step, bankroll, parlay_id, result, timestamp
- **flat_bets**: pick_id, amount, odds, result, profit_loss
- **team_stats**: team, sport, stat_name, stat_value, date, window_size
- **goalie_confirmations**: game_id, team, goalie_name, confirmed_at

## CLI Interface

### Commands

```bash
python run.py                    # Full daily pipeline: fetch -> model -> optimize -> alert
python run.py --picks            # Show today's picks without sending Discord alert
python run.py --dashboard        # Show model performance, ladder state, CLV stats
python run.py --backtest         # Backtest on cached historical data (see below)
python run.py --status           # Current ladder state + shadow portfolio
python run.py --refresh          # Force re-fetch all data (ignore cache)
python run.py --sport nba        # Only run for NBA
python run.py --sport nhl        # Only run for NHL
python run.py --web              # Launch web dashboard at localhost:8000
python run.py --web --port 8080  # Custom port
```

### Backtest Mode (--backtest)

Runs the model against cached historical data to evaluate performance:

```bash
python run.py --backtest                          # All cached data
python run.py --backtest --from 2026-01-01        # From specific date
python run.py --backtest --from 2026-01-01 --to 2026-02-28  # Date range
```

**Output**: Simulates the full pipeline (model predictions + edge detection + parlay optimization) on historical games where we have cached odds. Reports:
- Flat-bet P/L and ROI (primary metric)
- Win rate by sport, by bet type (ML, totals)
- Brier score and calibration curve
- CLV if closing odds were captured
- Simulated ladder results (how many completions in N attempts)

**Limitations**: Only works on dates where odds were cached. No historical odds exist before the system starts running — this improves over time.

### Dashboard Output (--dashboard)

```
=== LADDERBOT DASHBOARD ===

LADDER STATUS
  Current: Step 2 of 4 | Bankroll: $32.50 | Attempt #3
  Best run: Step 3 ($105.63) on attempt #2
  Total invested: $30.00 | Total returned: $32.50

SHADOW FLAT-BET PORTFOLIO (last 30 days)
  Record: 18W-12L (60.0%) | Profit: +$47.20 | ROI: +15.7%
  NBA: 10W-7L (58.8%) | NHL: 8W-5L (61.5%)

MODEL CALIBRATION
  NBA Brier: 0.228 | NHL Brier: 0.241
  Calibration: [chart showing predicted vs actual by bin]

CLV TRACKING (last 50 bets)
  Average CLV: +1.4% | NBA CLV: +1.1% | NHL CLV: +1.8%

RECENT PICKS
  03/10: Celtics ML + AVS/DAL O5.5 = +257 | WON  | CLV: +2.1%
  03/09: Bucks ML + BOS/NYR U5.5  = +198 | LOST | CLV: +0.3%
  03/08: 76ers ML + FLA/TBL O5.5  = +231 | WON  | CLV: +1.8%
```

## Web Dashboard

### Overview

A local web dashboard served by FastAPI at `http://localhost:8000`. Provides visual tracking, manual FanDuel odds verification, and interactive bet placement confirmation. Launched via:

```bash
python run.py --web          # Start web dashboard (opens browser automatically)
python run.py --web --port 8080  # Custom port
```

### Tech Stack

- **Backend**: FastAPI (lightweight, async, auto-generates API docs at `/docs`)
- **Frontend**: Single-page app — vanilla JS + Tailwind CSS (via CDN). No React/Vue/npm build step. Everything in `web/static/`.
- **Data**: Same SQLite database as the CLI. Dashboard reads from and writes to the same DB.
- **Real-time**: Server-Sent Events (SSE) for live updates when new picks arrive or results come in.

### Pages / Views

#### 1. Today's Picks (Main View — `/`)

The landing page. Shows today's recommended parlays with interactive controls.

```
┌─────────────────────────────────────────────────────────────┐
│  LADDERBOT                              Step 2 of 4 | $32  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  TODAY'S PICKS — March 11, 2026                             │
│                                                             │
│  ┌─ PARLAY #1 ─────────────────────── +257 ──────────────┐  │
│  │                                                       │  │
│  │  LEG 1: Celtics ML (-160)          Edge: +3.1%  HIGH  │  │
│  │  ├─ Model: 64.2% | Book (DK): 61.5%                  │  │
│  │  ├─ FanDuel Odds: [___-155___] ← manual input         │  │
│  │  └─ FD vs DK: ✅ Within threshold (+5 cents)          │  │
│  │                                                       │  │
│  │  LEG 2: AVS/DAL OVER 5.5 (+120)   Edge: +2.4%  MED   │  │
│  │  ├─ Model: 48.1% | Book (DK): 45.5%                  │  │
│  │  ├─ FanDuel Odds: [___+115___] ← manual input         │  │
│  │  └─ FD vs DK: ✅ Within threshold (-5 cents)          │  │
│  │                                                       │  │
│  │  FD Parlay Odds: [___+245___] ← enter actual FD odds  │  │
│  │  Calculated: +257 | Actual FD: +245 | Diff: -12       │  │
│  │  Status: ✅ STILL +EV (edge reduced from 4.8% to 4.1%)│  │
│  │                                                       │  │
│  │         [ ✅ MARK AS PLACED ]    [ ❌ SKIP ]           │  │
│  │                                                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ PARLAY #2 ─────────────────────── +198 ──────────────┐  │
│  │  (similar layout)                                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ PARLAY #3 ─────────────────────── +231 ──────────────┐  │
│  │  (similar layout)                                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**FanDuel Odds Verification Flow**:
1. User sees pick with DraftKings odds (from The Odds API)
2. User opens FanDuel app, finds the same bet
3. User types the actual FanDuel odds into the input fields (per leg + parlay total)
4. System instantly recalculates:
   - New combined parlay odds using FD prices
   - Updated edge (model prob vs FD implied prob)
   - Pass/fail verdict: if edge drops below MIN_EDGE_THRESHOLD → shows "⚠️ EDGE GONE — SKIP" in red
   - If still +EV → shows "✅ STILL +EV" in green with updated edge %
5. User clicks "MARK AS PLACED" or "SKIP"

**Bet Placement Tracking**:
- "MARK AS PLACED" (green checkmark button):
  - Records the bet as placed with the actual FanDuel odds entered
  - Updates the ladder state (bankroll committed, step active)
  - Timestamp recorded
  - Pick card turns green with ✅ badge
  - Shadow flat-bet also recorded at the FD odds (not DK odds)
- "SKIP" (red X button):
  - Records that the pick was skipped (with reason: "odds too low" / "user choice")
  - Ladder stays at current state
  - Pick card turns gray with "SKIPPED" badge
  - Still tracked in shadow portfolio at DK odds for model evaluation

#### 2. Ladder Tracker (`/ladder`)

Visual ladder progression with history.

```
┌─────────────────────────────────────────────────────────────┐
│  LADDER TRACKER                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  CURRENT LADDER — Attempt #3                                │
│                                                             │
│    $1,000+ ─── ○ Step 4 ─── TARGET                         │
│       │                                                     │
│     $343  ─── ○ Step 3                                      │
│       │                                                     │
│     $105  ─── ○ Step 2  ← YOU ARE HERE ($32.50)             │
│       │                                                     │
│      $32  ─── ✅ Step 1 ─── WON +257 (03/10)               │
│       │                                                     │
│      $10  ─── START                                         │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│                                                             │
│  LADDER HISTORY                                             │
│                                                             │
│  Attempt #1: ❌ Step 1 → LOST (03/05)                       │
│  Attempt #2: ❌ Step 3 → LOST at $105.63 (03/06-03/08)     │
│  Attempt #3: 🟢 Step 2 → IN PROGRESS                       │
│                                                             │
│  STATS                                                      │
│  Total attempts: 3 | Total invested: $30                    │
│  Best run: Step 3 ($105.63) | Furthest: 75% complete        │
│  Win rate per step: 40% (2/5 parlays won)                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 3. Performance Dashboard (`/performance`)

Model quality metrics and P/L tracking.

```
┌─────────────────────────────────────────────────────────────┐
│  PERFORMANCE                                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  SHADOW FLAT-BET PORTFOLIO                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  [P/L line chart over time — green when up, red]    │    │
│  │  Record: 18W-12L (60.0%)                            │    │
│  │  Profit: +$47.20 | ROI: +15.7%                      │    │
│  │  NBA: 10W-7L | NHL: 8W-5L                           │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  LADDER P/L (actual placed bets only)                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Total wagered: $30.00 | Returned: $32.50            │    │
│  │  Net: +$2.50                                         │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  MODEL CALIBRATION                                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  [Calibration curve chart — predicted vs actual]     │    │
│  │  NBA Brier: 0.228 | NHL Brier: 0.241                │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  CLV TRACKING                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  [CLV scatter plot — each bet's CLV over time]       │    │
│  │  Avg CLV (50): +1.4% | Avg CLV (100): +1.1%         │    │
│  │  Trend: ↗ improving                                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  BET HISTORY (filterable by sport, date, result)            │
│  ┌────┬──────────┬────────────────────┬──────┬─────┬────┐   │
│  │ ✅ │ 03/10    │ CEL ML + AVS O5.5  │ +257 │ WON │+$32│   │
│  │ ✅ │ 03/09    │ BUK ML + BOS U5.5  │ +198 │LOST │-$20│   │
│  │ ── │ 03/09    │ PHI ML + FLA O5.5  │ +231 │ WON │ -- │   │
│  │ ✅ │ 03/08    │ DEN ML + NYR U6    │ +210 │ WON │+$10│   │
│  └────┴──────────┴────────────────────┴──────┴─────┴────┘   │
│  ✅ = placed on FanDuel  │  ── = skipped / shadow only      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/picks/today` | Today's ranked parlays with model data |
| POST | `/api/picks/{id}/verify` | Submit FanDuel odds, get recalculated edge |
| POST | `/api/picks/{id}/place` | Mark a parlay as placed (green checkmark) |
| POST | `/api/picks/{id}/skip` | Mark a parlay as skipped |
| GET | `/api/ladder` | Current ladder state |
| GET | `/api/ladder/history` | All ladder attempts with results |
| GET | `/api/performance` | Shadow portfolio, Brier, CLV, P/L data |
| GET | `/api/performance/chart/{metric}` | Chart data (pl_over_time, calibration, clv_scatter) |
| GET | `/api/bets` | Bet history with filters (?sport=nba&result=won&placed=true) |
| GET | `/api/health` | System health — API status, last data refresh, model staleness |
| GET | `/events` | SSE stream — real-time pick updates, result notifications |

### POST /api/picks/{id}/verify — Request/Response

```json
// Request
{
  "fd_leg1_odds": -155,
  "fd_leg2_odds": 115,
  "fd_parlay_odds": 245
}

// Response
{
  "pick_id": "p_20260311_001",
  "dk_parlay_odds": 257,
  "fd_parlay_odds": 245,
  "odds_diff": -12,
  "dk_edge": 0.048,
  "fd_edge": 0.041,
  "still_plus_ev": true,
  "verdict": "STILL +EV",
  "message": "Edge reduced from 4.8% to 4.1% — still above 2.0% threshold"
}
```

If edge drops below threshold:
```json
{
  "still_plus_ev": false,
  "verdict": "EDGE GONE",
  "message": "Edge dropped to 1.2% — below 2.0% threshold. Recommend SKIP."
}
```

### POST /api/picks/{id}/place — Request/Response

```json
// Request
{
  "actual_odds": 245,
  "actual_stake": 32.50
}

// Response
{
  "pick_id": "p_20260311_001",
  "status": "placed",
  "ladder_step": 2,
  "potential_payout": 112.13,
  "next_step_target": 343.28
}
```

### Database Additions

New columns/tables for web tracking:

- **parlays** table — add columns:
  - `fd_leg1_odds` (nullable — filled when user verifies)
  - `fd_leg2_odds` (nullable)
  - `fd_parlay_odds` (nullable)
  - `fd_edge` (nullable — recalculated edge at FD odds)
  - `placed` (boolean, default false — true when user clicks checkmark)
  - `placed_at` (timestamp, nullable)
  - `skipped` (boolean, default false)
  - `skip_reason` (text, nullable — "odds_too_low", "user_choice", etc.)
  - `actual_stake` (float, nullable — what user actually bet)

## Setup Process (Turnkey)

The entire setup should take under 5 minutes:

```bash
# 1. Clone and install
git clone <repo>
cd ladderbot
pip install -e .

# 2. Get API key (free)
# Visit https://the-odds-api.com and sign up -> copy API key

# 3. Create Discord webhook
# Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy URL

# 4. Configure
cp config.example.yaml config.yaml
# Edit config.yaml: paste API key and Discord webhook URL

# 5. Run (CLI mode)
python run.py

# 5b. Or run with web dashboard
python run.py --web
# Opens browser to http://localhost:8000
```

`pyproject.toml` handles all dependency installation. No virtual environment setup required (though recommended). A first-run wizard guides through config if `config.yaml` is missing — prompts for API key and Discord webhook URL interactively.

## Testing Strategy

- **Unit tests**: Each model, each data source, optimizer logic
- **Integration test**: Full pipeline with mocked API responses
- **Backtest validation**: Run model on cached historical data, check Brier score and calibration
- **Paper trading**: First 2 weeks run in "paper" mode — picks are generated and tracked but labeled as paper bets, not real ladder steps

## Known Limitations

1. **No historical odds for initial backtest** — We start collecting odds from day 1 and build the historical dataset over time. Initial model validation is on calibration metrics only, not profitability.
2. **Cold-start uncertainty** — First 20 games of each season have wider confidence intervals. Model widens edge thresholds to compensate.
3. **FanDuel odds approximation** — We pull DraftKings odds from The Odds API as a proxy. FD and DK odds are typically within 5-10 cents on major markets (moneylines, spreads). Totals can diverge more. Users should verify FanDuel odds before placing — if the offered odds are worse by >15 cents, skip the bet.
4. **No same-game parlays** — SGP correlation pricing adds 15-35% hidden vig. Cross-game only.
5. **Manual bet placement** — User places bets manually on FanDuel. No automated bet execution.
6. **Account limiting risk** — If consistently profitable, sportsbooks may limit the account. The system does not address this.

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Shadow flat-bet ROI | > +5% | After 200+ bets |
| Average CLV | > +0.5% | Rolling 100 bets |
| Model Brier score | < 0.24 | Rolling 100 predictions |
| Calibration error | < 3% per bin | Calibration curve |
| Ladder completion | 1 in 50-100 attempts | Over full season |
