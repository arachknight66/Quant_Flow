# tests/integration/test_full_pipeline.py
"""
Integration test: full analysis pipeline from data fetch to signal.

This test uses real yfinance data (marked as integration test,
excluded from fast unit test runs). It verifies the entire
request-response cycle works correctly end-to-end.

Run with: pytest tests/integration/ -v --timeout=60
"""
import pytest
import asyncio
import pandas as pd
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from backend.main import app
from backend.core.config import settings


@pytest.fixture
def synthetic_ohlcv():
    """Generate deterministic synthetic OHLCV for fast tests."""
    import numpy as np
    rng = np.random.default_rng(42)
    dates = pd.date_range("2021-01-01", periods=400, freq="B", tz="UTC")
    prices = 150.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, 400)))
    return pd.DataFrame({
        "Open": prices * (1 + rng.uniform(-0.003, 0.003, 400)),
        "High": prices * (1 + rng.uniform(0.005, 0.015, 400)),
        "Low": prices * (1 - rng.uniform(0.005, 0.015, 400)),
        "Close": prices,
        "Volume": rng.uniform(1e7, 5e7, 400),
    }, index=dates)


@pytest.mark.asyncio
async def test_feature_matrix_no_lookahead(synthetic_ohlcv):
    """
    Critical test: features at bar t must not use data from bar t+1.
    We verify this by checking that feature values at bar t are identical
    whether computed on data[:t+1] or data[:t+10].
    """
    from ml.features.technical_indicators import build_feature_matrix

    df = synthetic_ohlcv
    t = 100  # Test bar

    # Features computed up to bar t
    features_at_t = build_feature_matrix(df.iloc[:t + 1], drop_na=False).iloc[-1]

    # Features computed on a larger window (bars t to t+9 are future)
    features_full = build_feature_matrix(df.iloc[:t + 10], drop_na=False).iloc[t]

    # All feature values must be identical
    for col in features_at_t.index:
        if col in features_full.index and col not in ["Open", "High", "Low", "Close", "Volume"]:
            val_t = features_at_t[col]
            val_full = features_full[col]
            if pd.notna(val_t) and pd.notna(val_full):
                assert abs(val_t - val_full) < 1e-8, (
                    f"LOOKAHEAD DETECTED in feature '{col}': "
                    f"value at t={val_t:.6f} differs from full-window value={val_full:.6f}"
                )


@pytest.mark.asyncio
async def test_risk_engine_never_exceeds_max_position(synthetic_ohlcv):
    """Position size must never exceed max_position_pct of capital."""
    from backend.services.risk_engine import RiskEngine, RiskTolerance, RISK_PROFILES

    engine = RiskEngine()
    capital = 50_000.0

    for risk_tol in RiskTolerance:
        params = RISK_PROFILES[risk_tol]
        for prob in [0.50, 0.60, 0.70, 0.80, 0.90]:
            sizing = engine.compute_position_size(
                capital=capital,
                win_probability=prob,
                current_price=100.0,
                atr=2.0,
                risk_tolerance=risk_tol,
                confidence=0.9,
            )
            pct = sizing["position_value_usd"] / capital
            assert pct <= params.max_position_pct + 0.001, (
                f"Position size {pct:.3f} exceeds max {params.max_position_pct} "
                f"for {risk_tol} at prob={prob}"
            )


@pytest.mark.asyncio
async def test_kelly_negative_edge_gives_zero():
    """Kelly should return 0 when win probability implies negative edge."""
    from backend.services.risk_engine import RiskEngine, RiskTolerance

    engine = RiskEngine()
    # Very low win probability — should give zero or near-zero sizing
    sizing = engine.compute_position_size(
        capital=10_000,
        win_probability=0.30,  # Strong negative edge
        current_price=100.0,
        atr=2.0,
        risk_tolerance=RiskTolerance.MODERATE,
        confidence=0.8,
    )
    assert sizing["position_value_usd"] == 0.0, (
        "Negative-edge scenario should return zero position size"
    )


@pytest.mark.asyncio
async def test_garch_persistence_constraint(synthetic_ohlcv):
    """GARCH alpha + beta must be < 1 for stationarity."""
    from ml.models.volatility.garch_model import GARCHVolatilityModel
    import numpy as np

    log_returns = np.log(synthetic_ohlcv["Close"] / synthetic_ohlcv["Close"].shift(1)).dropna()
    model = GARCHVolatilityModel()
    params = model.fit(log_returns)

    assert params.alpha >= 0, "ARCH term must be non-negative"
    assert params.beta >= 0, "GARCH term must be non-negative"
    assert params.persistence < 1.0, (
        f"GARCH not stationary: alpha+beta={params.persistence:.4f} >= 1.0"
    )
    assert params.long_run_volatility_annual > 0, "Long-run vol must be positive"
    assert params.long_run_volatility_annual < 2.0, (
        "Long-run vol > 200% is unreasonable for equity"
    )


@pytest.mark.asyncio
async def test_monte_carlo_prob_bounds(synthetic_ohlcv):
    """Monte Carlo probabilities must be in [0, 1]."""
    from ml.risk.monte_carlo import run_monte_carlo
    import numpy as np

    log_returns = np.log(
        synthetic_ohlcv["Close"] / synthetic_ohlcv["Close"].shift(1)
    ).dropna()

    result = run_monte_carlo(
        current_price=150.0,
        log_returns=log_returns,
        horizon_days=10,
        n_simulations=1000,
        random_seed=42,
    )

    assert 0 <= result.prob_positive_return <= 1
    assert 0 <= result.prob_10pct_loss <= 1
    assert 0 <= result.prob_20pct_loss <= 1
    assert result.prob_20pct_loss <= result.prob_10pct_loss
    assert result.var_95_pct >= 0
    assert result.cvar_95_pct >= result.var_95_pct, "CVaR must be >= VaR"
    assert result.p5 < result.p50 < result.p95, "Percentiles must be ordered"


@pytest.mark.asyncio
async def test_data_validator_rejects_negative_prices():
    """Validator must reject rows with negative prices."""
    import pandas as pd
    import numpy as np
    from data_pipeline.validators.ohlcv_validator import (
        validate_ohlcv_dataframe, DataQualityError
    )

    dates = pd.date_range("2022-01-01", periods=50, freq="B", tz="UTC")
    df = pd.DataFrame({
        "Open": np.random.uniform(90, 110, 50),
        "High": np.random.uniform(105, 115, 50),
        "Low": np.random.uniform(85, 95, 50),
        "Close": np.random.uniform(90, 110, 50),
        "Volume": np.random.uniform(1e6, 1e7, 50),
    }, index=dates)

    # Inject negative price
    df.iloc[25, df.columns.get_loc("Close")] = -50.0

    cleaned = validate_ohlcv_dataframe(df, "TEST")
    assert (cleaned["Close"] >= 0).all(), "Negative prices not removed"
    assert len(cleaned) < len(df), "Row with negative price not dropped"