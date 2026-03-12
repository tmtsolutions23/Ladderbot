"""Dixon-Coles modified Poisson model for NHL totals.

Models home and away goal-scoring as correlated Poisson processes with
a correction factor for low-scoring outcomes (0-0, 1-0, 0-1, 1-1).
"""
import math
from typing import Optional

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson


class DixonColesTotals:
    """Dixon-Coles bivariate Poisson model for NHL game totals.

    Fits home/away scoring rates with a dependence parameter (rho)
    that corrects for the empirical over-representation of low scores.
    """

    def __init__(self):
        self._home_attack: Optional[float] = None
        self._away_attack: Optional[float] = None
        self._rho: Optional[float] = None
        self._fitted = False

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @staticmethod
    def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
        """Dixon-Coles correction factor for low-scoring outcomes.

        Adjusts the independent Poisson probability for scores (0,0),
        (1,0), (0,1), and (1,1) using the dependence parameter rho.

        Args:
            x: Home goals.
            y: Away goals.
            lam: Home team expected goals (lambda).
            mu: Away team expected goals (mu).
            rho: Dependence parameter. Negative = low scores more likely.

        Returns:
            Correction factor (multiply with independent Poisson prob).
        """
        if x == 0 and y == 0:
            return 1.0 - lam * mu * rho
        elif x == 0 and y == 1:
            return 1.0 + mu * rho
        elif x == 1 and y == 0:
            return 1.0 + lam * rho
        elif x == 1 and y == 1:
            return 1.0 - rho
        else:
            return 1.0

    def _neg_log_likelihood(
        self,
        params: np.ndarray,
        home_goals: np.ndarray,
        away_goals: np.ndarray,
    ) -> float:
        """Negative log-likelihood for the Dixon-Coles model.

        Args:
            params: Array [log_lam, log_mu, rho].
            home_goals: Observed home goals per game.
            away_goals: Observed away goals per game.

        Returns:
            Negative log-likelihood (to minimize).
        """
        log_lam, log_mu, rho = params
        lam = math.exp(log_lam)
        mu = math.exp(log_mu)

        ll = 0.0
        for hg, ag in zip(home_goals, away_goals):
            hg_int = int(hg)
            ag_int = int(ag)

            # Independent Poisson probabilities
            p_home = poisson.pmf(hg_int, lam)
            p_away = poisson.pmf(ag_int, mu)

            tau = self._tau(hg_int, ag_int, lam, mu, rho)

            prob = p_home * p_away * tau
            if prob <= 0:
                prob = 1e-15

            ll += math.log(prob)

        return -ll

    def fit(
        self,
        home_goals: list[int] | np.ndarray,
        away_goals: list[int] | np.ndarray,
    ) -> None:
        """Fit the model via MLE using scipy.optimize.minimize.

        Args:
            home_goals: Array of home goals scored per game.
            away_goals: Array of away goals scored per game.

        Raises:
            ValueError: If inputs are empty or different lengths.
        """
        home_goals = np.asarray(home_goals, dtype=float)
        away_goals = np.asarray(away_goals, dtype=float)

        if len(home_goals) == 0:
            raise ValueError("home_goals must be non-empty")
        if len(home_goals) != len(away_goals):
            raise ValueError("home_goals and away_goals must have same length")

        # Initial guesses: log of mean goals, rho = 0
        init_lam = max(np.mean(home_goals), 0.5)
        init_mu = max(np.mean(away_goals), 0.5)
        x0 = np.array([math.log(init_lam), math.log(init_mu), 0.0])

        # Bounds: log_lam and log_mu unbounded, rho in [-1, 1]
        bounds = [(None, None), (None, None), (-0.99, 0.99)]

        result = minimize(
            self._neg_log_likelihood,
            x0,
            args=(home_goals, away_goals),
            method="L-BFGS-B",
            bounds=bounds,
        )

        if not result.success:
            raise RuntimeError(
                f"Dixon-Coles MLE failed to converge: {result.message}"
            )

        self._home_attack = math.exp(result.x[0])
        self._away_attack = math.exp(result.x[1])
        self._rho = result.x[2]
        self._fitted = True

    def predict_total_probs(
        self,
        home_attack: Optional[float] = None,
        home_defense: Optional[float] = None,
        away_attack: Optional[float] = None,
        away_defense: Optional[float] = None,
        total_line: float = 5.5,
        max_goals: int = 12,
    ) -> dict[str, float]:
        """Predict over/under probabilities for a given total line.

        If per-team attack/defense rates are provided, uses them to compute
        expected goals. Otherwise falls back to the fitted league-average rates.

        Expected goals:
            home_expected = home_attack * away_defense (if provided)
            away_expected = away_attack * home_defense (if provided)

        Args:
            home_attack: Home team attacking strength.
            home_defense: Home team defensive weakness (higher = worse defense).
            away_attack: Away team attacking strength.
            away_defense: Away team defensive weakness.
            total_line: The book's total line (e.g., 5.5).
            max_goals: Max goals per team to sum over.

        Returns:
            Dict with 'over' and 'under' probabilities.

        Raises:
            RuntimeError: If model not fitted and no rates provided.
        """
        # Determine expected goals
        if home_attack is not None and away_defense is not None:
            lam = home_attack * away_defense
        elif self._fitted:
            lam = self._home_attack
        else:
            raise RuntimeError(
                "Model not fitted and no attack/defense rates provided."
            )

        if away_attack is not None and home_defense is not None:
            mu = away_attack * home_defense
        elif self._fitted:
            mu = self._away_attack
        else:
            raise RuntimeError(
                "Model not fitted and no attack/defense rates provided."
            )

        rho = self._rho if self._fitted else 0.0

        # Compute bivariate probability matrix
        under_prob = 0.0
        over_prob = 0.0
        push_prob = 0.0
        total_prob = 0.0

        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                p_h = poisson.pmf(h, lam)
                p_a = poisson.pmf(a, mu)
                tau = self._tau(h, a, lam, mu, rho)
                prob = p_h * p_a * tau

                total_prob += prob
                total_goals = h + a
                if total_goals < total_line:
                    under_prob += prob
                elif total_goals > total_line:
                    over_prob += prob
                else:
                    push_prob += prob

        # Normalize over+under only (exclude push probability)
        sum_probs = over_prob + under_prob
        if sum_probs > 0:
            over_prob /= sum_probs
            under_prob /= sum_probs

        return {"over": over_prob, "under": under_prob}
