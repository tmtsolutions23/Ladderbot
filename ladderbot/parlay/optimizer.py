"""Parlay optimizer for LadderBot.

Finds the best 2-leg cross-game parlays from a list of +EV bet candidates.
Generates all valid combinations, filters by odds range and edge thresholds,
scores by true expected value, and returns the top picks.
"""
from itertools import combinations

from ladderbot.utils.odds import (
    american_to_decimal,
    decimal_to_american,
    implied_probability,
    parlay_decimal_odds,
)


def find_best_parlays(
    ev_bets: list[dict],
    config: dict,
) -> list[dict]:
    """Find the best 2-leg cross-game parlays from +EV candidates.

    Each bet dict must contain:
        - game_id: str
        - market: str  (h2h, totals, etc.)
        - outcome: str (team abbrev, Over, Under)
        - odds: int  (American odds)
        - model_prob: float  (model predicted probability, 0-1)
        - edge: float  (model_prob - book_implied_prob)
        - sport: str  (nba, nhl)

    Args:
        ev_bets: List of +EV bet candidate dicts.
        config: Configuration dict with parlay settings.

    Returns:
        Up to 3 parlay dicts sorted by parlay_edge descending, each containing:
            - leg1, leg2: the original bet dicts
            - parlay_decimal: combined decimal odds
            - parlay_american: combined American odds
            - parlay_edge: (prob1 * prob2 * decimal) - 1
            - combined_prob: prob1 * prob2
    """
    parlay_config = config.get("parlay", {})
    target_min = parlay_config.get("target_odds_min", 150)
    target_max = parlay_config.get("target_odds_max", 300)
    min_edge = parlay_config.get("min_edge_per_leg", 0.02)

    if len(ev_bets) < 2:
        return []

    parlays = []

    for leg1, leg2 in combinations(ev_bets, 2):
        # Must be from different games
        if leg1["game_id"] == leg2["game_id"]:
            continue

        # Both legs must meet minimum edge
        if leg1["edge"] < min_edge or leg2["edge"] < min_edge:
            continue

        # Calculate combined parlay odds
        dec1 = american_to_decimal(leg1["odds"])
        dec2 = american_to_decimal(leg2["odds"])
        combined_decimal = parlay_decimal_odds([dec1, dec2])
        combined_american = decimal_to_american(combined_decimal)

        # Filter: combined odds must be in target range
        if combined_american < target_min or combined_american > target_max:
            continue

        # Score: true EV of the parlay
        combined_prob = leg1["model_prob"] * leg2["model_prob"]
        parlay_edge = (combined_prob * combined_decimal) - 1

        parlays.append({
            "leg1": leg1,
            "leg2": leg2,
            "parlay_decimal": combined_decimal,
            "parlay_american": combined_american,
            "parlay_edge": parlay_edge,
            "combined_prob": combined_prob,
        })

    # Sort by parlay_edge descending, return top 3
    parlays.sort(key=lambda p: p["parlay_edge"], reverse=True)
    return parlays[:3]
