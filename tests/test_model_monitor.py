import pytest
import numpy as np
import pandas as pd
from httpx import AsyncClient
from backend.monitoring.model_monitor import ModelMonitor, DriftAlert

def test_model_monitor_stable_distribution():
    # 1. Setup stable distribution (training data vs live data are identical)
    np.random.seed(42)
    training_data = pd.DataFrame({
        "rsi": np.random.normal(50, 10, 1000),
        "atr": np.random.exponential(2, 1000)
    })
    
    monitor = ModelMonitor()
    monitor.set_reference_distribution(training_data, reference_accuracy=0.55)
    
    live_data = pd.DataFrame({
        "rsi": np.random.normal(50, 10, 1000),
        "atr": np.random.exponential(2, 1000)
    })
    
    alerts = monitor.check_drift(live_data, window_days=1000)
    
    # Assert no alerts on stable distributions
    assert len(alerts) == 0

def test_model_monitor_ks_drift():
    np.random.seed(42)
    training_data = pd.DataFrame({
        "rsi": np.random.normal(50, 5, 200)
    })
    
    monitor = ModelMonitor()
    monitor.set_reference_distribution(training_data)
    
    # Live data has significantly shifted distribution (mean = 70 instead of 50)
    live_data = pd.DataFrame({
        "rsi": np.random.normal(70, 5, 50)
    })
    
    alerts = monitor.check_drift(live_data, window_days=50)
    feature_alerts = [a for a in alerts if a.drift_type == "feature_drift"]
    
    # Assert KS test fires for clearly different distributions
    assert len(feature_alerts) > 0
    assert feature_alerts[0].feature_name == "rsi"
    assert feature_alerts[0].p_value < 0.01

def test_model_monitor_psi_drift():
    np.random.seed(42)
    training_data = pd.DataFrame({
        "rsi": np.random.normal(50, 5, 200)
    })
    
    monitor = ModelMonitor(psi_warning=0.1, psi_critical=0.25)
    monitor.set_reference_distribution(training_data)
    
    # Live data has significantly shifted distribution
    live_data = pd.DataFrame({
        "rsi": np.random.normal(65, 5, 50)
    })
    
    alerts = monitor.check_drift(live_data, window_days=50)
    psi_alerts = [a for a in alerts if a.drift_type == "psi_drift"]
    
    # Assert PSI fires above threshold
    assert len(psi_alerts) > 0
    assert psi_alerts[0].feature_name == "rsi"
    assert psi_alerts[0].statistic > 0.1

def test_model_monitor_accuracy_drift():
    monitor = ModelMonitor(min_accuracy_drop=0.05, accuracy_window=20)
    monitor.set_reference_distribution(pd.DataFrame({"rsi": [50.0]*20}), reference_accuracy=0.60)
    
    # Log 20 BUY predictions that all failed (realised_outcome = 0)
    for i in range(20):
        monitor.log_prediction(
            timestamp="2026-07-12T12:00:00Z",
            symbol="AAPL",
            features={"rsi": 50.0},
            prediction={"action": "BUY", "prob_profit": 0.65},
            realised_outcome=0 # 0% accuracy
        )
    
    # We need to call check_drift to trigger the inner _check_accuracy_drift()
    live_data = pd.DataFrame({"rsi": [50.0]*20})
    alerts = monitor.check_drift(live_data, window_days=20)
    
    acc_alerts = [a for a in alerts if a.drift_type == "accuracy_drift"]
    
    # Assert accuracy drift fires when recent accuracy drops by > 5 percentage points
    assert len(acc_alerts) == 1
    assert acc_alerts[0].statistic == pytest.approx(0.60) # drop is 0.60 - 0.0 = 0.60
    assert acc_alerts[0].severity == "critical"

@pytest.mark.asyncio
async def test_monitoring_drift_endpoint(app_client: AsyncClient, monkeypatch):
    from unittest.mock import AsyncMock
    from httpx import AsyncClient as HTTPAClient
    
    # 1. Setup mock data
    n_bars = 500
    dates = pd.date_range("2021-01-01", periods=n_bars, freq="B", tz="UTC")
    prices = 100.0 * np.exp(np.cumsum(np.random.normal(0, 0.01, n_bars)))
    df = pd.DataFrame({
        "Open": prices,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Close": prices,
        "Volume": np.random.uniform(1e6, 5e6, n_bars),
    }, index=dates)

    # 2. Mock MarketDataService.get_ohlcv
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )

    # 3. Call endpoint
    resp = await app_client.get("/api/v1/monitoring/drift?symbol=AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert "alerts" in data
    assert "status" in data
