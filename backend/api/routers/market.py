from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Optional
from backend.core.database import get_db
from backend.services.market_data_service import MarketDataService

router = APIRouter()

class OHLCVBar(BaseModel):
    t: str; o: float; h: float; l: float; c: float; v: float

class OHLCVResponse(BaseModel):
    symbol: str; interval: str; bars: list[OHLCVBar]
    count: int; first_ts: Optional[str]; last_ts: Optional[str]

@router.get("/ohlcv", response_model=OHLCVResponse)
async def get_ohlcv(symbol: str = Query(..., pattern=r"^[A-Z0-9\-\.]{1,10}$"), interval: str = Query("1d"),
                    days: int = Query(365, ge=1, le=1825),
                    db: AsyncSession = Depends(get_db)):
    symbol = symbol.upper().strip()
    start  = datetime.now(timezone.utc) - timedelta(days=days)
    service = MarketDataService(db)
    try:
        df = await service.get_ohlcv(symbol=symbol, interval=interval, start=start)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}/{interval}")
    bars = [OHLCVBar(t=ts.isoformat(), o=round(float(row["Open"]),4),
                     h=round(float(row["High"]),4), l=round(float(row["Low"]),4),
                     c=round(float(row["Close"]),4), v=round(float(row.get("Volume",0)),0))
            for ts, row in df.iterrows()]
    return OHLCVResponse(symbol=symbol, interval=interval, bars=bars, count=len(bars),
                         first_ts=bars[0].t if bars else None,
                         last_ts=bars[-1].t if bars else None)

class AssetSearchResult(BaseModel):
    symbol: str; name: str; asset_type: str; exchange: Optional[str]

@router.get("/search", response_model=list[AssetSearchResult])
async def search_assets(q: str = Query(..., min_length=1, max_length=20),
                        db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, or_
    from backend.models.asset import Asset
    q = q.upper().strip()
    result = await db.execute(
        select(Asset).where(or_(Asset.symbol.ilike(f"{q}%"),
                                Asset.name.ilike(f"%{q}%"))).limit(10))
    assets = result.scalars().all()
    if not assets:
        try:
            import yfinance as yf
            info = yf.Ticker(q).info
            if info.get("regularMarketPrice"):
                return [AssetSearchResult(symbol=q, name=info.get("longName", q),
                                          asset_type="crypto" if "-" in q else "stock",
                                          exchange=info.get("exchange"))]
        except Exception:
            pass
        return []
    return [AssetSearchResult(symbol=a.symbol, name=a.name,
                               asset_type=a.asset_type.value, exchange=a.exchange)
            for a in assets]

@router.get("/health/data")
async def data_health(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, func
    from backend.models.ohlcv import OHLCVData
    from backend.models.asset import Asset
    from backend.services.market_data_service import get_redis
    n_assets = (await db.execute(select(func.count()).select_from(Asset))).scalar()
    n_bars   = (await db.execute(select(func.count()).select_from(OHLCVData))).scalar()
    latest   = (await db.execute(select(func.max(OHLCVData.ts)).select_from(OHLCVData))).scalar()
    redis_ok = await (await get_redis()).ping()
    return {"status": "healthy", "assets_in_db": n_assets, "ohlcv_bars_in_db": n_bars,
            "latest_bar_ts": str(latest) if latest else None, "redis_connected": redis_ok}
