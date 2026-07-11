# tests/test_full_pipeline.py
"""
Integration tests for the full analysis pipeline.
Uses synthetic data — no live network calls.
"""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone


@pytest.fixture
def synthetic_ohlcv():
    rng    = np.random.default_rng(42)
    n      = 400
    dates  = pd.date_range("2021-01-01", periods=n, freq="B", tz="UTC")
    prices = 150.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    return pd.DataFrame({
        "Open":   prices * (1 + rng.uniform(-0.003, 0.003, n)),
        "High":   prices * (1 + rng.uniform(0.005, 0.015, n)),
        "Low":    prices * (1 - rng.uniform(0.005, 0.015, n)),
        "Close":  prices,
        "Volume": rng.uniform(1e7, 5e7, n),
    }, index=dates)


def test_feature_matrix_no_lookahead(synthetic_ohlcv):
    """Features at bar t must not use data from bar t+1."""
    from ml.features.technical_indicators import build_feature_matrix

    df = synthetic_ohlcv
    t  = 100

    ft   = build_feature_matrix(df.iloc[:t + 1],  drop_na=False).iloc[-1]
    full = build_feature_matrix(df.iloc[:t + 10], drop_na=False).iloc[t]

    for col in ft.index:
        if col in full.index and col not in ["Open","High","Low","Close","Volume"]:
            a, b = ft[col], full[col]
            if pd.notna(a) and pd.notna(b):
                assert abs(float(a) - float(b)) < 1e-8, (
                    f"LOOKAHEAD DETECTED in '{col}': "
                    f"t={float(a):.6f} vs full={float(b):.6f}"
                )


def test_risk_engine_never_exceeds_max_position(synthetic_ohlcv):
    """Position size must never exceed max_position_pct of capital."""
    from backend.services.risk_engine import RiskEngine, RiskTolerance, RISK_PROFILES

    engine  = RiskEngine()
    capital = 50_000.0

    for risk_tol in RiskTolerance:
        params = RISK_PROFILES[risk_tol]
        for prob in [0.50, 0.60, 0.70, 0.80, 0.90]:
            sizing = engine.compute_position_size(
                capital=capital, win_probability=prob,
                current_price=100.0, atr=2.0,
                risk_tolerance=risk_tol, confidence=0.9,
            )
            pct = sizing["position_value_usd"] / capital
            assert pct <= params.max_position_pct + 0.001, (
                f"Position {pct:.3f} exceeds max {params.max_position_pct} "
                f"for {risk_tol} at prob={prob}"
            )


def test_kelly_negative_edge_gives_zero():
    """Kelly must return 0 when win probability implies negative edge."""
    from backend.services.risk_engine import RiskEngine, RiskTolerance

    engine = RiskEngine()
    sizing = engine.compute_position_size(
        capital=10_000, win_probability=0.30,
        current_price=100.0, atr=2.0,
        risk_tolerance=RiskTolerance.MODERATE, confidence=0.8,
    )
    assert sizing["position_value_usd"] == 0.0,         "Negative-edge scenario should return zero position size"


def test_monte_carlo_prob_bounds(synthetic_ohlcv):
    """Monte Carlo probabilities must be in [0, 1]."""
    from ml.risk.monte_carlo import run_monte_carlo

    log_returns = np.log(
        synthetic_ohlcv["Close"] / synthetic_ohlcv["Close"].shift(1)
    ).dropna()

    result = run_monte_carlo(
        current_price=150.0, log_returns=log_returns,
        horizon_days=10, n_simulations=1000, random_seed=42,
    )

    assert 0 <= result.prob_positive_return <= 1
    assert 0 <= result.prob_10pct_loss <= 1
    assert 0 <= result.prob_20pct_loss <= 1
    assert result.prob_20pct_loss <= result.prob_10pct_loss
    assert result.var_95_pct >= 0
    assert result.cvar_95_pct >= result.var_95_pct, "CVaR must be >= VaR"
    assert result.p5 < result.p50 < result.p95,     "Percentiles must be ordered"


def test_data_validator_rejects_negative_prices():
    """Validator must remove rows with negative prices."""
    from data_pipeline.validators.ohlcv_validator import validate_ohlcv_dataframe

    rng   = np.random.default_rng(0)
    dates = pd.date_range("2022-01-01", periods=50, freq="B", tz="UTC")
    df    = pd.DataFrame({
        "Open":   rng.uniform(90, 110, 50),
        "High":   rng.uniform(105, 115, 50),
        "Low":    rng.uniform(85, 95, 50),
        "Close":  rng.uniform(90, 110, 50),
        "Volume": rng.uniform(1e6, 1e7, 50),
    }, index=dates)
    df.iloc[25, df.columns.get_loc("Close")] = -50.0

    cleaned = validate_ohlcv_dataframe(df, "TEST")
    assert (cleaned["Close"] >= 0).all(), "Negative prices not removed"
    assert len(cleaned) < len(df),        "Row with negative price not dropped"


def test_ohlcv_record_validates_all_bad_inputs():
    """OHLCVRecord must reject all known-bad input patterns."""
    from data_pipeline.collectors.base import OHLCVRecord
    now = datetime.now(timezone.utc)

    bad_inputs = [
        dict(symbol="X",interval="1d",ts=now,open=100,high=90,low=95,close=92,volume=1e6),   # H < L
        dict(symbol="X",interval="1d",ts=now,open=100,high=105,low=95,close=-1,volume=1e6),  # neg close
        dict(symbol="X",interval="1d",ts=now,open=-1,high=105,low=95,close=100,volume=1e6),  # neg open
        dict(symbol="X",interval="1d",ts=now,open=100,high=105,low=95,close=100,volume=-1),  # neg vol
    ]
    for kwargs in bad_inputs:
        try:
            OHLCVRecord(**kwargs)
            assert False, f"Should have raised ValueError for {kwargs}"
        except ValueError:
            pass  # Expected


def test_walk_forward_no_future_leakage():
    """WalkForwardSplitter: all train indices must precede test indices."""
    from ml.backtesting.engine import WalkForwardSplitter

    X = pd.DataFrame({"v": range(600)})
    for train_idx, test_idx in WalkForwardSplitter(
            n_splits=5, test_size=63, gap=5, min_train_size=100).split(X):
        assert int(train_idx.max()) < int(test_idx.min()),             f"Future leakage: train max={train_idx.max()} >= test min={test_idx.min()}"
