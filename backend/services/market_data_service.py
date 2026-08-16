import pandas as pd, hashlib
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
_redis_client: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            password=settings.REDIS_PASSWORD, encoding="utf-8",
            decode_responses=True, max_connections=20,
        )
    return _redis_client

CACHE_TTL    = {"1m":30,"5m":60,"15m":120,"1h":300,"1d":300,"1wk":3600}
COLD_DAYS    = {"1m":7,"5m":30,"15m":60,"1h":180,"1d":1825,"1wk":3650}
STALE_SECS   = {"1m":120,"5m":600,"15m":1800,"1h":7200,"1d":129600,"1wk":604800}

class MarketDataService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.collector = YFinanceCollector()

    def _cache_key(self, symbol, interval, start=None):
        date_hash = hashlib.md5((start.strftime("%Y%m%d") if start else "nodate").encode()).hexdigest()[:8]
        return f"ohlcv:{symbol.upper()}:{interval}:{date_hash}"

    def _cache_key_pattern(self, symbol, interval=None):
        return f"ohlcv:{symbol.upper()}:{interval}:*" if interval else f"ohlcv:{symbol.upper()}:*"

    async def get_ohlcv(self, symbol, interval, start=None, end=None, force_refresh=False):
        symbol = symbol.upper()
        now    = datetime.now(timezone.utc)
        if start is None: start = now - timedelta(days=COLD_DAYS.get(interval, 365))
        if end   is None: end   = now

        if not force_refresh:
            cache_key = self._cache_key(symbol, interval, start)
            try:
                redis  = await get_redis()
                cached = await redis.get(cache_key)
                if cached:
                    df = pd.read_json(cached, orient="split")
                    df.index = pd.to_datetime(df.index, utc=True)
                    return df
            except Exception as e:
                log.warning("Redis read failed", error=str(e))

        asset  = await self._get_or_create_asset(symbol)
        db_df  = await self._fetch_from_db(asset.id, interval, start, end)
        needs_refresh = force_refresh or db_df.empty or self._is_stale(db_df, interval)

        if needs_refresh:
            fetch_start = start if db_df.empty else db_df.index[-1] + timedelta(seconds=1)
            try:
                new_records = await self.collector.fetch_historical(symbol, interval, fetch_start, end)
                if new_records:
                    await self._save_to_db(asset.id, new_records)
                    db_df = await self._fetch_from_db(asset.id, interval, start, end)
            except Exception as e:
                log.error("API fetch failed", symbol=symbol, error=str(e))
                if db_df.empty:
                    raise RuntimeError(f"No data available for {symbol}: {e}") from e

        if not db_df.empty:
            try:
                redis = await get_redis()
                await redis.setex(self._cache_key(symbol, interval, start),
                                  CACHE_TTL.get(interval, 300),
                                  db_df.to_json(orient="split", date_format="iso"))
            except Exception as e:
                log.warning("Redis write failed", error=str(e))

        return db_df

    async def _get_or_create_asset(self, symbol):
        result = await self.db.execute(select(Asset).where(Asset.symbol == symbol))
        asset  = result.scalar_one_or_none()
        if asset is None:
            currency = "USD"
            try:
                import yfinance as yf
                import asyncio
                ticker = yf.Ticker(symbol)
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, lambda: ticker.info)
                if info and "currency" in info:
                    currency = info["currency"]
            except Exception:
                pass
            asset_type = AssetType.CRYPTO if "-USD" in symbol or "-USDT" in symbol else AssetType.STOCK
            asset = Asset(symbol=symbol, name=symbol, asset_type=asset_type, currency=currency)
            self.db.add(asset)
            await self.db.flush()
        return asset

    async def _fetch_from_db(self, asset_id, interval, start, end):
        if start is not None and start.tzinfo is not None:
            start = start.astimezone(timezone.utc).replace(tzinfo=None)
        if end is not None and end.tzinfo is not None:
            end = end.astimezone(timezone.utc).replace(tzinfo=None)
        result = await self.db.execute(
            select(OHLCVData)
            .where(and_(OHLCVData.asset_id == asset_id, OHLCVData.interval == interval,
                        OHLCVData.ts >= start, OHLCVData.ts <= end))
            .order_by(OHLCVData.ts.asc()))
        rows = result.scalars().all()
        if not rows: return pd.DataFrame()
        return pd.DataFrame(
            [{"Open":r.open,"High":r.high,"Low":r.low,"Close":r.close,
              "Volume":r.volume,"adj_close":r.adj_close} for r in rows],
            index=pd.DatetimeIndex([r.ts for r in rows], tz="UTC"))

    async def _save_to_db(self, asset_id, records):
        if not records: return
        import hashlib
        values = []
        for r in records:
            h = hashlib.sha256(f"{asset_id}:{r.interval}:{r.ts}".encode("utf-8")).digest()
            rec_id = int.from_bytes(h[:8], byteorder="big", signed=True)
            values.append({
                "id": rec_id,
                "asset_id": str(asset_id),
                "interval": r.interval,
                "ts": r.ts,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "adj_close": r.adj_close
            })
        for i in range(0, len(values), 1000):
            await self.db.execute(text("""
                INSERT INTO ohlcv_data (id,asset_id,interval,ts,open,high,low,close,volume,adj_close)
                VALUES (:id,:asset_id,:interval,:ts,:open,:high,:low,:close,:volume,:adj_close)
                ON CONFLICT (asset_id,interval,ts) DO NOTHING
            """), values[i:i+1000])

    def _is_stale(self, df, interval):
        if df.empty: return True
        age = (datetime.now(timezone.utc) - df.index[-1]).total_seconds()
        return age > STALE_SECS.get(interval, 3600)

    async def invalidate_cache(self, symbol, interval=None):
        redis = await get_redis()
        pattern = self._cache_key_pattern(symbol, interval)
        deleted = 0
        async for key in redis.scan_iter(match=pattern, count=100):
            await redis.delete(key)
            deleted += 1
        log.info("Cache invalidated", symbol=symbol, keys_deleted=deleted)
