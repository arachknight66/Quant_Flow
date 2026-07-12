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
