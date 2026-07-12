import pytest
import numpy as np
import pandas as pd
from ml.features.technical_indicators import build_feature_matrix, compute_rsi, compute_atr

def make_test_ohlcv(n=400):
    rng = np.random.default_rng(42)
    dates = pd.date_range("2021-01-01", periods=n, freq="B", tz="UTC")
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    return pd.DataFrame({
        "Open": prices * (1 + rng.uniform(-0.003, 0.003, n)),
        "High": prices * (1 + rng.uniform(0.005, 0.015, n)),
        "Low": prices * (1 - rng.uniform(0.005, 0.015, n)),
        "Close": prices,
        "Volume": rng.uniform(1e6, 5e6, n),
    }, index=dates)

def test_rsi_bounds():
    df = make_test_ohlcv(100)
    rsi = compute_rsi(df["Close"])
    
    # Assert RSI is within [0, 100] bounds
    valid_rsi = rsi.dropna()
    assert len(valid_rsi) > 0
    assert (valid_rsi >= 0.0).all()
    assert (valid_rsi <= 100.0).all()

def test_atr_positivity():
    df = make_test_ohlcv(100)
    atr = compute_atr(df["High"], df["Low"], df["Close"])
    
    # Assert ATR is strictly positive where calculated
    valid_atr = atr.dropna()
    assert len(valid_atr) > 0
    assert (valid_atr > 0.0).all()

def test_no_lookahead_at_bars():
    """Features at bar t must not use data from bar t+1."""
    df = make_test_ohlcv(400)
    
    # Check bounds at index 50, 100, 200, 300
    for t in [50, 100, 200, 300]:
        # Feature matrix built on data ONLY up to t
        sliced_features = build_feature_matrix(df.iloc[:t + 1], drop_na=False).iloc[-1]
        
        # Feature matrix built on data up to t + 50, but we evaluate the row at t
        full_features = build_feature_matrix(df.iloc[:t + 51], drop_na=False).iloc[t]
        
        for col in sliced_features.index:
            if col in full_features.index and col not in ["Open", "High", "Low", "Close", "Volume"] and not col.startswith("regime_") and not col.startswith("garch_"):
                val_sliced = sliced_features[col]
                val_full = full_features[col]
                if pd.notna(val_sliced) and pd.notna(val_full):
                    assert abs(float(val_sliced) - float(val_full)) < 1e-7, (
                         f"LOOKAHEAD DETECTED in indicator '{col}' at bar {t}: "
                         f"sliced value = {val_sliced} vs full value = {val_full}"
                    )

def test_garch_and_hmm_features():
    df = make_test_ohlcv(200)
    features = build_feature_matrix(df, drop_na=True)
    assert "garch_vol" in features.columns
    assert "regime_entropy" in features.columns
    regime_cols = [col for col in features.columns if col.startswith("regime_") and col != "regime_entropy"]
    assert len(regime_cols) > 0
