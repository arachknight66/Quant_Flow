import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
import pandas as pd

from backend.models.asset import Asset, AssetType
from backend.models.signal import Signal
from backend.models.user import User
from backend.models.alert_subscription import AlertSubscription
import numpy as np

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

@pytest.fixture
async def seeded_user_asset(db_session):
    user = User(
        id=uuid.uuid4(),
        email="alert_user@example.com",
        hashed_password="hashed_pwd",
        risk_tolerance="moderate",
        capital_usd=10000.0,
        is_active=True,
        created_at=datetime.utcnow()
    )
    asset = Asset(
        id=uuid.uuid4(),
        symbol="AAPL",
        name="Apple Inc",
        asset_type=AssetType.STOCK,
        currency="USD"
    )
    db_session.add_all([user, asset])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(asset)
    return user, asset


@pytest.mark.asyncio
async def test_alert_subscription_endpoints(app_client, seeded_user_asset, db_session):
    user, asset = seeded_user_asset
    
    from backend.services.auth_service import get_current_user
    app = app_client._transport.app
    app.dependency_overrides[get_current_user] = lambda: user

    # 1. Post to subscribe
    resp = await app_client.post("/api/v1/alerts", json={"symbol": "AAPL", "is_active": True})
    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["is_active"] is True

    # 2. Get subscriptions
    resp_get = await app_client.get("/api/v1/alerts")
    assert resp_get.status_code == 200
    assert len(resp_get.json()) == 1
    assert resp_get.json()[0]["symbol"] == "AAPL"

    # 3. Delete to unsubscribe
    resp_del = await app_client.delete("/api/v1/alerts/AAPL")
    assert resp_del.status_code == 200
    
    # 4. Get again should be empty
    resp_get2 = await app_client.get("/api/v1/alerts")
    assert len(resp_get2.json()) == 0

    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_signal_change_sends_email_if_subscribed(app_client, seeded_user_asset, db_session, monkeypatch, mock_redis):
    user, asset = seeded_user_asset
    
    # Subscribe User to AAPL alerts
    sub = AlertSubscription(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        is_active=True
    )
    # Add a previous signal (BUY)
    prev = Signal(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        action="BUY",
        confidence=0.8,
        prob_profit=0.75,
        created_at=datetime.utcnow() - timedelta(hours=1),
        resolved=False
    )
    db_session.add_all([sub, prev])
    await db_session.commit()

    # Mock email service
    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr("backend.services.email_service.send_signal_alert_email", mock_send)

    # Mock ML model to predict SELL
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.get_model",
        AsyncMock(return_value=MagicMock())
    )
    # Mock technical indicators and price
    df = make_dummy_ohlcv(100)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )
    
    # Mock model prediction output
    mock_predict = AsyncMock(return_value={
        "action": "SELL",
        "confidence": 0.85,
        "prob_profit": 0.9,
        "model_version": "v1"
    })
    monkeypatch.setattr(
        "backend.services.ml_service.MLService.predict",
        mock_predict
    )

    from backend.services.auth_service import auth_service
    token = auth_service.create_access_token(str(user.id), user.email)
    headers = {"Authorization": f"Bearer {token}"}

    # Trigger analysis (which generates a new Signal)
    resp = await app_client.post("/api/v1/analysis/analyze", json={
        "symbol": "AAPL",
        "asset_type": "stock",
        "timeframe": "1d",
        "risk_tolerance": "moderate",
        "lookback_days": 365,
        "capital": 10000.0
    }, headers=headers)
    assert resp.status_code == 200
    
    # Verify email send was called since action changed from BUY to SELL
    assert mock_send.call_count == 1
    mock_send.assert_called_with(
        email=user.email,
        symbol="AAPL",
        old_action="BUY",
        new_action="SELL"
    )




@pytest.mark.asyncio
async def test_signal_change_no_email_if_unsubscribed(app_client, seeded_user_asset, db_session, monkeypatch, mock_redis):
    user, asset = seeded_user_asset
    
    # Non-active subscription (is_active=False)
    sub = AlertSubscription(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        is_active=False
    )
    prev = Signal(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        action="BUY",
        confidence=0.8,
        prob_profit=0.75,
        created_at=datetime.utcnow() - timedelta(hours=1),
        resolved=False
    )
    db_session.add_all([sub, prev])
    await db_session.commit()

    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr("backend.services.email_service.send_signal_alert_email", mock_send)
    monkeypatch.setattr("backend.services.ml_service.MLService.get_model", AsyncMock(return_value=MagicMock()))
    df = make_dummy_ohlcv(100)
    monkeypatch.setattr("backend.services.market_data_service.MarketDataService.get_ohlcv", AsyncMock(return_value=df))
    monkeypatch.setattr("backend.services.ml_service.MLService.predict", AsyncMock(return_value={
        "action": "SELL", "confidence": 0.85, "prob_profit": 0.9, "model_version": "v1"
    }))

    from backend.services.auth_service import auth_service
    token = auth_service.create_access_token(str(user.id), user.email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await app_client.post("/api/v1/analysis/analyze", json={
        "symbol": "AAPL",
        "asset_type": "stock",
        "timeframe": "1d",
        "risk_tolerance": "moderate",
        "lookback_days": 365,
        "capital": 10000.0
    }, headers=headers)
    assert resp.status_code == 200
    
    # Should NOT send email since subscription is inactive
    assert mock_send.call_count == 0




@pytest.mark.asyncio
async def test_no_email_if_signal_action_unchanged(app_client, seeded_user_asset, db_session, monkeypatch, mock_redis):
    user, asset = seeded_user_asset
    
    # Active subscription
    sub = AlertSubscription(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        is_active=True
    )
    # Previous signal was BUY
    prev = Signal(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        action="BUY",
        confidence=0.8,
        prob_profit=0.75,
        created_at=datetime.utcnow() - timedelta(hours=1),
        resolved=False
    )
    db_session.add_all([sub, prev])
    await db_session.commit()

    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr("backend.services.email_service.send_signal_alert_email", mock_send)
    monkeypatch.setattr("backend.services.ml_service.MLService.get_model", AsyncMock(return_value=MagicMock()))
    df = make_dummy_ohlcv(100)
    monkeypatch.setattr("backend.services.market_data_service.MarketDataService.get_ohlcv", AsyncMock(return_value=df))
    
    # Next signal is ALSO BUY (no change)
    monkeypatch.setattr("backend.services.ml_service.MLService.predict", AsyncMock(return_value={
        "action": "BUY", "confidence": 0.85, "prob_profit": 0.9, "model_version": "v1"
    }))

    from backend.services.auth_service import auth_service
    token = auth_service.create_access_token(str(user.id), user.email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await app_client.post("/api/v1/analysis/analyze", json={
        "symbol": "AAPL",
        "asset_type": "stock",
        "timeframe": "1d",
        "risk_tolerance": "moderate",
        "lookback_days": 365,
        "capital": 10000.0
    }, headers=headers)
    assert resp.status_code == 200
    
    # Should NOT send email since signal action did not change
    assert mock_send.call_count == 0


