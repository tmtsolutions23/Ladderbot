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


def decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American odds.

    Args:
        decimal_odds: Decimal odds (must be > 1.0).

    Returns:
        American odds as integer (rounded).

    Raises:
        ValueError: If decimal_odds <= 1.0.
    """
    if decimal_odds <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {decimal_odds}")
    if decimal_odds >= 2.0:
        return round((decimal_odds - 1) * 100)
    else:
        return round(-100 / (decimal_odds - 1))


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


def classify_confidence(edge: float, cold_start: bool = False) -> str:
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
