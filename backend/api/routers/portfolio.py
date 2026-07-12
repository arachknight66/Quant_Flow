from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import uuid
from backend.core.database import get_db
from backend.services.auth_service import get_current_user
from backend.models.user import User
from backend.models.position import PortfolioPosition
from backend.models.asset import Asset
from backend.models.signal import Signal

router = APIRouter()

class PortfolioSummary(BaseModel):
    total_value_usd: float
    cash_usd: float
    invested_usd: float
    total_pnl_usd: float
    total_pnl_pct: float
    n_positions: int

class OpenPositionRequest(BaseModel):
    signal_id: uuid.UUID
    quantity: float
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    notes: Optional[str] = None

class ClosePositionRequest(BaseModel):
    exit_price: float
    exit_reason: Optional[str] = None

@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(current_user: User = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    # 1. Fetch all open positions
    res = await db.execute(
        select(PortfolioPosition)
        .where(PortfolioPosition.user_id == current_user.id, PortfolioPosition.is_open == True)
    )
    open_positions = res.scalars().all()

    # 2. Get current price for each open position
    from backend.services.market_data_service import MarketDataService
    service = MarketDataService(db)
    current_prices = {}
    
    for pos in open_positions:
        # Load asset details if needed
        res_asset = await db.execute(select(Asset).where(Asset.id == pos.asset_id))
        asset = res_asset.scalar_one()
        symbol = asset.symbol
        if symbol not in current_prices:
            try:
                df = await service.get_ohlcv(symbol, interval="1d", start=datetime.now(timezone.utc) - timedelta(days=10))
                if not df.empty:
                    current_prices[symbol] = float(df["Close"].iloc[-1])
                else:
                    current_prices[symbol] = pos.avg_entry_price
            except Exception:
                current_prices[symbol] = pos.avg_entry_price

    # 3. Perform financial calculations
    cash_usd = current_user.capital_usd or 0.0
    invested_usd = 0.0
    current_value_of_investments = 0.0

    for pos in open_positions:
        res_asset = await db.execute(select(Asset).where(Asset.id == pos.asset_id))
        asset = res_asset.scalar_one()
        sym = asset.symbol
        pos_cost = pos.quantity * pos.avg_entry_price
        pos_value = pos.quantity * current_prices.get(sym, pos.avg_entry_price)
        invested_usd += pos_cost
        current_value_of_investments += pos_value

    total_value_usd = cash_usd + current_value_of_investments
    total_pnl_usd = current_value_of_investments - invested_usd
    total_pnl_pct = (total_pnl_usd / invested_usd * 100) if invested_usd > 0 else 0.0

    return PortfolioSummary(
        total_value_usd=round(total_value_usd, 2),
        cash_usd=round(cash_usd, 2),
        invested_usd=round(invested_usd, 2),
        total_pnl_usd=round(total_pnl_usd, 2),
        total_pnl_pct=round(total_pnl_pct, 2),
        n_positions=len(open_positions)
    )

@router.get("/positions")
async def get_positions(current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(PortfolioPosition, Asset.symbol)
        .join(Asset, PortfolioPosition.asset_id == Asset.id)
        .where(PortfolioPosition.user_id == current_user.id)
    )
    results = res.all()
    out = []
    for pos, symbol in results:
        out.append({
            "id": str(pos.id),
            "symbol": symbol,
            "quantity": pos.quantity,
            "avg_entry_price": pos.avg_entry_price,
            "is_open": pos.is_open,
            "open_date": pos.open_date.isoformat(),
            "close_date": pos.close_date.isoformat() if pos.close_date else None,
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
            "notes": pos.notes
        })
    return out

@router.post("/positions/open")
async def open_position(request: OpenPositionRequest,
                        current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    # 1. Fetch signal
    res = await db.execute(select(Signal).where(Signal.id == request.signal_id, Signal.user_id == current_user.id))
    signal = res.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
        
    # 2. Check capital
    cost = request.quantity * request.entry_price
    if (current_user.capital_usd or 0.0) < cost:
        raise HTTPException(status_code=400, detail="Insufficient capital to open position")
        
    # 3. Deduct capital
    current_user.capital_usd -= cost
    
    # 4. Create position
    position = PortfolioPosition(
        user_id=current_user.id,
        asset_id=signal.asset_id,
        quantity=request.quantity,
        avg_entry_price=request.entry_price,
        is_open=True,
        stop_loss=request.stop_loss,
        take_profit=request.take_profit,
        signal_id=signal.id,
        notes=request.notes
    )
    db.add(position)
    await db.commit()
    return {"status": "success", "position_id": str(position.id), "new_cash_balance": current_user.capital_usd}

@router.post("/positions/{id}/close")
async def close_position(id: uuid.UUID,
                         request: ClosePositionRequest,
                         current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    # 1. Fetch position
    res = await db.execute(select(PortfolioPosition).where(PortfolioPosition.id == id, PortfolioPosition.user_id == current_user.id))
    position = res.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if not position.is_open:
        raise HTTPException(status_code=400, detail="Position is already closed")
        
    # 2. Compute sale value
    sale_value = position.quantity * request.exit_price
    
    # 3. Add back to capital
    if current_user.capital_usd is None:
        current_user.capital_usd = 0.0
    current_user.capital_usd += sale_value
    
    # 4. Close position
    position.is_open = False
    position.close_date = datetime.utcnow()
    position.notes = f"Closed: {request.exit_reason}" if request.exit_reason else position.notes
    
    await db.commit()
    pnl = sale_value - (position.quantity * position.avg_entry_price)
    return {"status": "success", "position_id": str(position.id), "pnl_usd": pnl, "new_cash_balance": current_user.capital_usd}

@router.get("/signals/history")
async def get_signal_history(limit: int = 50,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Signal).where(Signal.user_id == current_user.id)
        .order_by(desc(Signal.created_at)).limit(limit))
    return [{"id": str(s.id), "action": s.action, "confidence": s.confidence,
             "prob_profit": s.prob_profit, "model_version": s.model_version,
             "created_at": s.created_at.isoformat()} for s in result.scalars().all()]
