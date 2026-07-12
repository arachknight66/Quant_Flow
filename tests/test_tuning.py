import pytest
import numpy as np
import pandas as pd
from scripts.train_model import run_walk_forward

def test_hyperparameter_tuning_optuna():
    # 1. Setup synthetic data (enough for walk forward folds)
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

    # 2. Run walk forward with tuning
    wf_metrics, model, features = run_walk_forward(df, "AAPL", n_splits=3, tune=True)

    # 3. Assertions
    assert "mean_auc" in wf_metrics
    assert model is not None
    assert features is not None
    # Verify that model has loaded parameters
    assert isinstance(model.model_params, dict)
