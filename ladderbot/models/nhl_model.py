"""NHL prediction model for LadderBot.

Logistic regression for P(home_win) + optional linear regression for totals.
Same interface as NBAModel for consistency.
"""
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.linear_model import LogisticRegression, LinearRegression

from ladderbot.models.calibration import ModelCalibration


class NHLModel:
    """NHL game outcome and totals prediction model.

    Args:
        feature_names: Ordered list of feature names the model expects.
    """

    def __init__(self, feature_names: list[str]):
        self.feature_names = list(feature_names)
        self._classifier: Optional[LogisticRegression] = None
        self._totals_model: Optional[LinearRegression] = None
        self._platt_a: Optional[float] = None
        self._platt_b: Optional[float] = None
        self._trained = False
        self._totals_trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        totals: Optional[np.ndarray] = None,
    ) -> None:
        """Train the model on feature matrix X and outcome labels y.

        Args:
            X: Feature matrix, shape (n_samples, n_features).
            y: Binary outcome vector (1 = home win, 0 = away win).
            totals: Optional total goals vector for totals regression.
        """
        self._classifier = LogisticRegression(
            max_iter=1000,
            solver="lbfgs",
            C=1.0,
        )
        self._classifier.fit(X, y)
        self._trained = True

        if totals is not None:
            self._totals_model = LinearRegression()
            self._totals_model.fit(X, totals)
            self._totals_trained = True

    def predict(self, features_dict: dict[str, float]) -> float:
        """Predict P(home_win) from a feature dictionary.

        Args:
            features_dict: Dict mapping feature names to values.

        Returns:
            Probability of home team winning (0 to 1).

        Raises:
            RuntimeError: If model has not been trained.
        """
        if not self._trained:
            raise RuntimeError("Model has not been trained. Call train() first.")

        X = np.array([[features_dict[f] for f in self.feature_names]])
        raw_prob = self._classifier.predict_proba(X)[0, 1]

        if self._platt_a is not None and self._platt_b is not None:
            return ModelCalibration.apply_platt(raw_prob, self._platt_a, self._platt_b)

        return float(raw_prob)

    def predict_total(self, features_dict: dict[str, float]) -> float:
        """Predict total goals from a feature dictionary.

        Args:
            features_dict: Dict mapping feature names to values.

        Returns:
            Predicted total goals.

        Raises:
            RuntimeError: If totals model has not been trained.
        """
        if not self._totals_trained:
            raise RuntimeError(
                "Totals model has not been trained. Pass totals to train()."
            )

        X = np.array([[features_dict[f] for f in self.feature_names]])
        return float(self._totals_model.predict(X)[0])

    def calibrate(
        self,
        predictions: list[float],
        actuals: list[int],
    ) -> None:
        """Apply Platt scaling calibration from validation data.

        Args:
            predictions: Raw model predicted probabilities.
            actuals: Actual outcomes (1 = home win, 0 = away win).
        """
        self._platt_a, self._platt_b = ModelCalibration.platt_scale(
            predictions, actuals
        )

    def save(self, path: str) -> None:
        """Save model to a pickle file.

        Args:
            path: File path to save to.
        """
        state = {
            "feature_names": self.feature_names,
            "classifier": self._classifier,
            "totals_model": self._totals_model,
            "platt_a": self._platt_a,
            "platt_b": self._platt_b,
            "trained": self._trained,
            "totals_trained": self._totals_trained,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(state, f)

    @classmethod
    def load(cls, path: str) -> "NHLModel":
        """Load model from a pickle file.

        Args:
            path: File path to load from.

        Returns:
            Loaded NHLModel instance.
        """
        with open(path, "rb") as f:
            state = pickle.load(f)

        model = cls(state["feature_names"])
        model._classifier = state["classifier"]
        model._totals_model = state["totals_model"]
        model._platt_a = state["platt_a"]
        model._platt_b = state["platt_b"]
        model._trained = state["trained"]
        model._totals_trained = state["totals_trained"]
        return model
