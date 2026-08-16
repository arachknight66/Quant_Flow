from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import uuid

from backend.core.database import get_db
from backend.services.auth_service import get_current_user
from backend.models.user import User
from backend.models.asset import Asset
from backend.models.alert_subscription import AlertSubscription

router = APIRouter()

class AlertSubscriptionRequest(BaseModel):
    symbol: str
    is_active: bool = True

class AlertSubscriptionResponse(BaseModel):
    id: str
    symbol: str
    name: str
    is_active: bool

@router.get("", response_model=list[AlertSubscriptionResponse])
async def get_alert_subscriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(AlertSubscription, Asset)
        .join(Asset, AlertSubscription.asset_id == Asset.id)
        .where(AlertSubscription.user_id == current_user.id)
    )
    items = res.all()
    
    return [
        AlertSubscriptionResponse(
            id=str(item.id),
            symbol=asset.symbol,
            name=asset.name,
            is_active=item.is_active
        )
        for item, asset in items
    ]

@router.post("", response_model=AlertSubscriptionResponse, status_code=201)
async def subscribe_to_alert(
    request: AlertSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    symbol = request.symbol.upper().strip()
    
    # Resolve asset
    res_asset = await db.execute(select(Asset).where(Asset.symbol == symbol))
    asset = res_asset.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Symbol not found in assets database")

    # Check existing subscription
    res_sub = await db.execute(
        select(AlertSubscription)
        .where(AlertSubscription.user_id == current_user.id, AlertSubscription.asset_id == asset.id)
    )
    sub = res_sub.scalar_one_or_none()
    
    if sub:
        sub.is_active = request.is_active
    else:
        sub = AlertSubscription(
            id=uuid.uuid4(),
            user_id=current_user.id,
            asset_id=asset.id,
            is_active=request.is_active
        )
        db.add(sub)
        
    await db.commit()
    await db.refresh(sub)
    
    return AlertSubscriptionResponse(
        id=str(sub.id),
        symbol=asset.symbol,
        name=asset.name,
        is_active=sub.is_active
    )

@router.delete("/{symbol}")
async def unsubscribe_from_alert(
    symbol: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    symbol = symbol.upper().strip()
    res = await db.execute(
        select(AlertSubscription)
        .join(Asset, AlertSubscription.asset_id == Asset.id)
        .where(AlertSubscription.user_id == current_user.id, Asset.symbol == symbol)
    )
    sub = res.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Alert subscription not found")
        
    await db.delete(sub)
    await db.commit()
    return {"status": "success"}
