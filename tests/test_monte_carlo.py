import pytest
import numpy as np
import pandas as pd
from ml.risk.monte_carlo import run_monte_carlo

def test_monte_carlo_properties():
    # Setup log returns
    np.random.seed(42)
    clean_returns = pd.Series(np.random.normal(0.0005, 0.015, 200))
    
    # Run simulation twice with same seed to verify reproducibility
    r1 = run_monte_carlo(
        current_price=100.0,
        log_returns=clean_returns,
        horizon_days=20,
        n_simulations=1000,
        random_seed=123
    )
    
    r2 = run_monte_carlo(
        current_price=100.0,
        log_returns=clean_returns,
        horizon_days=20,
        n_simulations=1000,
        random_seed=123
    )
    
    # 1. Reproducibility
    assert r1.p5 == r2.p5
    assert r1.p50 == r2.p50
    assert r1.p95 == r2.p95
    assert r1.prob_positive_return == r2.prob_positive_return
    assert r1.var_95_pct == r2.var_95_pct
    assert r1.cvar_95_pct == r2.cvar_95_pct
    assert r1.sample_paths == r2.sample_paths
    
    # 2. Probability bounds [0, 1]
    for p in [r1.prob_positive_return, r1.prob_10pct_loss, r1.prob_20pct_loss]:
        assert 0.0 <= p <= 1.0

    # 3. CVaR >= VaR constraint
    assert r1.cvar_95_pct >= r1.var_95_pct
    
    # 4. Percentiles are strictly ordered
    assert r1.p5 <= r1.p25 <= r1.p50 <= r1.p75 <= r1.p95
    
    # 5. Monotonicity: prob_20pct_loss <= prob_10pct_loss
    assert r1.prob_20pct_loss <= r1.prob_10pct_loss
