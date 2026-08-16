import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from backend.models.asset import Asset, AssetType
from backend.models.signal import Signal
from backend.models.user import User
from backend.services.signal_evaluation_service import evaluate_signal_outcome
from backend.services.market_data_service import MarketDataService
import pandas as pd

def make_mock_ohlcv(prices):
    # Prices list is a list of float closes
    dates = [datetime(2026, 6, 1) + timedelta(days=i) for i in range(len(prices))]
    df = pd.DataFrame({
        "Open": prices,
        "High": [p + 1.0 for p in prices],
        "Low": [p - 1.0 for p in prices],
        "Close": prices,
        "Volume": [10000.0] * len(prices),
        "adj_close": prices
    }, index=dates)
    return df

@pytest.fixture
async def seeded_data(db_session):
    # 1. Create User
    user = User(
        id=uuid.uuid4(),
        email="test_eval@example.com",
        hashed_password="hashed_pwd",
        risk_tolerance="moderate",
        capital_usd=10000.0,
        is_active=True,
        created_at=datetime.utcnow()
    )
    db_session.add(user)
    
    # 2. Create Asset
    asset = Asset(
        id=uuid.uuid4(),
        symbol="AAPL",
        name="Apple Inc",
        asset_type=AssetType.STOCK,
        currency="USD"
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(asset)
    return user, asset


@pytest.mark.asyncio
async def test_buy_signal_correct_when_price_rises_past_threshold(db_session, seeded_data, monkeypatch):
    user, asset = seeded_data
    # 1. Create Signal on 2026-06-01
    signal = Signal(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        action="BUY",
        confidence=0.8,
        prob_profit=0.75,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        resolved=False
    )
    db_session.add(signal)
    await db_session.commit()

    # 2. Mock model metadata to return horizon=5, threshold=0.01
    # 3. Setup mock prices: day T close=100, day T+5 close=102 (+2%)
    prices = [100.0, 100.5, 101.0, 100.8, 101.5, 102.0, 102.5]
    mock_get = AsyncMock(return_value=make_mock_ohlcv(prices))
    monkeypatch.setattr("backend.services.market_data_service.MarketDataService.get_ohlcv", mock_get)

    service = MarketDataService(db_session)
    outcome = await evaluate_signal_outcome(db_session, signal, service)

    assert outcome is not None
    assert outcome["resolved"] is True
    assert outcome["correct"] is True
    assert outcome["actual_return_pct"] == pytest.approx(2.0)
    assert signal.resolved is True
    assert signal.outcome_correct is True


@pytest.mark.asyncio
async def test_buy_signal_incorrect_when_price_flat(db_session, seeded_data, monkeypatch):
    user, asset = seeded_data
    signal = Signal(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        action="BUY",
        confidence=0.8,
        prob_profit=0.75,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        resolved=False
    )
    db_session.add(signal)
    await db_session.commit()

    # day T close=100, day T+5 close=100.5 (+0.5% - below 1% threshold)
    prices = [100.0, 100.2, 100.1, 100.3, 100.4, 100.5, 100.6]
    mock_get = AsyncMock(return_value=make_mock_ohlcv(prices))
    monkeypatch.setattr("backend.services.market_data_service.MarketDataService.get_ohlcv", mock_get)

    service = MarketDataService(db_session)
    outcome = await evaluate_signal_outcome(db_session, signal, service)

    assert outcome is not None
    assert outcome["correct"] is False
    assert outcome["actual_return_pct"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_sell_signal_correct_when_price_falls_past_threshold(db_session, seeded_data, monkeypatch):
    user, asset = seeded_data
    signal = Signal(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        action="SELL",
        confidence=0.8,
        prob_profit=0.25,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        resolved=False
    )
    db_session.add(signal)
    await db_session.commit()

    # day T close=100, day T+5 close=98.0 (-2% - below -1% threshold)
    prices = [100.0, 99.5, 99.0, 98.8, 98.5, 98.0, 97.5]
    mock_get = AsyncMock(return_value=make_mock_ohlcv(prices))
    monkeypatch.setattr("backend.services.market_data_service.MarketDataService.get_ohlcv", mock_get)

    service = MarketDataService(db_session)
    outcome = await evaluate_signal_outcome(db_session, signal, service)

    assert outcome is not None
    assert outcome["correct"] is True
    assert outcome["actual_return_pct"] == pytest.approx(-2.0)


@pytest.mark.asyncio
async def test_hold_signals_excluded_from_accuracy(db_session, seeded_data, monkeypatch):
    user, asset = seeded_data
    signal = Signal(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        action="HOLD",
        confidence=0.0,
        prob_profit=0.50,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        resolved=False
    )
    db_session.add(signal)
    await db_session.commit()

    prices = [100.0, 100.5, 101.0, 100.8, 101.5, 102.0, 102.5]
    mock_get = AsyncMock(return_value=make_mock_ohlcv(prices))
    monkeypatch.setattr("backend.services.market_data_service.MarketDataService.get_ohlcv", mock_get)

    service = MarketDataService(db_session)
    outcome = await evaluate_signal_outcome(db_session, signal, service)

    assert outcome is None
    assert signal.resolved is False


@pytest.mark.asyncio
async def test_unresolved_signal_returns_none_when_horizon_not_elapsed(db_session, seeded_data, monkeypatch):
    user, asset = seeded_data
    signal = Signal(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        action="BUY",
        confidence=0.8,
        prob_profit=0.75,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        resolved=False
    )
    db_session.add(signal)
    await db_session.commit()

    # Only 4 prices (day T to T+3, horizon=5 not reached)
    prices = [100.0, 100.5, 101.0, 100.8]
    mock_get = AsyncMock(return_value=make_mock_ohlcv(prices))
    monkeypatch.setattr("backend.services.market_data_service.MarketDataService.get_ohlcv", mock_get)

    service = MarketDataService(db_session)
    outcome = await evaluate_signal_outcome(db_session, signal, service)

    assert outcome is None
    assert signal.resolved is False


@pytest.mark.asyncio
async def test_accuracy_endpoint_aggregates_correctly(app_client, db_session, seeded_data, monkeypatch):
    user, asset = seeded_data
    
    # Authenticate current user in app_client context
    from backend.services.auth_service import get_current_user
    app = app_client._transport.app
    app.dependency_overrides[get_current_user] = lambda: user

    # Create several resolved signals
    s1 = Signal(
        id=uuid.uuid4(), user_id=user.id, asset_id=asset.id,
        action="BUY", confidence=0.8, prob_profit=0.85,
        created_at=datetime.utcnow() - timedelta(days=5),
        resolved=True, outcome_correct=True, actual_return_pct=2.5
    )
    s2 = Signal(
        id=uuid.uuid4(), user_id=user.id, asset_id=asset.id,
        action="BUY", confidence=0.6, prob_profit=0.75,
        created_at=datetime.utcnow() - timedelta(days=4),
        resolved=True, outcome_correct=False, actual_return_pct=0.2
    )
    s3 = Signal(
        id=uuid.uuid4(), user_id=user.id, asset_id=asset.id,
        action="SELL", confidence=0.7, prob_profit=0.15,
        created_at=datetime.utcnow() - timedelta(days=3),
        resolved=True, outcome_correct=True, actual_return_pct=-3.0
    )
    db_session.add_all([s1, s2, s3])
    await db_session.commit()

    resp = await app_client.get("/api/v1/portfolio/signals/accuracy")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_signals_evaluated"] == 3
    assert data["correct_count"] == 2
    assert data["accuracy_pct"] == pytest.approx(66.67, 0.01)
    assert data["buy_count"] == 2
    assert data["buy_accuracy_pct"] == pytest.approx(50.0)
    assert data["sell_count"] == 1
    assert data["sell_accuracy_pct"] == pytest.approx(100.0)
    
    # Clean up overrides
    app.dependency_overrides.pop(get_current_user, None)
