from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class SignalResponse(BaseModel):
    action: str
    prob_profit: float
    confidence: float
    model_version: str
    error: Optional[str] = None

class BacktestSignal(BaseModel):
    timestamp: datetime
    action: str
    prob_profit: float
    confidence: float
    model_version: str
