"""Tests for ladderbot.models.calibration."""
import pytest

from ladderbot.models.calibration import ModelCalibration


class TestBrierScore:
    def test_perfect_predictions(self):
        preds = [1.0, 0.0, 1.0, 0.0]
        actuals = [1, 0, 1, 0]
        assert ModelCalibration.brier_score(preds, actuals) == 0.0

    def test_worst_predictions(self):
        preds = [0.0, 1.0, 0.0, 1.0]
        actuals = [1, 0, 1, 0]
        assert ModelCalibration.brier_score(preds, actuals) == 1.0

    def test_coin_flip(self):
        preds = [0.5, 0.5, 0.5, 0.5]
        actuals = [1, 0, 1, 0]
        assert ModelCalibration.brier_score(preds, actuals) == 0.25

    def test_between_perfect_and_worst(self):
        preds = [0.7, 0.3, 0.8, 0.2]
        actuals = [1, 0, 1, 0]
        score = ModelCalibration.brier_score(preds, actuals)
        assert 0.0 < score < 0.25  # Better than coin flip

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            ModelCalibration.brier_score([], [])

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            ModelCalibration.brier_score([0.5, 0.5], [1])


class TestCalibrationCurve:
    def test_returns_correct_keys(self):
        preds = [0.1, 0.3, 0.5, 0.7, 0.9]
        actuals = [0, 0, 1, 1, 1]
        result = ModelCalibration.calibration_curve(preds, actuals, n_bins=5)
        assert "bin_edges" in result
        assert "bin_centers" in result
        assert "bin_counts" in result
        assert "predicted_means" in result
        assert "actual_means" in result

    def test_correct_number_of_bins(self):
        preds = [0.1, 0.3, 0.5, 0.7, 0.9]
        actuals = [0, 0, 1, 1, 1]
        result = ModelCalibration.calibration_curve(preds, actuals, n_bins=5)
        assert len(result["bin_edges"]) == 5

    def test_well_calibrated_diagonal(self):
        """For a perfectly calibrated model, predicted_mean ~= actual_mean."""
        # Create data that is roughly calibrated
        preds = [0.1] * 20 + [0.5] * 20 + [0.9] * 20
        # 10% of low-prob are 1, 50% of mid-prob, 90% of high-prob
        actuals = ([1] * 2 + [0] * 18 +
                   [1] * 10 + [0] * 10 +
                   [1] * 18 + [0] * 2)
        result = ModelCalibration.calibration_curve(preds, actuals, n_bins=10)

        # Check bins with data are close to diagonal
        for pm, am in zip(result["predicted_means"], result["actual_means"]):
            if pm is not None and am is not None:
                assert abs(pm - am) < 0.15, f"pred={pm}, actual={am}"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            ModelCalibration.calibration_curve([], [])


class TestPlattScaling:
    def test_returns_tuple_of_two(self):
        preds = [0.3, 0.4, 0.5, 0.6, 0.7]
        actuals = [0, 0, 1, 1, 1]
        a, b = ModelCalibration.platt_scale(preds, actuals)
        assert isinstance(a, float)
        assert isinstance(b, float)

    def test_monotonic_transform(self):
        """Platt scaling should preserve ordering (monotonic)."""
        preds = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        actuals = [0, 0, 0, 1, 1, 1, 1]
        a, b = ModelCalibration.platt_scale(preds, actuals)

        calibrated = [ModelCalibration.apply_platt(p, a, b) for p in preds]
        # Check monotonically increasing
        for i in range(len(calibrated) - 1):
            assert calibrated[i] <= calibrated[i + 1] + 1e-6

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            ModelCalibration.platt_scale([], [])


class TestApplyPlatt:
    def test_identity_when_a1_b0(self):
        """With a=1, b=0, apply_platt is just sigmoid(x)."""
        result = ModelCalibration.apply_platt(0.0, 1.0, 0.0)
        assert abs(result - 0.5) < 0.01

    def test_output_bounded_0_1(self):
        for raw in [-10.0, -1.0, 0.0, 0.5, 1.0, 10.0]:
            result = ModelCalibration.apply_platt(raw, 2.0, -1.0)
            assert 0.0 <= result <= 1.0

    def test_higher_input_gives_higher_output_positive_a(self):
        r1 = ModelCalibration.apply_platt(0.3, 5.0, -2.0)
        r2 = ModelCalibration.apply_platt(0.7, 5.0, -2.0)
        assert r2 > r1
