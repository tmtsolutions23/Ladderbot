"""Edge detection for LadderBot.

Identifies +EV bets by comparing model probabilities against book-implied
probabilities. Supports moneyline and totals markets.
"""
from typing import Any, Optional

from ladderbot.utils.odds import (
    implied_probability,
    calculate_edge,
    classify_confidence,
    american_to_decimal,
)


def find_ev_bets(
    games: list[dict],
    model_predictions: dict[str, dict],
    odds_data: dict[str, dict],
    config: Optional[dict] = None,
) -> list[dict]:
    """Find all +EV bet opportunities across games.

    For each game, checks moneyline (home/away) and totals (over/under)
    against model predictions, returning bets that exceed the edge threshold.

    Args:
        games: List of game dicts with keys: game_id, sport, home, away.
        model_predictions: Dict mapping game_id to prediction dict with keys:
            home_win_prob (float), predicted_total (float, optional).
        odds_data: Dict mapping game_id to odds dict with keys:
            home_ml (int), away_ml (int), total_line (float),
            over_odds (int), under_odds (int).
        config: Optional config dict with keys:
            min_edge_per_leg (float, default 0.02),
            min_confidence (float, default 0.30),
            max_confidence (float, default 0.75),
            cold_start (bool, default False).

    Returns:
        List of bet dicts sorted by edge descending, each with keys:
            game_id, sport, market, outcome, model_prob, book_odds,
            book_implied_prob, edge, confidence, decimal_odds.
    """
    if config is None:
        config = {}

    min_edge = config.get("min_edge_per_leg", 0.02)
    min_conf = config.get("min_confidence", 0.30)
    max_conf = config.get("max_confidence", 0.75)
    cold_start = config.get("cold_start", False)

    if cold_start:
        min_edge = config.get("min_edge_cold_start", 0.03)

    ev_bets = []

    for game in games:
        game_id = game["game_id"]
        sport = game.get("sport", "unknown")

        preds = model_predictions.get(game_id)
        odds = odds_data.get(game_id)

        if preds is None or odds is None:
            continue

        home_prob = preds.get("home_win_prob")
        if home_prob is None:
            continue

        away_prob = 1.0 - home_prob

        # --- Moneyline: Home ---
        home_ml = odds.get("home_ml")
        if home_ml is not None:
            edge = calculate_edge(home_prob, home_ml)
            if edge >= min_edge and min_conf <= home_prob <= max_conf:
                ev_bets.append({
                    "game_id": game_id,
                    "sport": sport,
                    "market": "moneyline",
                    "outcome": "home",
                    "team": game.get("home", ""),
                    "model_prob": home_prob,
                    "book_odds": home_ml,
                    "book_implied_prob": implied_probability(home_ml),
                    "edge": edge,
                    "confidence": classify_confidence(edge, cold_start),
                    "decimal_odds": american_to_decimal(home_ml),
                })

        # --- Moneyline: Away ---
        away_ml = odds.get("away_ml")
        if away_ml is not None:
            edge = calculate_edge(away_prob, away_ml)
            if edge >= min_edge and min_conf <= away_prob <= max_conf:
                ev_bets.append({
                    "game_id": game_id,
                    "sport": sport,
                    "market": "moneyline",
                    "outcome": "away",
                    "team": game.get("away", ""),
                    "model_prob": away_prob,
                    "book_odds": away_ml,
                    "book_implied_prob": implied_probability(away_ml),
                    "edge": edge,
                    "confidence": classify_confidence(edge, cold_start),
                    "decimal_odds": american_to_decimal(away_ml),
                })

        # --- Totals: Over ---
        predicted_total = preds.get("predicted_total")
        total_line = odds.get("total_line")
        over_odds = odds.get("over_odds")
        under_odds = odds.get("under_odds")

        if predicted_total is not None and total_line is not None:
            # Simple heuristic: if predicted total > line, lean over
            # Use a normal approximation for over/under probability
            # Std dev of NBA totals ~ 12 pts, NHL ~ 1.5 goals
            if sport == "nba":
                std_dev = 12.0
            else:
                std_dev = 1.5

            diff = predicted_total - total_line
            # Approximate P(over) using logistic CDF
            # Scale = std_dev * pi / sqrt(3) ≈ std_dev * 1.814 for normal approx
            # Simplified: use std_dev directly as scale parameter
            over_prob = 1.0 / (1.0 + _exp_safe(-diff / std_dev))
            under_prob = 1.0 - over_prob

            if over_odds is not None:
                edge = calculate_edge(over_prob, over_odds)
                if edge >= min_edge and min_conf <= over_prob <= max_conf:
                    ev_bets.append({
                        "game_id": game_id,
                        "sport": sport,
                        "market": "totals",
                        "outcome": "over",
                        "team": f"{game.get('home', '')}/{game.get('away', '')}",
                        "model_prob": over_prob,
                        "book_odds": over_odds,
                        "book_implied_prob": implied_probability(over_odds),
                        "edge": edge,
                        "confidence": classify_confidence(edge, cold_start),
                        "decimal_odds": american_to_decimal(over_odds),
                        "total_line": total_line,
                        "predicted_total": predicted_total,
                    })

            if under_odds is not None:
                edge = calculate_edge(under_prob, under_odds)
                if edge >= min_edge and min_conf <= under_prob <= max_conf:
                    ev_bets.append({
                        "game_id": game_id,
                        "sport": sport,
                        "market": "totals",
                        "outcome": "under",
                        "team": f"{game.get('home', '')}/{game.get('away', '')}",
                        "model_prob": under_prob,
                        "book_odds": under_odds,
                        "book_implied_prob": implied_probability(under_odds),
                        "edge": edge,
                        "confidence": classify_confidence(edge, cold_start),
                        "decimal_odds": american_to_decimal(under_odds),
                        "total_line": total_line,
                        "predicted_total": predicted_total,
                    })

    # Sort by edge descending
    ev_bets.sort(key=lambda b: b["edge"], reverse=True)
    return ev_bets


def _exp_safe(x: float) -> float:
    """Numerically safe exponential."""
    if x > 500:
        return float("inf")
    if x < -500:
        return 0.0
    import math
    return math.exp(x)


def recalculate_edge_with_fd_odds(
    pick: dict,
    fd_odds: int,
) -> dict:
    """Recalculate edge using actual FanDuel odds.

    Used when a user manually enters FanDuel odds to verify the pick
    is still +EV at the actual available price.

    Args:
        pick: Original pick dict with 'model_prob' and 'book_odds' keys.
        fd_odds: Actual FanDuel American odds.

    Returns:
        Dict with keys:
            original_edge, fd_edge, fd_implied_prob, fd_decimal_odds,
            still_plus_ev, original_odds, fd_odds.
    """
    model_prob = pick["model_prob"]
    original_edge = pick["edge"]

    fd_implied = implied_probability(fd_odds)
    fd_edge = model_prob - fd_implied
    fd_decimal = american_to_decimal(fd_odds)

    # Use the config threshold if available, default to 2%
    min_edge = pick.get("min_edge_threshold", 0.02)

    return {
        "original_odds": pick["book_odds"],
        "fd_odds": fd_odds,
        "original_edge": original_edge,
        "fd_edge": fd_edge,
        "fd_implied_prob": fd_implied,
        "fd_decimal_odds": fd_decimal,
        "still_plus_ev": fd_edge >= min_edge,
        "model_prob": model_prob,
    }
