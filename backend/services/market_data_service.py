# backend/services/market_data_service.py
"""
Market data service — the single source of truth for OHLCV data.

Caching strategy (three layers):
  Layer 1 — Redis (hot cache, seconds to minutes)
    For live prices and the most recent candles.
    TTL: 30 seconds for 1m data, 5 minutes for 1d data.

  Layer 2 — PostgreSQL (warm store, days to years)
    Full historical OHLCV. Persists across restarts.
    Updated by incremental collector runs.

  Layer 3 — yfinance/ccxt (cold source, network)
    Only hit when cache misses or stale.
    Rate-limited, retried, validated before storage.

Incremental fetch strategy:
  On every request, find the last stored timestamp.
  Only fetch from that timestamp forward.
  This dramatically reduces API calls.

Thread safety:
  Async throughout. Redis and asyncpg are both async-safe.
  No shared mutable state — each request gets its own DB session.
"""
import pandas as pd
import numpy as np
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text
import redis.asyncio as aioredis
import structlog

from backend.core.config import settings
from backend.models.asset import Asset, AssetType
from backend.models.ohlcv import OHLCVData
from data_pipeline.collectors.yfinance_collector import YFinanceCollector
from data_pipeline.collectors.base import OHLCVRecord

log = structlog.get_logger()

# ── Redis client singleton ──────────────────────────────────────────────────
_redis_client: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            password=settings.REDIS_PASSWORD,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return _redis_client

# ── Cache TTL strategy ──────────────────────────────────────────────────────
CACHE_TTL = {
    "1m":  30,          # 30 seconds — near real-time
    "5m":  60,          # 1 minute
    "15m": 120,
    "1h":  300,         # 5 minutes
    "1d":  300,         # 5 minutes (daily close doesn't change mid-day)
    "1wk": 3600,        # 1 hour
}

# How far back to fetch if we have no data at all (cold start)
COLD_START_DAYS = {
    "1m": 7,
    "5m": 30,
    "15m": 60,
    "1h": 180,
    "1d": 1825,   # 5 years of daily data
    "1wk": 3650,
}


