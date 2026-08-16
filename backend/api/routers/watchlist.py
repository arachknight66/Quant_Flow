from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
import uuid

from backend.core.database import get_db
from backend.services.auth_service import get_current_user
from backend.models.user import User
from backend.models.asset import Asset, AssetType
from backend.models.watchlist import WatchlistItem

router = APIRouter()

class AddWatchlistItemRequest(BaseModel):
    symbol: str
    notes: Optional[str] = None

class WatchlistItemResponse(BaseModel):
    id: str
    asset_id: str
    symbol: str
    name: str
    asset_type: str
    currency: str
    current_price: Optional[float]
    added_at: str
    notes: Optional[str]

async def get_or_create_asset(db: AsyncSession, symbol: str) -> Optional[Asset]:
    symbol = symbol.upper().strip()
    result = await db.execute(select(Asset).where(Asset.symbol == symbol))
    asset = result.scalar_one_or_none()
    if asset:
        return asset

    # Fallback to yfinance
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if info.get("regularMarketPrice") or info.get("price") or info.get("previousClose") or info.get("regularMarketOpen"):
            asset_type = AssetType.CRYPTO if "-" in symbol else AssetType.STOCK
            asset = Asset(
                id=uuid.uuid4(),
                symbol=symbol,
                name=info.get("longName", info.get("shortName", symbol)),
                asset_type=asset_type,
                exchange=info.get("exchange", "NASDAQ"),
                currency=info.get("currency", "USD")
            )
            db.add(asset)
            await db.commit()
            await db.refresh(asset)
            return asset
    except Exception:
        pass
    return None

@router.get("", response_model=list[WatchlistItemResponse])
async def get_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    from backend.services.market_data_service import MarketDataService
    res = await db.execute(
        select(WatchlistItem, Asset)
        .join(Asset, WatchlistItem.asset_id == Asset.id)
        .where(WatchlistItem.user_id == current_user.id)
    )
    items = res.all()
    
    market_service = MarketDataService(db)
    out = []
    for item, asset in items:
        current_price = None
        try:
            df = await market_service.get_ohlcv(asset.symbol, interval="1d", start=datetime.now(timezone.utc) - timedelta(days=10))
            if not df.empty:
                current_price = float(df["Close"].iloc[-1])
        except Exception:
            pass
            
        out.append(
            WatchlistItemResponse(
                id=str(item.id),
                asset_id=str(asset.id),
                symbol=asset.symbol,
                name=asset.name,
                asset_type=asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type),
                currency=asset.currency,
                current_price=current_price,
                added_at=item.added_at.isoformat(),
                notes=item.notes
            )
        )
    return out

@router.post("", response_model=WatchlistItemResponse, status_code=201)
async def add_to_watchlist(
    request: AddWatchlistItemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    symbol = request.symbol.upper().strip()
    
    # Check duplicate
    res_exist = await db.execute(
        select(WatchlistItem)
        .join(Asset, WatchlistItem.asset_id == Asset.id)
        .where(WatchlistItem.user_id == current_user.id, Asset.symbol == symbol)
    )
    if res_exist.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Symbol is already on the watchlist")

    # Resolve asset
    asset = await get_or_create_asset(db, symbol)
    if not asset:
        raise HTTPException(status_code=404, detail="Symbol cannot be resolved")

    item = WatchlistItem(
        id=uuid.uuid4(),
        user_id=current_user.id,
        asset_id=asset.id,
        notes=request.notes
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return WatchlistItemResponse(
        id=str(item.id),
        asset_id=str(asset.id),
        symbol=asset.symbol,
        name=asset.name,
        asset_type=asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type),
        currency=asset.currency,
        current_price=None,
        added_at=item.added_at.isoformat(),
        notes=item.notes
    )

@router.delete("/{asset_id}")
async def remove_from_watchlist(
    asset_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == current_user.id, WatchlistItem.asset_id == asset_id)
    )
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    await db.delete(item)
    await db.commit()
    return {"status": "success"}
