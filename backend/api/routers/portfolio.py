# backend/api/routers/portfolio.py
"""
Portfolio endpoints — holdings, P&L, allocation breakdown, signal history.

CRITICAL FIX: backend/main.py does
    from backend.api.routers import market, analysis, portfolio, auth, ws
which crashed at import time because this file never existed.

Phase 1 (this file): read-only views — portfolio summary is a placeholder
sourced from User.capital_usd until real position tracking exists.
Phase 2 (paper trading, see roadmap): real order management, the
portfolio_positions table, live P&L computed from open positions.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.core.database import get_db
from backend.services.auth_service import get_current_user
from backend.models.user import User

router = APIRouter()


class PortfolioSummary(BaseModel):
    total_value_usd: float
    cash_usd: float
    invested_usd: float
    total_pnl_usd: float
    total_pnl_pct: float
    n_positions: int


class PortfolioPosition(BaseModel):
    symbol: str
    asset_type: str
    quantity: float
    avg_entry_price: float
    current_price: float
    current_value: float
    unrealised_pnl: float
    unrealised_pnl_pct: float
    weight_pct: float


@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return portfolio-level P&L summary.
    Phase 1: returns placeholder values — real positions arrive in Phase 2
    (paper trading engine) once portfolio_positions is populated.
    """
    return PortfolioSummary(
        total_value_usd=current_user.capital_usd or 0.0,
        cash_usd=current_user.capital_usd or 0.0,
        invested_usd=0.0,
        total_pnl_usd=0.0,
        total_pnl_pct=0.0,
        n_positions=0,
    )


@router.get("/positions", response_model=list[PortfolioPosition])
async def get_positions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current open positions. Empty until Phase 2 paper trading lands."""
    return []


@router.get("/signals/history")
async def get_signal_history(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return recent signals generated for this user."""
    from sqlalchemy import select, desc
    from backend.models.signal import Signal

    result = await db.execute(
        select(Signal)
        .where(Signal.user_id == current_user.id)
        .order_by(desc(Signal.created_at))
        .limit(limit)
    )
    signals = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "action": s.action,
            "confidence": s.confidence,
            "prob_profit": s.prob_profit,
            "model_version": s.model_version,
            "created_at": s.created_at.isoformat(),
        }
        for s in signals
    ]