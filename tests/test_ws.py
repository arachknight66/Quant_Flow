import pytest
import asyncio
import json
from starlette.testclient import TestClient
from unittest.mock import MagicMock
from backend.main import app
from backend.services.auth_service import auth_service
from backend.models.user import User
from tests.conftest import AsyncSessionLocal
from sqlalchemy import select

def get_valid_token_for_user(email: str) -> str:
    async def create_user_task():
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if not user:
                user = User(
                    email=email,
                    hashed_password=auth_service.hash_password("some-password"),
                    risk_tolerance="moderate",
                    is_active=True
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
            return auth_service.create_access_token(user_id=user.id, email=email)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(create_user_task())
    finally:
        loop.close()


def test_ws_prices_no_token():
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/prices"):
            pass


def test_ws_prices_invalid_token():
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/prices?token=garbage"):
            pass


def test_ws_prices_valid_token_and_ping(db_session, mock_redis):
    token = get_valid_token_for_user("ws_user@example.com")
    client = TestClient(app)
    with client.websocket_connect(f"/ws/prices?token={token}") as ws:
        ws.send_json({"action": "ping"})
        resp = ws.receive_json()
        assert resp["type"] == "pong"


def test_ws_prices_revoked_token_rejected(db_session, mock_redis):
    email = "ws_revoked_user@example.com"
    token = get_valid_token_for_user(email)
    
    payload = auth_service.decode_token(token)
    jti = payload.get("jti")
    
    mock_redis.store[f"revoked:{jti}"] = "true"
        
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/prices?token={token}"):
            pass


def test_ws_prices_subscribe_and_broadcast(db_session, mock_redis):
    token = get_valid_token_for_user("ws_user_sub@example.com")
    client = TestClient(app)
    with client.websocket_connect(f"/ws/prices?token={token}") as ws:
        # Subscribe
        ws.send_json({"action": "subscribe", "symbol": "AAPL"})
        resp = ws.receive_json()
        assert resp["type"] == "subscribed"
        assert resp["symbol"] == "AAPL"
        
        # Broadcast manually
        from backend.api.routers.ws import manager
        async def broadcast():
            await manager.broadcast_to_symbol("AAPL", {"type": "price_update", "symbol": "AAPL", "price": 150.0})
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(broadcast())
        finally:
            loop.close()
            
        # Receive broadcast
        resp_update = ws.receive_json()
        assert resp_update["type"] == "price_update"
        assert resp_update["price"] == 150.0

        # Unsubscribe
        ws.send_json({"action": "unsubscribe", "symbol": "AAPL"})


def test_price_polling_task(monkeypatch):
    from backend.api.routers.ws import price_polling_task, manager
    import yfinance as yf
    
    # Pre-add active symbol to test execution branch
    manager.symbol_subscribers["AAPL"] = set()
    
    # Mock yfinance download
    mock_df = MagicMock()
    mock_df.empty = False
    mock_df.columns = MagicMock()
    mock_df.columns.get_level_values.return_value = []
    
    # Mock iloc to return dummy series
    dummy_bar = {"Close": 150.0, "High": 151.0, "Low": 149.0, "Volume": 1000}
    mock_iloc = MagicMock()
    mock_iloc.__getitem__.side_effect = lambda idx: dummy_bar
    mock_iloc.__len__.return_value = 2
    mock_df.iloc = mock_iloc
    
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: mock_df)
    
    # Mock sleep to raise exception to exit loop
    class ExitLoop(Exception):
        pass
    async def mock_sleep(secs):
        raise ExitLoop()
    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        with pytest.raises(ExitLoop):
            loop.run_until_complete(price_polling_task(0.01))
    finally:
        loop.close()
        
    # Clean up
    manager.symbol_subscribers.clear()
