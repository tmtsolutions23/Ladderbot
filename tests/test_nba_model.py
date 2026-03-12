"""Tests for ladderbot.models.nba_model."""
import os
import tempfile

import numpy as np
import pytest

from ladderbot.models.nba_model import NBAModel


FEATURE_NAMES = [
    "net_rating_diff", "off_efg_diff", "def_efg_diff",
    "tov_pct_diff", "orb_pct_diff", "ft_rate_diff",
    "rest_diff", "home_court", "travel_dist_diff",
    "injury_impact_diff",
]


def _make_training_data(n=200, seed=42):
    """Generate synthetic training data where home advantage matters."""
    rng = np.random.RandomState(seed)
    X = rng.randn(n, len(FEATURE_NAMES))
    # home_court feature (index 7) strongly predicts outcome
    X[:, 7] = 1.0
    logits = X[:, 0] * 0.5 + X[:, 7] * 1.0 + rng.randn(n) * 0.5
    y = (logits > 0).astype(int)
    totals = 200 + X[:, 0] * 5 + rng.randn(n) * 10
    return X, y, totals


class TestNBAModelTrainPredict:
    def test_train_and_predict(self):
        model = NBAModel(FEATURE_NAMES)
        X, y, _ = _make_training_data()
        model.train(X, y)

        assert model.is_trained

        features = {name: 0.0 for name in FEATURE_NAMES}
        features["home_court"] = 1.0
        prob = model.predict(features)
        assert 0.0 <= prob <= 1.0

    def test_predict_untrained_raises(self):
        model = NBAModel(FEATURE_NAMES)
        features = {name: 0.0 for name in FEATURE_NAMES}
        with pytest.raises(RuntimeError, match="not been trained"):
            model.predict(features)

    def test_predict_total(self):
        model = NBAModel(FEATURE_NAMES)
        X, y, totals = _make_training_data()
        model.train(X, y, totals=totals)

        features = {name: 0.0 for name in FEATURE_NAMES}
        features["home_court"] = 1.0
        total = model.predict_total(features)
        # Should be in reasonable range
        assert 150 < total < 250

    def test_predict_total_untrained_raises(self):
        model = NBAModel(FEATURE_NAMES)
        X, y, _ = _make_training_data()
        model.train(X, y)  # No totals

        features = {name: 0.0 for name in FEATURE_NAMES}
        with pytest.raises(RuntimeError, match="Totals model"):
            model.predict_total(features)

    def test_home_advantage_increases_prob(self):
        model = NBAModel(FEATURE_NAMES)
        X, y, _ = _make_training_data()
        model.train(X, y)

        features_home = {name: 0.0 for name in FEATURE_NAMES}
        features_home["home_court"] = 1.0
        features_home["net_rating_diff"] = 5.0

        features_away = {name: 0.0 for name in FEATURE_NAMES}
        features_away["home_court"] = 1.0
        features_away["net_rating_diff"] = -5.0

        p_strong = model.predict(features_home)
        p_weak = model.predict(features_away)
        assert p_strong > p_weak


class TestNBAModelSaveLoad:
    def test_save_and_load(self):
        model = NBAModel(FEATURE_NAMES)
        X, y, totals = _make_training_data()
        model.train(X, y, totals=totals)

        features = {name: 0.0 for name in FEATURE_NAMES}
        features["home_court"] = 1.0
        original_prob = model.predict(features)
        original_total = model.predict_total(features)

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name

        try:
            model.save(path)
            loaded = NBAModel.load(path)

            assert loaded.is_trained
            assert loaded.feature_names == FEATURE_NAMES
            assert abs(loaded.predict(features) - original_prob) < 1e-10
            assert abs(loaded.predict_total(features) - original_total) < 1e-10
        finally:
            os.unlink(path)


class TestNBAModelCalibrate:
    def test_calibrate_changes_output(self):
        model = NBAModel(FEATURE_NAMES)
        X, y, _ = _make_training_data()
        model.train(X, y)

        features = {name: 0.0 for name in FEATURE_NAMES}
        features["home_court"] = 1.0
        raw_prob = model.predict(features)

        # Calibrate with biased data (all actuals = 1)
        preds = [0.4, 0.5, 0.6, 0.7, 0.8]
        actuals = [1, 1, 1, 1, 1]
        model.calibrate(preds, actuals)

        calibrated_prob = model.predict(features)
        # After calibrating on all-win data, output should shift
        assert calibrated_prob != raw_prob

    def test_calibrate_preserves_save_load(self):
        model = NBAModel(FEATURE_NAMES)
        X, y, _ = _make_training_data()
        model.train(X, y)

        model.calibrate([0.4, 0.5, 0.6], [0, 1, 1])

        features = {name: 0.0 for name in FEATURE_NAMES}
        features["home_court"] = 1.0
        cal_prob = model.predict(features)

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name

        try:
            model.save(path)
            loaded = NBAModel.load(path)
            assert abs(loaded.predict(features) - cal_prob) < 1e-10
        finally:
            os.unlink(path)
