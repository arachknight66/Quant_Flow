import httpx
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
import structlog
from data_pipeline.collectors.base import BaseCollector, OHLCVRecord

log = structlog.get_logger()

class AlphaVantageCollector(BaseCollector):
    """
    Data collector using the Alpha Vantage REST API.
    Uses ALPHA_VANTAGE_API_KEY from environment variables.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ALPHA_VANTAGE_API_KEY", "demo")
        self.base_url = "https://www.alphavantage.co/query"

    async def fetch_historical(self, symbol: str, interval: str,
                               start: datetime, end: Optional[datetime] = None) -> list[OHLCVRecord]:
        if interval != "1d":
            raise ValueError("AlphaVantageCollector only supports '1d' daily interval currently.")

        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol.upper(),
            "apikey": self.api_key,
            "outputsize": "full"
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(self.base_url, params=params, timeout=15.0)
                resp.raise_for_status()
                raw_data = resp.json()
            except Exception as e:
                log.error("Failed to fetch from Alpha Vantage", symbol=symbol, error=str(e))
                raise RuntimeError(f"Alpha Vantage fetch error: {e}")

        if "Error Message" in raw_data:
            raise RuntimeError(f"Alpha Vantage API error: {raw_data['Error Message']}")
        if "Note" in raw_data:
            log.warning("Alpha Vantage API limit warning", note=raw_data["Note"])
            return []

        time_series = raw_data.get("Time Series (Daily)")
        if not time_series:
            return []

        records = []
        for date_str, bar in time_series.items():
            ts = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if ts < start:
                continue
            if end and ts > end:
                continue

            records.append(OHLCVRecord(
                symbol=symbol,
                interval=interval,
                ts=ts,
                open=float(bar["1. open"]),
                high=float(bar["2. high"]),
                low=float(bar["3. low"]),
                close=float(bar["4. close"]),
                volume=float(bar["5. volume"]),
                adj_close=float(bar["4. close"])
            ))

        records.sort(key=lambda r: r.ts)
        return records

    async def fetch_latest(self, symbol: str, interval: str = "1d") -> Optional[OHLCVRecord]:
        start = datetime.now(timezone.utc) - timedelta(days=5)
        records = await self.fetch_historical(symbol, interval, start=start)
        return records[-1] if records else None
