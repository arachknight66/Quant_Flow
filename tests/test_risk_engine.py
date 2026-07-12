import pytest
import pandas as pd
import numpy as np
from backend.services.risk_engine import RiskEngine, RiskTolerance, RISK_PROFILES

def test_kelly_edge_cases():
    engine = RiskEngine()
    
    # 1. Zero loss -> returns 0.0 to prevent division by zero
    assert engine.compute_kelly_fraction(win_probability=0.5, avg_win_pct=0.05, avg_loss_pct=0.0) == 0.0
    assert engine.compute_kelly_fraction(win_probability=0.5, avg_win_pct=0.05, avg_loss_pct=-0.01) == 0.0
    
    # 2. p = 0 -> returns 0.0 (no win probability, no position size)
    assert engine.compute_kelly_fraction(win_probability=0.0, avg_win_pct=0.05, avg_loss_pct=0.02) == 0.0
    
    # 3. p = 1 -> returns 1.0 (perfect certainty)
    assert engine.compute_kelly_fraction(win_probability=1.0, avg_win_pct=0.05, avg_loss_pct=0.02) == 1.0

def test_risk_profiles_limits():
    engine = RiskEngine()
    capital = 100_000.0
    
    # Test all three risk profiles
    for rt in RiskTolerance:
        params = RISK_PROFILES[rt]
        # Even with 100% win probability and high confidence, position sizing must never exceed max_position_pct
        sizing = engine.compute_position_size(
            capital=capital, win_probability=1.0, current_price=100.0, atr=1.0,
            risk_tolerance=rt, avg_win_pct=0.10, avg_loss_pct=0.01, confidence=1.0
        )
        allocated_pct = sizing["position_value_usd"] / capital
        assert allocated_pct <= params.max_position_pct + 0.001

def test_value_at_risk():
    engine = RiskEngine()
    
    # Empty/insufficient returns -> returns 0.0
    short_returns = pd.Series(np.random.normal(0, 0.01, 10))
    assert engine.compute_var(short_returns, method="historical") == 0.0
    assert engine.compute_var(short_returns, method="parametric") == 0.0
    
    # Generate 100 random returns
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0.0005, 0.01, 100))
    
    # Historical VaR >= 0
    hist_var = engine.compute_var(returns, confidence_level=0.95, method="historical")
    assert hist_var >= 0.0
    
    # Parametric VaR >= 0
    param_var = engine.compute_var(returns, confidence_level=0.95, method="parametric")
    assert param_var >= 0.0
    
    # Invalid method -> ValueError
    with pytest.raises(ValueError):
        engine.compute_var(returns, method="invalid")

def test_max_drawdown_negative():
    engine = RiskEngine()
    
    # Equity curve going down
    equity = pd.Series([100.0, 95.0, 90.0, 85.0, 80.0])
    dd_result = engine.compute_max_drawdown(equity)
    
    # Must return a negative value for drawdown
    assert dd_result["max_drawdown_pct"] == -20.0
    assert dd_result["peak_date"] == "0"
    assert dd_result["trough_date"] == "4"
    assert dd_result["recovery_date"] == "Not recovered"
