"""Model calibration utilities for LadderBot.

Provides Brier score computation, calibration curves, and Platt scaling
for recalibrating raw model probabilities.
"""
import math


class ModelCalibration:
    """Static methods for model calibration analysis and correction."""

    @staticmethod
    def brier_score(predictions: list[float], actuals: list[int]) -> float:
        """Compute Brier score: mean squared error of probability forecasts.

        Brier score ranges from 0 (perfect) to 1 (worst).
        A coin-flip model predicting 0.5 always yields Brier = 0.25.

        Args:
            predictions: List of predicted probabilities (0 to 1).
            actuals: List of actual outcomes (0 or 1).

        Returns:
            Brier score as float.

        Raises:
            ValueError: If inputs are empty or different lengths.
        """
        if not predictions or not actuals:
            raise ValueError("Predictions and actuals must be non-empty")
        if len(predictions) != len(actuals):
            raise ValueError(
                f"Length mismatch: {len(predictions)} predictions vs {len(actuals)} actuals"
            )

        n = len(predictions)
        total = sum((p - a) ** 2 for p, a in zip(predictions, actuals))
        return total / n

    @staticmethod
    def calibration_curve(
        predictions: list[float],
        actuals: list[int],
        n_bins: int = 10,
    ) -> dict:
        """Compute calibration curve: predicted vs actual frequency per bin.

        Args:
            predictions: List of predicted probabilities.
            actuals: List of actual outcomes (0 or 1).
            n_bins: Number of bins to divide [0, 1] range.

        Returns:
            Dict with keys:
                bin_edges: list of bin edge pairs [(low, high), ...]
                bin_centers: list of bin center values
                bin_counts: list of counts per bin
                predicted_means: list of mean predicted prob per bin
                actual_means: list of actual frequency per bin
        """
        if not predictions or not actuals:
            raise ValueError("Predictions and actuals must be non-empty")
        if len(predictions) != len(actuals):
            raise ValueError("Length mismatch between predictions and actuals")

        bin_width = 1.0 / n_bins
        bin_edges = []
        bin_centers = []
        bin_counts = []
        predicted_means = []
        actual_means = []

        for i in range(n_bins):
            low = i * bin_width
            high = (i + 1) * bin_width
            bin_edges.append((low, high))
            bin_centers.append((low + high) / 2)

            # Collect predictions in this bin
            bin_preds = []
            bin_acts = []
            for p, a in zip(predictions, actuals):
                if i == n_bins - 1:
                    # Last bin includes upper edge
                    if low <= p <= high:
                        bin_preds.append(p)
                        bin_acts.append(a)
                else:
                    if low <= p < high:
                        bin_preds.append(p)
                        bin_acts.append(a)

            bin_counts.append(len(bin_preds))
            if bin_preds:
                predicted_means.append(sum(bin_preds) / len(bin_preds))
                actual_means.append(sum(bin_acts) / len(bin_acts))
            else:
                predicted_means.append(None)
                actual_means.append(None)

        return {
            "bin_edges": bin_edges,
            "bin_centers": bin_centers,
            "bin_counts": bin_counts,
            "predicted_means": predicted_means,
            "actual_means": actual_means,
        }

    @staticmethod
    def platt_scale(
        predictions: list[float],
        actuals: list[int],
        lr: float = 0.01,
        max_iter: int = 10000,
    ) -> tuple[float, float]:
        """Fit Platt scaling parameters (a, b) via gradient descent.

        Platt scaling fits a sigmoid: calibrated = 1 / (1 + exp(a * raw + b))
        to minimize log-loss on a validation set.

        Args:
            predictions: Raw predicted probabilities.
            actuals: Actual outcomes (0 or 1).
            lr: Learning rate for gradient descent.
            max_iter: Maximum iterations.

        Returns:
            Tuple (a, b) for the sigmoid transform.

        Raises:
            ValueError: If inputs are empty or mismatched.
        """
        if not predictions or not actuals:
            raise ValueError("Predictions and actuals must be non-empty")
        if len(predictions) != len(actuals):
            raise ValueError("Length mismatch between predictions and actuals")

        # Initialize: a=1.0 (identity transform) so gradient reflects actual
        # miscalibration. Starting at a=0.0 collapses all probs to 0.5.
        a = 1.0
        b = 0.0
        n = len(predictions)
        eps = 1e-12

        for _ in range(max_iter):
            grad_a = 0.0
            grad_b = 0.0

            for p, y in zip(predictions, actuals):
                z = a * p + b
                # Numerically stable sigmoid
                if z >= 0:
                    s = 1.0 / (1.0 + math.exp(-z))
                else:
                    ez = math.exp(z)
                    s = ez / (1.0 + ez)

                # For Platt: calibrated = sigmoid(a*x + b)
                # Gradient of log-loss w.r.t. a and b
                diff = s - y
                grad_a += diff * p
                grad_b += diff

            grad_a /= n
            grad_b /= n

            a -= lr * grad_a
            b -= lr * grad_b

            # Early stopping if gradients are tiny
            if abs(grad_a) < eps and abs(grad_b) < eps:
                break

        return (a, b)

    @staticmethod
    def apply_platt(raw_prob: float, a: float, b: float) -> float:
        """Apply Platt scaling to a raw probability.

        calibrated = sigmoid(a * raw_prob + b)

        Args:
            raw_prob: Raw predicted probability.
            a: Platt scaling slope.
            b: Platt scaling intercept.

        Returns:
            Calibrated probability between 0 and 1.
        """
        z = a * raw_prob + b
        # Numerically stable sigmoid
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        else:
            ez = math.exp(z)
            return ez / (1.0 + ez)
