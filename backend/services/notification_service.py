# backend/services/notification_service.py
"""
Push notification service via Expo Push API.

Sends notifications to mobile clients when:
  - A new BUY signal fires (prob > 0.65 and confidence > 0.5)
  - A watchlist price alert threshold is crossed
  - A position approaches its stop-loss (within 1 ATR)
  - A market regime change is detected

Batching:
  Expo supports up to 100 notifications per request.
  We batch and flush every 10 seconds to avoid thundering the API.
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
    channel_id: str = "signals"
    priority: str = "high"
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
        emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "🟡"
        msg = PushMessage(
            expo_push_token=push_token,
            title=f"{emoji} {action} Signal — {symbol}",
            body=(f"Confidence: {confidence * 100:.0f}% · "
                  f"Price: ${current_price:,.2f}"),
            data={"type": "SIGNAL", "symbol": symbol,
                  "action": action, "confidence": confidence},
            channel_id="signals", priority="high",
        )
        self._pending.append(msg)
        await self._maybe_flush()

    async def send_risk_alert(self, push_token: str, symbol: str, message: str):
        msg = PushMessage(
            expo_push_token=push_token,
            title=f"⚠️ Risk Alert — {symbol}",
            body=message,
            data={"type": "RISK_ALERT", "symbol": symbol},
            channel_id="risk_alerts", priority="high",
        )
        self._pending.append(msg)
        await self._flush()  # Immediate flush for risk alerts

    async def _maybe_flush(self):
        if len(self._pending) >= 100:
            await self._flush()
        elif self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._delayed_flush(10))

    async def _delayed_flush(self, delay: float):
        await asyncio.sleep(delay)
        await self._flush()

    async def _flush(self):
        if not self._pending:
            return
        batch = self._pending.copy()
        self._pending.clear()

        payload = [
            {"to": m.expo_push_token, "title": m.title, "body": m.body,
             "data": m.data, "channelId": m.channel_id,
             "priority": m.priority, "sound": m.sound, "badge": m.badge}
            for m in batch
        ]

        try:
            resp = await self._client.post(
                EXPO_PUSH_URL, json=payload,
                headers={"Accept": "application/json",
                         "Content-Type": "application/json"},
            )
            result = resp.json()
            errors = [r for r in result.get("data", []) if r.get("status") == "error"]
            if errors:
                log.warning("Push errors", count=len(errors), sample=errors[0])
            else:
                log.info("Push notifications sent", count=len(batch))
        except Exception as e:
            log.error("Push flush failed", error=str(e))
            self._pending.extend(batch[:10])  # retry first 10 only
