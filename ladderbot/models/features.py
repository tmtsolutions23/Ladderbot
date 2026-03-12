"""Feature engineering pipeline for LadderBot.

Computes differential features for NBA and NHL game predictions.
All features are computed as (home - away) differentials unless noted.
"""
import math
from datetime import date, timedelta
from typing import Any, Protocol


class StatsClient(Protocol):
    """Protocol for stats data providers."""
    def get_team_stats(self, team: str, stat: str, window: int = 20) -> float: ...
    def get_recent_games(self, team: str, n: int = 10) -> list[dict]: ...


class InjuryClient(Protocol):
    """Protocol for injury data providers."""
    def get_injury_impact(self, team: str) -> float: ...


# ---------------------------------------------------------------------------
# Arena coordinates: lat/lon for all 30 NBA + 32 NHL teams
# Keys are standard team abbreviations
# ---------------------------------------------------------------------------
ARENA_COORDS: dict[str, tuple[float, float]] = {
    # NBA Teams (30)
    "ATL": (33.7573, -84.3963),   # State Farm Arena
    "BOS": (42.3662, -71.0621),   # TD Garden
    "BKN": (40.6826, -73.9754),   # Barclays Center
    "CHA": (35.2251, -80.8392),   # Spectrum Center
    "CHI": (41.8807, -87.6742),   # United Center
    "CLE": (41.4965, -81.6882),   # Rocket Mortgage FieldHouse
    "DAL": (32.7905, -96.8103),   # American Airlines Center
    "DEN": (39.7487, -105.0077),  # Ball Arena
    "DET": (42.3410, -83.0553),   # Little Caesars Arena
    "GSW": (37.7680, -122.3877),  # Chase Center
    "HOU": (29.7508, -95.3621),   # Toyota Center
    "IND": (39.7640, -86.1555),   # Gainbridge Fieldhouse
    "LAC": (33.9456, -118.3410),  # Intuit Dome
    "LAL": (34.0430, -118.2673),  # Crypto.com Arena
    "MEM": (35.1382, -90.0506),   # FedExForum
    "MIA": (25.7814, -80.1870),   # Kaseya Center
    "MIL": (43.0451, -87.9174),   # Fiserv Forum
    "MIN": (44.9795, -93.2761),   # Target Center
    "NOP": (29.9490, -90.0821),   # Smoothie King Center
    "NYK": (40.7505, -73.9934),   # Madison Square Garden
    "OKC": (35.4634, -97.5151),   # Paycom Center
    "ORL": (28.5392, -81.3839),   # Amway Center
    "PHI": (39.9012, -75.1720),   # Wells Fargo Center
    "PHX": (33.4457, -112.0712),  # Footprint Center
    "POR": (45.5316, -122.6668),  # Moda Center
    "SAC": (38.5802, -121.4997),  # Golden 1 Center
    "SAS": (29.4270, -98.4375),   # Frost Bank Center
    "TOR": (43.6435, -79.3791),   # Scotiabank Arena
    "UTA": (40.7683, -111.9011),  # Delta Center
    "WAS": (38.8981, -77.0209),   # Capital One Arena
    # NHL Teams (32)
    "ANA": (33.8078, -117.8765),  # Honda Center
    "ARI": (33.5321, -112.2613),  # Mullett Arena (Arizona Coyotes / Utah)
    "BUF": (42.8750, -78.8764),   # KeyBank Center
    "CGY": (51.0375, -114.0519),  # Scotiabank Saddledome
    "CAR": (35.8031, -78.7220),   # PNC Arena
    "CBJ": (39.9691, -83.0060),   # Nationwide Arena
    "COL": (39.7487, -105.0077),  # Ball Arena (shared with DEN)
    "DAL_NHL": (32.7905, -96.8103),  # American Airlines Center (shared)
    "EDM": (53.5461, -113.4938),  # Rogers Place
    "FLA": (26.1584, -80.3256),   # Amerant Bank Arena
    "LAK": (34.0430, -118.2673),  # Crypto.com Arena (shared with LAL)
    "MIN_NHL": (44.9447, -93.1010),  # Xcel Energy Center (St. Paul)
    "MTL": (45.4961, -73.5693),   # Bell Centre
    "NSH": (36.1592, -86.7786),   # Bridgestone Arena
    "NJD": (40.7334, -74.1712),   # Prudential Center
    "NYI": (40.6572, -73.5260),   # UBS Arena
    "NYR": (40.7505, -73.9934),   # Madison Square Garden (shared with NYK)
    "OTT": (45.2969, -75.9272),   # Canadian Tire Centre
    "PHI_NHL": (39.9012, -75.1720),  # Wells Fargo Center (shared)
    "PIT": (40.4396, -79.9891),   # PPG Paints Arena
    "SEA": (47.6220, -122.3540),  # Climate Pledge Arena
    "SJS": (37.3327, -121.9010),  # SAP Center
    "STL": (38.6268, -90.2027),   # Enterprise Center
    "TBL": (27.9425, -82.4519),   # Amalie Arena
    "UTA_NHL": (40.7683, -111.9011),  # Delta Center (shared with UTA)
    "VAN": (49.2778, -123.1088),  # Rogers Arena
    "VGK": (36.1029, -115.1785),  # T-Mobile Arena
    "WPG": (49.8928, -97.1437),   # Canada Life Centre
    "WSH": (38.8981, -77.0209),   # Capital One Arena (shared with WAS)
    "BOS_NHL": (42.3662, -71.0621),  # TD Garden (shared with BOS)
    "CHI_NHL": (41.8807, -87.6742),  # United Center (shared with CHI)
    "DET_NHL": (42.3410, -83.0553),  # Little Caesars Arena (shared)
    "TOR_NHL": (43.6435, -79.3791),  # Scotiabank Arena (shared)
}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in miles between two lat/lon points.

    Uses the haversine formula for great-circle distance.

    Args:
        lat1, lon1: Latitude/longitude of point 1 (degrees).
        lat2, lon2: Latitude/longitude of point 2 (degrees).

    Returns:
        Distance in miles.
    """
    R = 3958.8  # Earth radius in miles

    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def _compute_rest_days(game_date: date, recent_games: list[dict]) -> int:
    """Compute rest days for a team before a game.

    Args:
        game_date: Date of the upcoming game.
        recent_games: List of recent game dicts with 'date' key (date objects).

    Returns:
        0 if back-to-back (B2B), 1 if one day rest, 2 if two days, 3 if 3+.
    """
    if not recent_games:
        return 3  # Default: well-rested if no data

    # Find the most recent game before game_date
    game_dates = []
    for g in recent_games:
        gd = g.get("date")
        if gd is None:
            continue
        if isinstance(gd, str):
            gd = date.fromisoformat(gd)
        if gd < game_date:
            game_dates.append(gd)

    if not game_dates:
        return 3

    last_game = max(game_dates)
    days_off = (game_date - last_game).days - 1  # subtract 1: game day itself

    if days_off <= 0:
        return 0  # B2B
    elif days_off == 1:
        return 1
    elif days_off == 2:
        return 2
    else:
        return 3


def _cold_start_blend(
    current: float,
    prior: float,
    games_played: int,
    roster_changes: int = 0,
    cold_start_games: int = 20,
) -> float:
    """Blend current-season and prior-season metrics during cold start.

    For the first `cold_start_games` games:
      current_weight = games_played / cold_start_games
      prior_weight   = (cold_start_games - games_played) / cold_start_games
      prior_weight  *= (1 - 0.05 * roster_changes)  # penalty per roster move

    After cold start, returns current value only.

    Args:
        current: Current-season metric value.
        prior: Prior-season metric value.
        games_played: Games played this season.
        roster_changes: Number of significant roster changes.
        cold_start_games: Number of games for cold-start window.

    Returns:
        Blended metric value.
    """
    if games_played >= cold_start_games:
        return current

    current_weight = games_played / cold_start_games
    prior_weight = (cold_start_games - games_played) / cold_start_games

    # Reduce prior weight by 5% per roster change, floor at 0
    roster_penalty = max(0.0, 1.0 - 0.05 * roster_changes)
    prior_weight *= roster_penalty

    # Renormalize weights
    total_weight = current_weight + prior_weight
    if total_weight == 0:
        return current

    return (current * current_weight + prior * prior_weight) / total_weight


def build_nba_features(
    home: str,
    away: str,
    game_date: date,
    stats_client: Any,
    injury_client: Any,
) -> dict[str, float]:
    """Build NBA feature vector as home-minus-away differentials.

    Features (10 total):
        net_rating_diff: Pace-adjusted net rating differential
        off_efg_diff: Offensive eFG% differential
        def_efg_diff: Defensive eFG% allowed differential
        tov_pct_diff: Turnover % differential
        orb_pct_diff: Offensive rebound % differential
        ft_rate_diff: Free throw rate differential
        rest_diff: Rest days differential (home - away)
        home_court: Always 1.0 (home perspective)
        travel_dist_diff: Travel distance differential (miles, last 5 days)
        injury_impact_diff: Injury impact differential (sum of missing player EPM)

    Args:
        home: Home team abbreviation.
        away: Away team abbreviation.
        game_date: Date of the game.
        stats_client: Object implementing StatsClient protocol.
        injury_client: Object implementing InjuryClient protocol.

    Returns:
        Dict mapping feature names to float values.
    """
    # Team stats differentials
    home_net = stats_client.get_team_stats(home, "net_rating", window=20)
    away_net = stats_client.get_team_stats(away, "net_rating", window=20)

    home_off_efg = stats_client.get_team_stats(home, "off_efg_pct", window=15)
    away_off_efg = stats_client.get_team_stats(away, "off_efg_pct", window=15)

    home_def_efg = stats_client.get_team_stats(home, "def_efg_pct", window=15)
    away_def_efg = stats_client.get_team_stats(away, "def_efg_pct", window=15)

    home_tov = stats_client.get_team_stats(home, "tov_pct", window=15)
    away_tov = stats_client.get_team_stats(away, "tov_pct", window=15)

    home_orb = stats_client.get_team_stats(home, "orb_pct", window=10)
    away_orb = stats_client.get_team_stats(away, "orb_pct", window=10)

    home_ft = stats_client.get_team_stats(home, "ft_rate", window=10)
    away_ft = stats_client.get_team_stats(away, "ft_rate", window=10)

    # Rest days
    home_recent = stats_client.get_recent_games(home, n=5)
    away_recent = stats_client.get_recent_games(away, n=5)
    home_rest = _compute_rest_days(game_date, home_recent)
    away_rest = _compute_rest_days(game_date, away_recent)

    # Travel distance (approximation: distance from last game to this arena)
    home_coord = ARENA_COORDS.get(home)
    away_coord = ARENA_COORDS.get(away)

    # Home team travels 0 (playing at home); away team travels to home arena
    if home_coord is not None and away_coord is not None:
        away_travel = _haversine(away_coord[0], away_coord[1],
                                 home_coord[0], home_coord[1])
    else:
        away_travel = 0.0  # Unknown team — use 0 rather than bogus distance

    # Injury impact
    home_injury = injury_client.get_injury_impact(home)
    away_injury = injury_client.get_injury_impact(away)

    return {
        "net_rating_diff": home_net - away_net,
        "off_efg_diff": home_off_efg - away_off_efg,
        "def_efg_diff": home_def_efg - away_def_efg,
        "tov_pct_diff": home_tov - away_tov,
        "orb_pct_diff": home_orb - away_orb,
        "ft_rate_diff": home_ft - away_ft,
        "rest_diff": float(home_rest - away_rest),
        "home_court": 1.0,
        "travel_dist_diff": -away_travel,  # Negative = away team traveled more
        "injury_impact_diff": home_injury - away_injury,
    }


def build_nhl_features(
    home: str,
    away: str,
    game_date: date,
    stats_client: Any,
    injury_client: Any,
) -> dict[str, float]:
    """Build NHL feature vector as home-minus-away differentials.

    Features (10 total):
        xgf_60_diff: 5v5 expected goals for per 60 differential
        xga_60_diff: 5v5 expected goals against per 60 differential
        goalie_gsax_diff: Goalie GSAx differential
        goalie_hdsv_diff: Goalie high-danger save % differential
        pp_xg_60_diff: Power play xG/60 differential
        pk_xga_60_diff: Penalty kill xGA/60 differential
        rest_diff: Rest days differential
        home_ice: Always 1.0
        b2b_travel_diff: Back-to-back + travel composite differential
        pdo_regression_diff: PDO regression signal differential

    Args:
        home: Home team abbreviation.
        away: Away team abbreviation.
        game_date: Date of the game.
        stats_client: Object implementing StatsClient protocol.
        injury_client: Object implementing InjuryClient protocol.

    Returns:
        Dict mapping feature names to float values.
    """
    home_xgf = stats_client.get_team_stats(home, "xgf_60", window=20)
    away_xgf = stats_client.get_team_stats(away, "xgf_60", window=20)

    home_xga = stats_client.get_team_stats(home, "xga_60", window=20)
    away_xga = stats_client.get_team_stats(away, "xga_60", window=20)

    home_gsax = stats_client.get_team_stats(home, "goalie_gsax", window=15)
    away_gsax = stats_client.get_team_stats(away, "goalie_gsax", window=15)

    home_hdsv = stats_client.get_team_stats(home, "goalie_hdsv_pct", window=15)
    away_hdsv = stats_client.get_team_stats(away, "goalie_hdsv_pct", window=15)

    home_pp = stats_client.get_team_stats(home, "pp_xg_60", window=25)
    away_pp = stats_client.get_team_stats(away, "pp_xg_60", window=25)

    home_pk = stats_client.get_team_stats(home, "pk_xga_60", window=25)
    away_pk = stats_client.get_team_stats(away, "pk_xga_60", window=25)

    # Rest / B2B
    home_recent = stats_client.get_recent_games(home, n=5)
    away_recent = stats_client.get_recent_games(away, n=5)
    home_rest = _compute_rest_days(game_date, home_recent)
    away_rest = _compute_rest_days(game_date, away_recent)

    # Travel distance for B2B composite
    home_coord = ARENA_COORDS.get(home) or ARENA_COORDS.get(f"{home}_NHL")
    away_coord = ARENA_COORDS.get(away) or ARENA_COORDS.get(f"{away}_NHL")
    if home_coord is not None and away_coord is not None:
        away_travel = _haversine(away_coord[0], away_coord[1],
                                 home_coord[0], home_coord[1])
    else:
        away_travel = 0.0

    # B2B travel composite: penalize B2B more if traveled far
    home_b2b = 1.0 if home_rest == 0 else 0.0
    away_b2b = 1.0 if away_rest == 0 else 0.0
    # Normalize travel to 0-1 scale (max ~3000 miles)
    away_travel_norm = min(away_travel / 3000.0, 1.0)
    b2b_travel_home = home_b2b * 0.0  # Home doesn't travel
    b2b_travel_away = away_b2b * (0.5 + 0.5 * away_travel_norm)

    # PDO regression: (current PDO - 100), higher = due for regression down
    home_pdo = stats_client.get_team_stats(home, "pdo", window=20)
    away_pdo = stats_client.get_team_stats(away, "pdo", window=20)

    return {
        "xgf_60_diff": home_xgf - away_xgf,
        "xga_60_diff": home_xga - away_xga,
        "goalie_gsax_diff": home_gsax - away_gsax,
        "goalie_hdsv_diff": home_hdsv - away_hdsv,
        "pp_xg_60_diff": home_pp - away_pp,
        "pk_xga_60_diff": home_pk - away_pk,
        "rest_diff": float(home_rest - away_rest),
        "home_ice": 1.0,
        "b2b_travel_diff": b2b_travel_home - b2b_travel_away,
        "pdo_regression_diff": (home_pdo - 100.0) - (away_pdo - 100.0),
    }
