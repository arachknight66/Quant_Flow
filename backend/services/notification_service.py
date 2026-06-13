# backend/services/notification_service.py
"""
Push notification service via Expo Push API.

Sends notifications to mobile clients when:
  - A new BUY/SELL signal fires (with prob > 0.65 and confidence > 0.5)
  - A watchlist price alert threshold is crossed
  - A position approaches its stop-loss (within 1 ATR)
  - A market regime change is detected

Batching:
  Expo Push API supports up to 100 notifications per request.
  We batch all pending notifications and flush every 10 seconds.
  This prevents overwhelming the Expo API during volatile periods.
"""
import httpx
import asyncio
from dataclasses import dataclass
from typing import Optional
import structlog

log = structlog.get_logger()

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


@dataclass
class PushMessage:
    expo_push_token: str
    title: str
    body: str
    data: dict
    channel_id: str = "signals"   # Android channel
    priority: str = "high"        # "default", "high", "normal"
    sound: str = "default"
    badge: int = 1


class NotificationService:

    def __init__(self):
        self._pending: list[PushMessage] = []
        self._flush_task: Optional[asyncio.Task] = None
        self._client = httpx.AsyncClient(timeout=10.0)

    async def send_signal_notification(
        self,
        push_token: str,
        symbol: str,
        action: str,
        confidence: float,
        current_price: float,
    ):
        """Send a BUY/SELL signal notification."""
        emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "🟡"
        msg = PushMessage(
            expo_push_token=push_token,
            title=f"{emoji} {action} Signal — {symbol}",
            body=(
                f"Confidence: {confidence * 100:.0f}% · "
                f"Price: ${current_price:,.2f}"
            ),
            data={
                "type": "SIGNAL",
                "symbol": symbol,
                "action": action,
                "confidence": confidence,
            },
            channel_id="signals",
            priority="high",
        )
        self._pending.append(msg)
        await self._maybe_flush()

    async def send_risk_alert(
        self,
        push_token: str,
        symbol: str,
        message: str,
    ):
        """Send a critical risk alert (bypasses DND on Android)."""
        msg = PushMessage(
            expo_push_token=push_token,
            title=f"⚠️ Risk Alert — {symbol}",
            body=message,
            data={"type": "RISK_ALERT", "symbol": symbol},
            channel_id="risk_alerts",
            priority="high",
            sound="default",
        )
        self._pending.append(msg)
        # Flush immediately for risk alerts — don't batch
        await self._flush()

    async def _maybe_flush(self):
        """Flush if we have 100 pending or schedule a flush in 10s."""
        if len(self._pending) >= 100:
            await self._flush()
        elif self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._delayed_flush(10))

    async def _delayed_flush(self, delay: float):
        await asyncio.sleep(delay)
        await self._flush()

    async def _flush(self):
        """Send all pending notifications to Expo Push API."""
        if not self._pending:
            return

        batch = self._pending.copy()
        self._pending.clear()

        payload = [
            {
                "to": msg.expo_push_token,
                "title": msg.title,
                "body": msg.body,
                "data": msg.data,
                "channelId": msg.channel_id,
                "priority": msg.priority,
                "sound": msg.sound,
                "badge": msg.badge,
            }
            for msg in batch
        ]

        try:
            response = await self._client.post(
                EXPO_PUSH_URL,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Content-Type": "application/json",
                },
            )
            result = response.json()

            errors = [
                r for r in result.get("data", [])
                if r.get("status") == "error"
            ]
            if errors:
                log.warning(
                    "Push notification errors",
                    count=len(errors),
                    sample=errors[0] if errors else None,
                )
            else:
                log.info("Push notifications sent", count=len(batch))

        except Exception as e:
            log.error("Push notification flush failed", error=str(e))
            # Re-queue for retry (simplified — production would use a queue)
            self._pending.extend(batch[:10])  # Retry first 10 only