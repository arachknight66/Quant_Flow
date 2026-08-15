from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
import asyncio, json
import structlog
from datetime import datetime, timezone
from typing import Dict, Set

log = structlog.get_logger()
router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.connections: Dict[WebSocket, Set[str]] = {}
        self.symbol_subscribers: Dict[str, Set[WebSocket]] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections[ws] = set()

    def disconnect(self, ws: WebSocket):
        for sym in self.connections.pop(ws, set()):
            self.symbol_subscribers.get(sym, set()).discard(ws)

    def subscribe(self, ws: WebSocket, symbol: str):
        symbol = symbol.upper()
        self.connections[ws].add(symbol)
        self.symbol_subscribers.setdefault(symbol, set()).add(ws)

    def unsubscribe(self, ws: WebSocket, symbol: str):
        symbol = symbol.upper()
        self.connections[ws].discard(symbol)
        self.symbol_subscribers.get(symbol, set()).discard(ws)

    async def broadcast_to_symbol(self, symbol: str, data: dict):
        dead = set()
        payload = json.dumps(data)
        for ws in self.symbol_subscribers.get(symbol.upper(), set()):
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
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return
    try:
        from backend.services.auth_service import auth_service
        from backend.core.database import AsyncSessionLocal
        from sqlalchemy import select
        from backend.models.user import User

        payload = auth_service.decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001)
            return

        try:
            from backend.services.market_data_service import get_redis
            redis = await get_redis()
            jti = payload.get("jti")
            if jti and await redis.get(f"revoked:{jti}"):
                await websocket.close(code=4001)
                return
        except Exception as e:
            log.warning("WS revocation check bypassed", error=str(e))

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.id == payload.get("sub")))
            user = result.scalar_one_or_none()
            if not user or not user.is_active:
                await websocket.close(code=4001)
                return
    except Exception:
        await websocket.close(code=4001)
        return

    await manager.connect(websocket)
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = json.loads(raw)
                action = msg.get("action")
                symbol = msg.get("symbol", "").upper()
                if action == "subscribe" and symbol:
                    manager.subscribe(websocket, symbol)
                    await websocket.send_text(json.dumps({"type":"subscribed","symbol":symbol}))
                elif action == "unsubscribe" and symbol:
                    manager.unsubscribe(websocket, symbol)
                elif action == "ping":
                    await websocket.send_text(json.dumps({"type":"pong"}))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type":"keepalive"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log.error("WebSocket error", error=str(e))
        manager.disconnect(websocket)

async def price_polling_task(poll_interval_seconds: float = 5.0):
    """Phase 2.1 fix: now actually started in main.py lifespan."""
    import yfinance as yf
    log.info("Price polling task started", interval=poll_interval_seconds)
    while True:
        try:
            active = manager.active_symbols
            if active:
                data = yf.download(" ".join(active), period="1d", interval="1m",
                                   progress=False)
                for symbol in active:
                    try:
                        sd = data[symbol] if len(active) > 1 and symbol in data.columns.get_level_values(0) else data
                        if sd is None or sd.empty: continue
                        latest = sd.iloc[-1]; prev = sd.iloc[-2] if len(sd) > 1 else latest
                        cp, pp = float(latest["Close"]), float(prev["Close"])
                        await manager.broadcast_to_symbol(symbol, {
                            "type":"price_update","symbol":symbol,
                            "price":round(cp,4), "change_pct":round((cp-pp)/pp*100,3),
                            "volume":float(latest.get("Volume",0)),
                            "high":float(latest["High"]),"low":float(latest["Low"]),
                            "timestamp":datetime.now(timezone.utc).isoformat()})
                    except Exception as e:
                        log.warning("Symbol processing failed", symbol=symbol, error=str(e))
        except Exception as e:
            log.error("Price polling error", error=str(e))
        await asyncio.sleep(poll_interval_seconds)
