import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
import structlog
from data_pipeline.collectors.base import BaseCollector, OHLCVRecord

log = structlog.get_logger()

class BinanceCollector(BaseCollector):
    """
    Data collector using the Binance Public REST API (spot klines).
    Maps symbols like BTC-USD to BTCUSDT.
    """
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"

    def _map_symbol(self, symbol: str) -> str:
        s = symbol.upper().replace("-", "")
        if s.endswith("USD"):
            s = s[:-3] + "USDT"
        return s

    def _map_interval(self, interval: str) -> str:
        return interval

    async def fetch_historical(self, symbol: str, interval: str,
                               start: datetime, end: Optional[datetime] = None) -> list[OHLCVRecord]:
        mapped_symbol = self._map_symbol(symbol)
        mapped_interval = self._map_interval(interval)
        
        if end is None:
            end = datetime.now(timezone.utc)

        records = []
        current_start = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        async with httpx.AsyncClient() as client:
            while current_start < end_ms:
                params = {
                    "symbol": mapped_symbol,
                    "interval": mapped_interval,
                    "startTime": current_start,
                    "endTime": end_ms,
                    "limit": 1000
                }
                try:
                    resp = await client.get(f"{self.base_url}/klines", params=params, timeout=10.0)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    log.error("Failed to fetch klines from Binance", symbol=symbol, error=str(e))
                    raise RuntimeError(f"Binance fetch error: {e}")

                if not data:
                    break

                for item in data:
                    ts = datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc)
                    records.append(OHLCVRecord(
                        symbol=symbol,
                        interval=interval,
                        ts=ts,
                        open=float(item[1]),
                        high=float(item[2]),
                        low=float(item[3]),
                        close=float(item[4]),
                        volume=float(item[5]),
                        adj_close=float(item[4])
                    ))

                last_time = data[-1][0]
                if last_time <= current_start:
                    break
                current_start = last_time + 1

        return records

    async def fetch_latest(self, symbol: str, interval: str = "1d") -> Optional[OHLCVRecord]:
        start = datetime.now(timezone.utc) - timedelta(days=5)
        records = await self.fetch_historical(symbol, interval, start=start)
        return records[-1] if records else None
