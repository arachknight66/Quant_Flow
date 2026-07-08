import asyncio, pandas as pd, numpy as np, yfinance as yf
from datetime import datetime, timedelta, timezone
from typing import Optional
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from data_pipeline.collectors.base import BaseCollector, OHLCVRecord
from data_pipeline.validators.ohlcv_validator import validate_ohlcv_dataframe
import logging

log = structlog.get_logger()
VALID_INTERVALS = frozenset(["1m","2m","5m","15m","30m","60m","90m","1h","1d","5d","1wk","1mo","3mo"])
RATE_LIMIT_DELAY_SECONDS = 0.5

class YFinanceCollector(BaseCollector):
    def __init__(self):
        self._last_request_time: float = 0.0

    async def _rate_limit(self):
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY_SECONDS:
            await asyncio.sleep(RATE_LIMIT_DELAY_SECONDS - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30),
           retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)), reraise=True)
    def _fetch_sync(self, symbol, interval, start, end):
        ticker = yf.Ticker(symbol)
        return ticker.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
                              interval=interval, auto_adjust=True, back_adjust=False, actions=False)

    async def fetch_historical(self, symbol, interval, start, end=None) -> list[OHLCVRecord]:
        if interval not in VALID_INTERVALS:
            raise ValueError(f"Invalid interval '{interval}'")
        if end is None: end = datetime.now(timezone.utc)
        await self._rate_limit()
        loop = asyncio.get_event_loop()
        try:
            df = await loop.run_in_executor(None, self._fetch_sync, symbol, interval, start, end)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch {symbol}: {e}") from e
        if df.empty: return []
        df = validate_ohlcv_dataframe(df, symbol)
        records = []
        for ts, row in df.iterrows():
            timestamp = ts.to_pydatetime()
            if not timestamp.tzinfo:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            records.append(OHLCVRecord(
                symbol=symbol, interval=interval, ts=timestamp,
                open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]),  close=float(row["Close"]),
                volume=float(row.get("Volume", 0.0)),
                adj_close=float(row.get("Close", row["Close"])),
            ))
        return records

    async def fetch_latest(self, symbol, interval="1d") -> Optional[OHLCVRecord]:
        records = await self.fetch_historical(
            symbol, interval, start=datetime.now(timezone.utc) - timedelta(days=5))
        return records[-1] if records else None
