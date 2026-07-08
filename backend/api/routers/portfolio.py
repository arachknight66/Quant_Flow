from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from backend.core.database import get_db
from backend.services.auth_service import get_current_user
from backend.models.user import User

router = APIRouter()

class PortfolioSummary(BaseModel):
    total_value_usd: float; cash_usd: float; invested_usd: float
    total_pnl_usd: float; total_pnl_pct: float; n_positions: int

@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(current_user: User = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    return PortfolioSummary(total_value_usd=current_user.capital_usd or 0.0,
                            cash_usd=current_user.capital_usd or 0.0,
                            invested_usd=0.0, total_pnl_usd=0.0,
                            total_pnl_pct=0.0, n_positions=0)

@router.get("/positions")
async def get_positions(current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    return []

@router.get("/signals/history")
async def get_signal_history(limit: int = 50,
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, desc
    from backend.models.signal import Signal
    result = await db.execute(
        select(Signal).where(Signal.user_id == current_user.id)
        .order_by(desc(Signal.created_at)).limit(limit))
    return [{"id": str(s.id), "action": s.action, "confidence": s.confidence,
             "prob_profit": s.prob_profit, "model_version": s.model_version,
             "created_at": s.created_at.isoformat()} for s in result.scalars().all()]
