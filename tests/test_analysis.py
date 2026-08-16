import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from httpx import AsyncClient
from unittest.mock import AsyncMock

def make_dummy_ohlcv(n_bars=350):
    dates = pd.date_range("2021-01-01", periods=n_bars, freq="B", tz="UTC")
    rng = np.random.default_rng(42)
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n_bars)))
    return pd.DataFrame({
        "Open": prices,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Close": prices,
        "Volume": rng.uniform(1e6, 5e6, n_bars),
    }, index=dates)

async def test_analyze_no_model_warning(app_client: AsyncClient, monkeypatch):
    # Mock MarketDataService.get_ohlcv
    df = make_dummy_ohlcv(100)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )

    # Force ML predict to raise an error
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.predict",
        AsyncMock(side_effect=RuntimeError("Model not loaded"))
    )

    payload = {
        "symbol": "AAPL",
        "asset_type": "stock",
        "timeframe": "1d",
        "risk_tolerance": "moderate",
        "lookback_days": 365
    }
    resp = await app_client.post("/api/v1/analysis/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "HOLD"
    assert any("ML model unavailable" in w for w in data["warnings"])

async def test_analyze_with_synthetic_model_buy(app_client: AsyncClient, monkeypatch):
    df = make_dummy_ohlcv(100)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )

    # Mock predict to return a BUY signal
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.predict",
        AsyncMock(return_value={
            "action": "BUY",
            "prob_profit": 0.65,
            "confidence": 0.85,
            "model_version": "v1-test"
        })
    )

    # Mock get_model_auc
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.get_model_auc",
        AsyncMock(return_value=0.55)
    )

    # Scenario: No capital provided -> position_sizing is None
    payload = {
        "symbol": "AAPL",
        "timeframe": "1d",
        "risk_tolerance": "moderate",
        "lookback_days": 365
    }
    resp = await app_client.post("/api/v1/analysis/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "BUY"
    assert data["position_sizing"] is None

    # Scenario: Capital provided -> position_sizing is computed
    payload["capital"] = 50000.0
    resp = await app_client.post("/api/v1/analysis/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["position_sizing"] is not None
    assert data["position_sizing"]["position_value_usd"] > 0

async def test_analyze_insufficient_bars(app_client: AsyncClient, monkeypatch):
    # Only 50 bars
    df = make_dummy_ohlcv(50)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )

    payload = {
        "symbol": "AAPL",
        "timeframe": "1d",
        "risk_tolerance": "moderate"
    }
    resp = await app_client.post("/api/v1/analysis/analyze", json=payload)
    assert resp.status_code == 422
    assert "Insufficient data" in resp.json()["detail"]

async def test_backtest_insufficient_bars(app_client: AsyncClient, monkeypatch):
    # Insufficient bars (e.g. 200 bars when at least 300 are required)
    df = make_dummy_ohlcv(200)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )

    payload = {
        "symbol": "AAPL",
        "timeframe": "1d",
        "start_date": "2021-01-01",
        "end_date": "2021-12-31",
        "initial_capital": 10000.0,
        "risk_tolerance": "moderate"
    }
    resp = await app_client.post("/api/v1/analysis/backtest", json=payload)
    assert resp.status_code == 422
    assert "Need at least 300 bars" in resp.json()["detail"]

async def test_backtest_no_model(app_client: AsyncClient, monkeypatch):
    # 350 bars
    df = make_dummy_ohlcv(350)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )

    # Mock get_model to return None
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.get_model",
        AsyncMock(return_value=None)
    )

    payload = {
        "symbol": "AAPL",
        "timeframe": "1d",
        "start_date": "2021-01-01",
        "end_date": "2022-12-31",
        "initial_capital": 10000.0,
        "risk_tolerance": "moderate"
    }
    resp = await app_client.post("/api/v1/analysis/backtest", json=payload)
    assert resp.status_code == 422
    assert "No trained model" in resp.json()["detail"]

async def test_analyze_rate_limiting(app_client: AsyncClient, monkeypatch):
    df = make_dummy_ohlcv(100)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )
    # Mock predict and auc
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.predict",
        AsyncMock(return_value={"action": "HOLD", "prob_profit": 0.5, "confidence": 0.0})
    )
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.get_model_auc",
        AsyncMock(return_value=0.55)
    )

    payload = {
        "symbol": "AAPL",
        "timeframe": "1d",
        "risk_tolerance": "moderate"
    }
    # Send a request to ensure slowapi responds
    resp = await app_client.post("/api/v1/analysis/analyze", json=payload)
    assert resp.status_code == 200


async def test_analyze_includes_regime_and_garch_when_present(app_client: AsyncClient, monkeypatch):
    df = make_dummy_ohlcv(100)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )
    
    from ml.features.technical_indicators import build_feature_matrix
    original_build = build_feature_matrix
    def mock_build_features(*args, **kwargs):
        features = original_build(*args, **kwargs)
        features["regime_bull"] = 0.0
        features["regime_bear"] = 0.0
        features["regime_sideways"] = 0.0
        features["regime_entropy"] = 0.15
        features.loc[features.index[-1], "regime_bull"] = 1.0
        features.loc[features.index[-1], "garch_vol_1d"] = 0.24
        return features
        
    monkeypatch.setattr("backend.api.routers.analysis.build_feature_matrix", mock_build_features)

    monkeypatch.setattr(
        "backend.services.ml_service.MLService.predict",
        AsyncMock(return_value={"action": "HOLD", "prob_profit": 0.5, "confidence": 0.0})
    )
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.get_model_auc",
        AsyncMock(return_value=0.55)
    )

    payload = {
        "symbol": "AAPL",
        "timeframe": "1d",
        "risk_tolerance": "moderate"
    }
    resp = await app_client.post("/api/v1/analysis/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["regime"] == "bull"
    assert data["regime_confidence"] == pytest.approx(0.85)
    assert data["garch_vol_forecast"] == pytest.approx(0.24)


async def test_analyze_handles_missing_regime_and_garch_gracefully(app_client: AsyncClient, monkeypatch):
    df = make_dummy_ohlcv(100)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )
    
    from ml.features.technical_indicators import build_feature_matrix
    original_build = build_feature_matrix
    def mock_build_features(*args, **kwargs):
        features = original_build(*args, **kwargs)
        if "regime_bull" in features.columns:
            features = features.drop(columns=["regime_bull", "regime_bear", "regime_sideways", "regime_entropy"])
        if "garch_vol_1d" in features.columns:
            features = features.drop(columns=["garch_vol_1d"])
        if "garch_vol" in features.columns:
            features = features.drop(columns=["garch_vol"])
        return features

    monkeypatch.setattr("backend.api.routers.analysis.build_feature_matrix", mock_build_features)

    monkeypatch.setattr(
        "backend.services.ml_service.MLService.predict",
        AsyncMock(return_value={"action": "HOLD", "prob_profit": 0.5, "confidence": 0.0})
    )
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.get_model_auc",
        AsyncMock(return_value=0.55)
    )

    payload = {
        "symbol": "AAPL",
        "timeframe": "1d",
        "risk_tolerance": "moderate"
    }
    resp = await app_client.post("/api/v1/analysis/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["regime"] is None
    assert data["regime_confidence"] is None
    assert data["garch_vol_forecast"] is None


