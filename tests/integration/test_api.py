import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta
from data_pipeline.collectors.base import OHLCVRecord

async def test_full_api_integration_flow(app_client: AsyncClient, monkeypatch):
    # Mock yfinance data source to return 100 historical bars so that /analyze doesn't fail
    from ml.features.technical_indicators import IndicatorConfig
    import numpy as np
    import pandas as pd
    
    n_bars = 100
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=n_bars, freq="B")
    rng = np.random.default_rng(42)
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n_bars)))
    
    mock_records = []
    for i, ts in enumerate(dates):
        mock_records.append(OHLCVRecord(
            symbol="AAPL", interval="1d", ts=ts.to_pydatetime(),
            open=prices[i], high=prices[i] * 1.01, low=prices[i] * 0.99,
            close=prices[i], volume=10000.0, adj_close=prices[i]
        ))
        
    mock_fetch = AsyncMock(return_value=mock_records)
    monkeypatch.setattr("data_pipeline.collectors.yfinance_collector.YFinanceCollector.fetch_historical", mock_fetch)

    # 1. Register
    reg_payload = {
        "email": "integration@example.com",
        "password": "integrationpassword123",
        "risk_tolerance": "moderate"
    }
    resp = await app_client.post("/api/v1/auth/register", json=reg_payload)
    assert resp.status_code == 201
    assert resp.json()["email"] == "integration@example.com"
    
    # 2. Login
    login_payload = {
        "email": "integration@example.com",
        "password": "integrationpassword123"
    }
    resp = await app_client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 200
    token_data = resp.json()
    assert "access_token" in token_data
    token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3. Get /me
    resp = await app_client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "integration@example.com"
    
    # 4. Fetch OHLCV data
    resp = await app_client.get("/api/v1/market/ohlcv?symbol=AAPL&interval=1d&days=30", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "AAPL"
    
    # 5. Run analyze
    analyze_payload = {
        "symbol": "AAPL",
        "timeframe": "1d",
        "risk_tolerance": "moderate",
        "capital": 10000.0,
        "lookback_days": 90
    }
    resp = await app_client.post("/api/v1/analysis/analyze", json=analyze_payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "AAPL"
    
    # 6. Portfolio Summary
    resp = await app_client.get("/api/v1/portfolio/summary", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total_value_usd"] == 0.0
    
    # 7. Portfolio signals history
    resp = await app_client.get("/api/v1/portfolio/signals/history", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
