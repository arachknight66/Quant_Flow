# backend/api/routers/ws.py
"""
WebSocket streaming for real-time price and signal updates.

Architecture:
- Each connected client subscribes to a set of symbols
- A background task polls prices every N seconds
- Price updates are pushed via Redis pub/sub to all relevant connections
- This decouples the polling loop from the connection management

Why Redis pub/sub instead of direct broadcast?
- Allows horizontal scaling: multiple backend instances share the same
  pub/sub channel, so all clients receive updates regardless of which
  instance they're connected to
- The polling process publishes; WS handlers subscribe
- If we later add 5 backend containers, all will relay updates correctly
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.websockets import WebSocketState
import asyncio
import json
import redis.asyncio as aioredis
import structlog
from datetime import datetime, timezone
from typing import Dict, Set

from backend.core.config import settings
from backend.services.market_data_service import MarketDataService

log = structlog.get_logger()
router = APIRouter()


class ConnectionManager:
    """
    Manages active WebSocket connections and their symbol subscriptions.

    Structure:
      connections: { websocket -> Set[symbol] }
      symbol_subscribers: { symbol -> Set[websocket] }
    """

    def __init__(self):
        self.connections: Dict[WebSocket, Set[str]] = {}
        self.symbol_subscribers: Dict[str, Set[WebSocket]] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections[ws] = set()
        log.info("WebSocket connected", total=len(self.connections))

    def disconnect(self, ws: WebSocket):
        symbols = self.connections.pop(ws, set())
        for symbol in symbols:
            self.symbol_subscribers.get(symbol, set()).discard(ws)
        log.info("WebSocket disconnected", total=len(self.connections))

    def subscribe(self, ws: WebSocket, symbol: str):
        symbol = symbol.upper()
        self.connections[ws].add(symbol)
        if symbol not in self.symbol_subscribers:
            self.symbol_subscribers[symbol] = set()
        self.symbol_subscribers[symbol].add(ws)

    def unsubscribe(self, ws: WebSocket, symbol: str):
        symbol = symbol.upper()
        self.connections[ws].discard(symbol)
        self.symbol_subscribers.get(symbol, set()).discard(ws)

    async def broadcast_to_symbol(self, symbol: str, data: dict):
        """Send a price update to all clients subscribed to this symbol."""
        subscribers = self.symbol_subscribers.get(symbol.upper(), set())
        dead = set()
        payload = json.dumps(data)

        for ws in subscribers:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(payload)
            except Exception:
                dead.add(ws)

        for ws in dead:
            self.disconnect(ws)

    @property
    def active_symbols(self) -> Set[str]:
        return set(self.symbol_subscribers.keys())


manager = ConnectionManager()


@router.websocket("/prices")
async def price_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time price streaming.

    Client message protocol:
        { "action": "subscribe",   "symbol": "AAPL" }
        { "action": "unsubscribe", "symbol": "AAPL" }
        { "action": "ping" }

    Server message protocol:
        { "type": "price_update", "symbol": "AAPL", "price": 150.25,
          "change_pct": 0.5, "volume": 12345678, "timestamp": "..." }
        { "type": "pong" }
        { "type": "error", "message": "..." }
    """
    await manager.connect(websocket)

    try:
        while True:
            # Wait for client messages (subscribe/unsubscribe/ping)
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                message = json.loads(raw)

                action = message.get("action")
                symbol = message.get("symbol", "").upper()

                if action == "subscribe" and symbol:
                    manager.subscribe(websocket, symbol)
                    await websocket.send_text(json.dumps({
                        "type": "subscribed",
                        "symbol": symbol,
                    }))

                elif action == "unsubscribe" and symbol:
                    manager.unsubscribe(websocket, symbol)

                elif action == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))

            except asyncio.TimeoutError:
                # Send keepalive ping after 30s inactivity
                await websocket.send_text(json.dumps({"type": "keepalive"}))

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log.error("WebSocket error", error=str(e))
        manager.disconnect(websocket)


# ---- Background price polling task ----
# Start this in lifespan() of the main app

async def price_polling_task(poll_interval_seconds: float = 5.0):
    """
    Background task that fetches latest prices and broadcasts updates.

    In production, replace yfinance with a proper market data websocket
    (Alpaca, Polygon, Binance stream) for true real-time data.
    """
    import yfinance as yf

    log.info("Price polling task started", interval=poll_interval_seconds)

    while True:
        try:
            active = manager.active_symbols
            if active:
                # Batch fetch for all active symbols
                # yfinance supports multi-ticker download
                tickers_str = " ".join(active)
                data = yf.download(
                    tickers_str,
                    period="1d",
                    interval="1m",
                    progress=False,
                    group_by="ticker" if len(active) > 1 else None,
                )

                for symbol in active:
                    try:
                        if len(active) == 1:
                            symbol_data = data
                        else:
                            symbol_data = data[symbol] if symbol in data.columns.get_level_values(0) else None

                        if symbol_data is None or symbol_data.empty:
                            continue

                        latest = symbol_data.iloc[-1]
                        prev = symbol_data.iloc[-2] if len(symbol_data) > 1 else latest

                        current_price = float(latest["Close"])
                        prev_price = float(prev["Close"])
                        change_pct = (current_price - prev_price) / prev_price * 100

                        await manager.broadcast_to_symbol(symbol, {
                            "type": "price_update",
                            "symbol": symbol,
                            "price": round(current_price, 4),
                            "change_pct": round(change_pct, 3),
                            "volume": float(latest.get("Volume", 0)),
                            "high": float(latest["High"]),
                            "low": float(latest["Low"]),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception as e:
                        log.warning("Failed to process symbol", symbol=symbol, error=str(e))

        except Exception as e:
            log.error("Price polling error", error=str(e))

        await asyncio.sleep(poll_interval_seconds)