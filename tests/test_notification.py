import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.services.notification_service import NotificationService, PushMessage

@pytest.mark.asyncio
async def test_notification_service_signals(monkeypatch):
    service = NotificationService()
    
    # Mock post call
    mock_post = AsyncMock(return_value=MagicMock(
        json=MagicMock(return_value={"data": [{"status": "ok"}]})
    ))
    monkeypatch.setattr(service._client, "post", mock_post)
    
    # Send buy signal (batching, will trigger delayed flush or maybe_flush)
    await service.send_signal_notification(
        push_token="ExponentPushToken[xxx]",
        symbol="AAPL",
        action="BUY",
        confidence=0.85,
        current_price=175.50
    )
    
    assert len(service._pending) == 1
    
    # Trigger immediate flush to verify logic
    await service._flush()
    assert len(service._pending) == 0
    assert mock_post.called
    
    # Verify payload format
    payload = mock_post.call_args[1]["json"]
    assert len(payload) == 1
    assert payload[0]["to"] == "ExponentPushToken[xxx]"
    assert "BUY" in payload[0]["title"]
    assert "AAPL" in payload[0]["title"]
    assert "85%" in payload[0]["body"]

@pytest.mark.asyncio
async def test_notification_service_risk_alert(monkeypatch):
    service = NotificationService()
    
    mock_post = AsyncMock(return_value=MagicMock(
        json=MagicMock(return_value={"data": [{"status": "error", "message": "Invalid token"}]})
    ))
    monkeypatch.setattr(service._client, "post", mock_post)
    
    # Risk alerts flush immediately
    await service.send_risk_alert(
        push_token="ExponentPushToken[yyy]",
        symbol="BTC-USD",
        message="Approaching stop-loss"
    )
    
    assert len(service._pending) == 0
    assert mock_post.called
    payload = mock_post.call_args[1]["json"]
    assert payload[0]["to"] == "ExponentPushToken[yyy]"
    assert "BTC-USD" in payload[0]["title"]
    assert "Approaching stop-loss" in payload[0]["body"]

from httpx import AsyncClient

@pytest.mark.asyncio
async def test_register_device_token(app_client: AsyncClient):
    from backend.services.auth_service import auth_service
    from backend.models.user import User
    from tests.conftest import AsyncSessionLocal
    from sqlalchemy import select

    # 1. Setup user
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == "notif_user@example.com"))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                email="notif_user@example.com",
                hashed_password="some-hashed-password",
                risk_tolerance="moderate",
                capital_usd=10000.0,
                is_active=True
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        user_id = user.id

    # 2. Get Access Token
    token = auth_service.create_access_token(user_id=user_id, email="notif_user@example.com")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Requested-With": "XMLHttpRequest"
    }

    # 3. Call register-token endpoint
    payload = {
        "expo_push_token": "ExponentPushToken[notif_test_token]",
        "platform": "ios"
    }
    resp = await app_client.post("/api/v1/notifications/register-token", json=payload, headers=headers)
    assert resp.status_code == 201
    assert resp.json() == {"status": "success", "message": "Device token registered"}
