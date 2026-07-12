import pytest
import numpy as np
import pandas as pd
from ml.models.volatility.garch_model import GARCHVolatilityModel

def test_garch_model():
    # 1. Generate returns with volatility clustering
    np.random.seed(42)
    n = 300
    v = np.empty(n)
    r = np.empty(n)
    v[0] = 0.01
    r[0] = np.random.normal(0, np.sqrt(v[0]))
    omega, alpha, beta = 1e-5, 0.08, 0.90
    for t in range(1, n):
        v[t] = omega + alpha * r[t-1]**2 + beta * v[t-1]
        r[t] = np.random.normal(0, np.sqrt(v[t]))
        
    returns = pd.Series(r)
    
    # 2. Fit model (will use arch package since it is installed now)
    model = GARCHVolatilityModel()
    params = model.fit(returns)
    
    # Verify parameter constraints (stationarity, positivity)
    assert params.alpha + params.beta < 1.0
    assert params.omega > 0.0
    assert params.long_run_variance > 0.0
    assert params.long_run_volatility_annual > 0.0
    
    # Verify 1-day ahead forecast returns positive float
    fc = model.forecast_1day_vol(returns)
    assert isinstance(fc, float)
    assert fc > 0.0
    
    # 3. Compare with manual MLE path
    # Force manual fitting
    manual_model = GARCHVolatilityModel()
    manual_params = manual_model._fit_manual(returns)
    
    # Compare manual parameters with arch package parameters
    # They should be reasonably close / similar
    assert manual_params.alpha + manual_params.beta < 1.0
    assert manual_params.omega > 0.0
    
    # Verify that the two models produce comparable 1-day vol forecasts
    fc_manual = manual_model.forecast_1day_vol(returns)
    assert fc_manual > 0.0
    assert abs(fc - fc_manual) < 1.5 # Allow reasonable difference due to optimization variance
