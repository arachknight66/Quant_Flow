import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from backend.models.asset import Asset, AssetType
from backend.models.watchlist import WatchlistItem
from backend.models.user import User
from backend.services.market_data_service import MarketDataService

@pytest.fixture
async def seeded_users(db_session):
    # User A
    user_a = User(
        id=uuid.uuid4(),
        email="usera@example.com",
        hashed_password="hashed_pwd",
        risk_tolerance="moderate",
        capital_usd=10000.0,
        is_active=True,
        created_at=datetime.utcnow()
    )
    # User B
    user_b = User(
        id=uuid.uuid4(),
        email="userb@example.com",
        hashed_password="hashed_pwd",
        risk_tolerance="moderate",
        capital_usd=10000.0,
        is_active=True,
        created_at=datetime.utcnow()
    )
    db_session.add_all([user_a, user_b])
    
    # Seedeable Assets
    asset_aapl = Asset(
        id=uuid.uuid4(),
        symbol="AAPL",
        name="Apple Inc",
        asset_type=AssetType.STOCK,
        currency="USD"
    )
    asset_msft = Asset(
        id=uuid.uuid4(),
        symbol="MSFT",
        name="Microsoft Corp",
        asset_type=AssetType.STOCK,
        currency="USD"
    )
    db_session.add_all([asset_aapl, asset_msft])
    await db_session.commit()
    await db_session.refresh(user_a)
    await db_session.refresh(user_b)
    await db_session.refresh(asset_aapl)
    await db_session.refresh(asset_msft)
    return user_a, user_b, asset_aapl, asset_msft


@pytest.mark.asyncio
async def test_add_to_watchlist_success(app_client, seeded_users):
    user_a, _, asset_aapl, _ = seeded_users
    from backend.services.auth_service import get_current_user
    app = app_client._transport.app
    app.dependency_overrides[get_current_user] = lambda: user_a

    payload = {"symbol": "AAPL", "notes": "Fave Stock"}
    resp = await app_client.post("/api/v1/watchlist", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["notes"] == "Fave Stock"
    assert data["asset_id"] == str(asset_aapl.id)

    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_add_duplicate_returns_409(app_client, seeded_users, db_session):
    user_a, _, asset_aapl, _ = seeded_users
    
    # Pre-add to watchlist
    w_item = WatchlistItem(
        id=uuid.uuid4(),
        user_id=user_a.id,
        asset_id=asset_aapl.id,
        notes="First note"
    )
    db_session.add(w_item)
    await db_session.commit()

    from backend.services.auth_service import get_current_user
    app = app_client._transport.app
    app.dependency_overrides[get_current_user] = lambda: user_a

    payload = {"symbol": "AAPL"}
    resp = await app_client.post("/api/v1/watchlist", json=payload)
    assert resp.status_code == 409
    assert "Symbol is already on the watchlist" in resp.json()["detail"]

    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_add_unknown_symbol_creates_asset_via_yfinance_fallback(app_client, seeded_users, monkeypatch):
    user_a, _, _, _ = seeded_users

    # Mock yfinance ticker info
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "regularMarketPrice": 250.0,
        "longName": "Super New Asset",
        "exchange": "NASDAQ",
        "currency": "USD"
    }
    monkeypatch.setattr("yfinance.Ticker", lambda sym: mock_ticker)

    from backend.services.auth_service import get_current_user
    app = app_client._transport.app
    app.dependency_overrides[get_current_user] = lambda: user_a

    payload = {"symbol": "NEWASSET"}
    resp = await app_client.post("/api/v1/watchlist", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "NEWASSET"
    assert data["name"] == "Super New Asset"

    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_remove_from_watchlist(app_client, seeded_users, db_session):
    user_a, _, asset_aapl, _ = seeded_users

    w_item = WatchlistItem(
        id=uuid.uuid4(),
        user_id=user_a.id,
        asset_id=asset_aapl.id,
        notes="to be deleted"
    )
    db_session.add(w_item)
    await db_session.commit()

    from backend.services.auth_service import get_current_user
    app = app_client._transport.app
    app.dependency_overrides[get_current_user] = lambda: user_a

    resp = await app_client.delete(f"/api/v1/watchlist/{asset_aapl.id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_watchlist_scoped_to_user(app_client, seeded_users, db_session):
    user_a, user_b, asset_aapl, _ = seeded_users

    # User B adds AAPL to watchlist
    w_item = WatchlistItem(
        id=uuid.uuid4(),
        user_id=user_b.id,
        asset_id=asset_aapl.id,
        notes="private watch"
    )
    db_session.add(w_item)
    await db_session.commit()

    from backend.services.auth_service import get_current_user
    app = app_client._transport.app
    
    # 1. User A tries to delete it (should return 404 since it's scoped to User B)
    app.dependency_overrides[get_current_user] = lambda: user_a
    resp = await app_client.delete(f"/api/v1/watchlist/{asset_aapl.id}")
    assert resp.status_code == 404

    # 2. User A gets watchlist (should be empty, user A cannot see User B's list)
    resp_get = await app_client.get("/api/v1/watchlist")
    assert resp_get.status_code == 200
    assert len(resp_get.json()) == 0

    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_get_watchlist_includes_current_prices(app_client, seeded_users, db_session, monkeypatch):
    user_a, _, asset_aapl, _ = seeded_users

    w_item = WatchlistItem(
        id=uuid.uuid4(),
        user_id=user_a.id,
        asset_id=asset_aapl.id
    )
    db_session.add(w_item)
    await db_session.commit()

    # Mock market data service close price
    import pandas as pd
    df = pd.DataFrame({"Close": [180.0]}, index=[datetime.now(timezone.utc)])
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=df)
    )

    from backend.services.auth_service import get_current_user
    app = app_client._transport.app
    app.dependency_overrides[get_current_user] = lambda: user_a

    resp = await app_client.get("/api/v1/watchlist")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "AAPL"
    assert data[0]["current_price"] == 180.0

    app.dependency_overrides.pop(get_current_user, None)
