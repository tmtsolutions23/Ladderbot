"""Tests for ladderbot.models.nhl_totals."""
import pytest
import numpy as np

from ladderbot.models.nhl_totals import DixonColesTotals


class TestDixonColesTotals:
    def test_fit_converges(self):
        # Typical NHL scoring: ~3 home goals, ~2.5 away
        rng = np.random.RandomState(42)
        home = rng.poisson(3.0, 100)
        away = rng.poisson(2.5, 100)

        model = DixonColesTotals()
        model.fit(home, away)

        assert model.is_fitted
        assert model._home_attack is not None
        assert model._away_attack is not None
        assert model._rho is not None
        # Fitted rates should be near the true means
        assert abs(model._home_attack - 3.0) < 0.5
        assert abs(model._away_attack - 2.5) < 0.5

    def test_fit_empty_raises(self):
        model = DixonColesTotals()
        with pytest.raises(ValueError):
            model.fit([], [])

    def test_fit_length_mismatch_raises(self):
        model = DixonColesTotals()
        with pytest.raises(ValueError):
            model.fit([1, 2, 3], [1, 2])


class TestTauCorrection:
    def test_tau_0_0(self):
        tau = DixonColesTotals._tau(0, 0, 2.5, 2.5, -0.1)
        assert tau == 1.0 - 2.5 * 2.5 * (-0.1)
        assert tau > 1.0  # Negative rho makes low scores more likely

    def test_tau_0_1(self):
        tau = DixonColesTotals._tau(0, 1, 2.5, 2.5, -0.1)
        assert tau == 1.0 + 2.5 * (-0.1)
        assert tau < 1.0

    def test_tau_1_0(self):
        tau = DixonColesTotals._tau(1, 0, 2.5, 2.5, -0.1)
        assert tau == 1.0 + 2.5 * (-0.1)
        assert tau < 1.0

    def test_tau_1_1(self):
        tau = DixonColesTotals._tau(1, 1, 2.5, 2.5, -0.1)
        assert tau == 1.0 - (-0.1)
        assert tau > 1.0

    def test_tau_high_scores_are_one(self):
        for x in range(2, 8):
            for y in range(2, 8):
                assert DixonColesTotals._tau(x, y, 2.5, 2.5, -0.1) == 1.0


class TestPredictTotalProbs:
    def test_probs_sum_to_one(self):
        model = DixonColesTotals()
        rng = np.random.RandomState(42)
        model.fit(rng.poisson(3.0, 100), rng.poisson(2.5, 100))

        probs = model.predict_total_probs(total_line=5.5)
        total = probs["over"] + probs["under"]
        assert abs(total - 1.0) < 0.01

    def test_higher_attack_means_more_over(self):
        model = DixonColesTotals()
        rng = np.random.RandomState(42)
        model.fit(rng.poisson(3.0, 100), rng.poisson(2.5, 100))

        # Low scoring teams
        low = model.predict_total_probs(
            home_attack=1.5, home_defense=1.0,
            away_attack=1.5, away_defense=1.0,
            total_line=5.5,
        )

        # High scoring teams
        high = model.predict_total_probs(
            home_attack=3.5, home_defense=1.0,
            away_attack=3.5, away_defense=1.0,
            total_line=5.5,
        )

        assert high["over"] > low["over"]

    def test_custom_total_line(self):
        model = DixonColesTotals()
        rng = np.random.RandomState(42)
        model.fit(rng.poisson(3.0, 100), rng.poisson(2.5, 100))

        low_line = model.predict_total_probs(total_line=4.5)
        high_line = model.predict_total_probs(total_line=7.5)

        # Higher line should have more under
        assert high_line["under"] > low_line["under"]

    def test_not_fitted_no_rates_raises(self):
        model = DixonColesTotals()
        with pytest.raises(RuntimeError):
            model.predict_total_probs(total_line=5.5)

    def test_with_explicit_rates_no_fit_needed(self):
        model = DixonColesTotals()
        # Provide explicit rates so no fit is needed
        # Still need rho, which defaults to 0.0 when not fitted
        probs = model.predict_total_probs(
            home_attack=3.0, home_defense=1.0,
            away_attack=2.5, away_defense=1.0,
            total_line=5.5,
        )
        assert 0.0 < probs["over"] < 1.0
        assert 0.0 < probs["under"] < 1.0
