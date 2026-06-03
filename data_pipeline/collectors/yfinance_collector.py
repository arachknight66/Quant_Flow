# data_pipeline/collectors/yfinance_collector.py
"""
YFinance data collector with:
- Exponential backoff retry logic
- Rate limiting
- Data validation
- Async execution via thread pool (yfinance is sync)
- Incremental updates (only fetch what's missing)
"""
import asyncio
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone
from typing import Optional
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import logging

from data_pipeline.collectors.base import BaseCollector, OHLCVRecord
from data_pipeline.validators.ohlcv_validator import validate_ohlcv_dataframe

log = structlog.get_logger()

# Valid intervals supported by yfinance
VALID_INTERVALS = frozenset([
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h",
    "1d", "5d", "1wk", "1mo", "3mo"
])

# yfinance rate limits (approximate) — be conservative
RATE_LIMIT_DELAY_SECONDS = 0.5


class YFinanceCollector(BaseCollector):
    """
    Collects OHLCV data from Yahoo Finance via yfinance library.

    LIMITATIONS (be honest about these):
    - Yahoo Finance data is free but not guaranteed accurate
    - Intraday data limited to last 60 days (varies by interval)
    - Crypto data quality is lower than dedicated exchanges
    - No official API — subject to breaking changes
    - Not suitable for HFT or tick-level analysis

    For production, supplement with:
    - Alpha Vantage (stocks, fundamentals)
    - Binance API (crypto)
    - Polygon.io (institutional-grade, paid)
    """

    def __init__(self):
        self._last_request_time: float = 0.0

    async def _rate_limit(self):
        """Ensures minimum delay between API calls."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY_SECONDS:
            await asyncio.sleep(RATE_LIMIT_DELAY_SECONDS - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)),
        before_sleep=before_sleep_log(logging.getLogger(), logging.WARNING),
        reraise=True,
    )
    def _fetch_sync(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """
        Synchronous yfinance call wrapped for retry.
        yfinance is inherently synchronous; we run it in a thread pool
        to avoid blocking the async event loop.
        """
        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            auto_adjust=True,   # Adjust for splits and dividends
            back_adjust=False,
            actions=False,
        )
        return df

    async def fetch_historical(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: Optional[datetime] = None,
    ) -> list[OHLCVRecord]:
        """
        Fetch historical OHLCV data asynchronously.

        Args:
            symbol: Ticker symbol (e.g. "AAPL", "BTC-USD")
            interval: Time interval (e.g. "1d", "1h")
            start: Start datetime (UTC)
            end: End datetime (UTC), defaults to now

        Returns:
            List of validated OHLCVRecord objects

        Raises:
            ValueError: If interval invalid or data fails validation
            RuntimeError: If fetch fails after retries
        """
        if interval not in VALID_INTERVALS:
            raise ValueError(f"Invalid interval '{interval}'. Valid: {VALID_INTERVALS}")

        if end is None:
            end = datetime.now(timezone.utc)

        await self._rate_limit()

        log.info("Fetching OHLCV", symbol=symbol, interval=interval,
                 start=start.isoformat(), end=end.isoformat())

        # Run synchronous yfinance call in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        try:
            df = await loop.run_in_executor(
                None,  # Use default thread pool
                self._fetch_sync,
                symbol, interval, start, end,
            )
        except Exception as e:
            log.error("YFinance fetch failed", symbol=symbol, error=str(e))
            raise RuntimeError(f"Failed to fetch data for {symbol}: {e}") from e

        if df.empty:
            log.warning("No data returned", symbol=symbol, interval=interval)
            return []

        # Validate and clean
        df = validate_ohlcv_dataframe(df, symbol)

        # Convert to our internal schema
        records = []
        for ts, row in df.iterrows():
            # Ensure timezone-aware timestamps
            if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
                timestamp = ts.to_pydatetime()
            else:
                timestamp = ts.to_pydatetime().replace(tzinfo=timezone.utc)

            records.append(OHLCVRecord(
                symbol=symbol,
                interval=interval,
                ts=timestamp,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0.0)),
                adj_close=float(row.get("Close", row["Close"])),
            ))

        log.info("Fetch complete", symbol=symbol, records=len(records))
        return records

    async def fetch_latest(self, symbol: str, interval: str = "1d") -> OHLCVRecord | None:
        """Fetch the most recent single candle."""
        records = await self.fetch_historical(
            symbol=symbol,
            interval=interval,
            start=datetime.now(timezone.utc) - timedelta(days=5),
        )
        return records[-1] if records else None