"""Tests for ladderbot.models.nhl_model."""
import os
import tempfile

import numpy as np
import pytest

from ladderbot.models.nhl_model import NHLModel


FEATURE_NAMES = [
    "xgf_60_diff", "xga_60_diff", "goalie_gsax_diff",
    "goalie_hdsv_diff", "pp_xg_60_diff", "pk_xga_60_diff",
    "rest_diff", "home_ice", "b2b_travel_diff",
    "pdo_regression_diff",
]


def _make_training_data(n=200, seed=42):
    rng = np.random.RandomState(seed)
    X = rng.randn(n, len(FEATURE_NAMES))
    X[:, 7] = 1.0  # home_ice
    logits = X[:, 0] * 0.5 + X[:, 7] * 0.8 + rng.randn(n) * 0.5
    y = (logits > 0).astype(int)
    totals = 5.5 + X[:, 0] * 0.5 + rng.randn(n) * 1.0
    return X, y, totals


class TestNHLModelTrainPredict:
    def test_train_and_predict(self):
        model = NHLModel(FEATURE_NAMES)
        X, y, _ = _make_training_data()
        model.train(X, y)

        assert model.is_trained
        features = {name: 0.0 for name in FEATURE_NAMES}
        features["home_ice"] = 1.0
        prob = model.predict(features)
        assert 0.0 <= prob <= 1.0

    def test_predict_untrained_raises(self):
        model = NHLModel(FEATURE_NAMES)
        with pytest.raises(RuntimeError, match="not been trained"):
            model.predict({name: 0.0 for name in FEATURE_NAMES})

    def test_predict_total(self):
        model = NHLModel(FEATURE_NAMES)
        X, y, totals = _make_training_data()
        model.train(X, y, totals=totals)

        features = {name: 0.0 for name in FEATURE_NAMES}
        features["home_ice"] = 1.0
        total = model.predict_total(features)
        assert 2.0 < total < 10.0

    def test_predict_total_untrained_raises(self):
        model = NHLModel(FEATURE_NAMES)
        X, y, _ = _make_training_data()
        model.train(X, y)
        with pytest.raises(RuntimeError, match="Totals model"):
            model.predict_total({name: 0.0 for name in FEATURE_NAMES})


class TestNHLModelSaveLoad:
    def test_save_and_load(self):
        model = NHLModel(FEATURE_NAMES)
        X, y, totals = _make_training_data()
        model.train(X, y, totals=totals)

        features = {name: 0.0 for name in FEATURE_NAMES}
        features["home_ice"] = 1.0
        original_prob = model.predict(features)

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name

        try:
            model.save(path)
            loaded = NHLModel.load(path)
            assert loaded.is_trained
            assert abs(loaded.predict(features) - original_prob) < 1e-10
        finally:
            os.unlink(path)


class TestNHLModelCalibrate:
    def test_calibrate_applied(self):
        model = NHLModel(FEATURE_NAMES)
        X, y, _ = _make_training_data()
        model.train(X, y)

        features = {name: 0.0 for name in FEATURE_NAMES}
        features["home_ice"] = 1.0
        raw = model.predict(features)

        model.calibrate([0.4, 0.5, 0.6, 0.7, 0.8], [1, 1, 1, 1, 1])
        calibrated = model.predict(features)
        assert calibrated != raw