class MarketDataService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.collector = YFinanceCollector()

    def _cache_key(self, symbol: str, interval: str, start: Optional[datetime] = None) -> str:
        """Deterministic cache key for OHLCV data."""
        components = f"{symbol}:{interval}"
        if start:
            components += f":{start.strftime('%Y%m%d')}"
        return f"ohlcv:{hashlib.md5(components.encode()).hexdigest()[:12]}"

    async def get_ohlcv(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Get OHLCV data. Checks cache → DB → API in that order.

        Returns DataFrame with columns: Open, High, Low, Close, Volume, adj_close
        Index: DatetimeTZ (UTC)
        """
        symbol = symbol.upper()
        now = datetime.now(timezone.utc)

        if start is None:
            lookback = COLD_START_DAYS.get(interval, 365)
            start = now - timedelta(days=lookback)

        if end is None:
            end = now

        # ── Layer 1: Redis cache ────────────────────────────────────────────
        if not force_refresh:
            cache_key = self._cache_key(symbol, interval, start)
            redis = await get_redis()

            try:
                cached = await redis.get(cache_key)
                if cached:
                    df = pd.read_json(cached, orient="split")
                    df.index = pd.to_datetime(df.index, utc=True)
                    log.debug("Cache hit", symbol=symbol, interval=interval)
                    return df
            except Exception as e:
                log.warning("Redis read failed", error=str(e))

        # ── Layer 2: PostgreSQL ─────────────────────────────────────────────
        asset = await self._get_or_create_asset(symbol)
        db_df = await self._fetch_from_db(asset.id, interval, start, end)

        # Determine if we need to fetch fresh data
        needs_refresh = (
            force_refresh
            or db_df.empty
            or self._is_stale(db_df, interval)
        )

        if needs_refresh:
            # ── Layer 3: API fetch ──────────────────────────────────────────
            fetch_start = start if db_df.empty else (db_df.index[-1] + timedelta(seconds=1))

            log.info(
                "Fetching from API",
                symbol=symbol,
                interval=interval,
                from_date=fetch_start.isoformat(),
            )

            try:
                new_records = await self.collector.fetch_historical(
                    symbol=symbol,
                    interval=interval,
                    start=fetch_start,
                    end=end,
                )

                if new_records:
                    await self._save_to_db(asset.id, new_records)
                    db_df = await self._fetch_from_db(asset.id, interval, start, end)
                    log.info("Saved new records", symbol=symbol, count=len(new_records))

            except Exception as e:
                log.error("API fetch failed", symbol=symbol, error=str(e))
                if db_df.empty:
                    raise RuntimeError(f"No data available for {symbol}: {e}") from e
                # Fall through to return stale data with warning

        # ── Write back to Redis cache ───────────────────────────────────────
        if not db_df.empty:
            try:
                redis = await get_redis()
                ttl = CACHE_TTL.get(interval, 300)
                cache_key = self._cache_key(symbol, interval, start)
                await redis.setex(
                    cache_key,
                    ttl,
                    db_df.to_json(orient="split", date_format="iso"),
                )
            except Exception as e:
                log.warning("Redis write failed", error=str(e))

        return db_df

    async def _get_or_create_asset(self, symbol: str) -> Asset:
        """Get or create an asset record."""
        result = await self.db.execute(
            select(Asset).where(Asset.symbol == symbol)
        )
        asset = result.scalar_one_or_none()

        if asset is None:
            # Detect asset type from symbol
            asset_type = AssetType.CRYPTO if "-USD" in symbol or "-USDT" in symbol else AssetType.STOCK
            asset = Asset(
                symbol=symbol,
                name=symbol,  # Will be enriched later
                asset_type=asset_type,
                currency="USD",
            )
            self.db.add(asset)
            await self.db.flush()  # Get the ID without committing
            log.info("Created new asset", symbol=symbol, type=asset_type)

        return asset

    async def _fetch_from_db(
        self,
        asset_id,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Fetch OHLCV rows from PostgreSQL into a DataFrame."""
        result = await self.db.execute(
            select(OHLCVData)
            .where(and_(
                OHLCVData.asset_id == asset_id,
                OHLCVData.interval == interval,
                OHLCVData.ts >= start,
                OHLCVData.ts <= end,
            ))
            .order_by(OHLCVData.ts.asc())
        )
        rows = result.scalars().all()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame([
            {
                "Open": r.open, "High": r.high, "Low": r.low,
                "Close": r.close, "Volume": r.volume, "adj_close": r.adj_close,
            }
            for r in rows
        ], index=pd.DatetimeIndex([r.ts for r in rows], tz="UTC"))

        return df

    async def _save_to_db(self, asset_id, records: list[OHLCVRecord]):
        """
        Upsert OHLCV records into PostgreSQL.
        Uses INSERT ... ON CONFLICT DO NOTHING to handle duplicates gracefully.
        """
        if not records:
            return

        # Batch insert using raw SQL for performance
        values = [
            {
                "asset_id": str(asset_id),
                "interval": r.interval,
                "ts": r.ts,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "adj_close": r.adj_close,
            }
            for r in records
        ]

        # Process in chunks of 1000 to avoid query size limits
        chunk_size = 1000
        for i in range(0, len(values), chunk_size):
            chunk = values[i:i + chunk_size]
            await self.db.execute(
                text("""
                    INSERT INTO ohlcv_data
                        (asset_id, interval, ts, open, high, low, close, volume, adj_close)
                    VALUES
                        (:asset_id, :interval, :ts, :open, :high, :low, :close, :volume, :adj_close)
                    ON CONFLICT (asset_id, interval, ts) DO NOTHING
                """),
                chunk,
            )

    def _is_stale(self, df: pd.DataFrame, interval: str) -> bool:
        """
        Determine if existing data is too old and needs refreshing.
        Compares last candle timestamp to current time.
        """
        if df.empty:
            return True

        last_ts = df.index[-1]
        now = datetime.now(timezone.utc)
        age = (now - last_ts).total_seconds()

        thresholds = {
            "1m": 120,
            "5m": 600,
            "15m": 1800,
            "1h": 7200,
            "1d": 86400 * 1.5,  # Allow 1.5 days — market closed on weekends
            "1wk": 86400 * 7,
        }
        return age > thresholds.get(interval, 3600)

    async def invalidate_cache(self, symbol: str, interval: str):
        """Force cache invalidation for a symbol/interval pair."""
        redis = await get_redis()
        pattern = f"ohlcv:*"
        keys = await redis.keys(pattern)
        for key in keys:
            await redis.delete(key)
        log.info("Cache invalidated", symbol=symbol, interval=interval)