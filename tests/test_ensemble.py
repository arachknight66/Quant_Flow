import pytest
import numpy as np
import pandas as pd
import shutil
from ml.features.technical_indicators import build_feature_matrix
from ml.models.ensemble_stacker import EnsembleStackerModel

def test_ensemble_stacker_flow():
    # 1. Setup synthetic data
    rng = np.random.default_rng(42)
    n = 200
    dates = pd.date_range("2021-01-01", periods=n, freq="B", tz="UTC")
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    df = pd.DataFrame({
        "Open": prices * 0.99,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Close": prices,
        "Volume": rng.uniform(1e6, 5e6, n),
    }, index=dates)

    features = build_feature_matrix(df, drop_na=False)

    # 2. Instantiate and fit
    stacker = EnsembleStackerModel(prediction_horizon=5, profit_threshold=0.01)
    res = stacker.fit_and_stack(features, df["Close"], n_splits=3)

    assert "mean_auc" in res
    assert res["base_models_count"] == 3

    # 3. Predict
    pred = stacker.predict(features)
    assert "action" in pred
    assert "prob_profit" in pred
    assert len(pred["base_probabilities"]) == 3

    # 4. Save and Load
    test_path = "./ml/artifacts/test_ensemble"
    try:
        stacker.save(test_path)
        loaded = EnsembleStackerModel.load(test_path)
        assert loaded.prediction_horizon == 5
        assert loaded.meta_model is not None
        assert len(loaded.base_models) == 3

        # Test predict with loaded model
        loaded_pred = loaded.predict(features)
        assert loaded_pred["action"] == pred["action"]
    finally:
        shutil.rmtree(test_path, ignore_errors=True)
