from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.database import get_db
from backend.services.market_data_service import MarketDataService
from ml.features.technical_indicators import build_feature_matrix
from backend.monitoring.model_monitor import ModelMonitor
import re

router = APIRouter()

@router.get("/drift")
async def check_model_drift(
    symbol: str = Query("AAPL"),
    db: AsyncSession = Depends(get_db),
):
    symbol = symbol.upper()
    if not re.match(r'^[A-Z0-9\-\.]{1,10}$', symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol format")
        
    market_data_service = MarketDataService(db)
    try:
        # Fetch daily data
        ohlcv_df = await market_data_service.get_ohlcv(symbol, "1d")
        if len(ohlcv_df) < 60:
            raise HTTPException(status_code=400, detail="Insufficient data for drift analysis")
            
        features = build_feature_matrix(ohlcv_df, drop_na=True)
        if len(features) < 30:
             raise HTTPException(status_code=400, detail="Insufficient feature rows for drift analysis")
             
        # Reference features: first 80%, Live features: last 20%
        split_idx = int(len(features) * 0.8)
        ref_features = features.iloc[:split_idx]
        live_features = features.iloc[split_idx:]
        
        monitor = ModelMonitor()
        monitor.set_reference_distribution(ref_features, reference_accuracy=0.55)
        
        # Check drift
        alerts = monitor.check_drift(live_features, window_days=len(live_features))
        
        # Format alerts
        alerts_data = [
            {
                "feature_name": a.feature_name,
                "drift_type": a.drift_type,
                "statistic": a.statistic,
                "p_value": a.p_value,
                "severity": a.severity,
                "message": a.message
            }
            for a in alerts
        ]
        
        status = "normal"
        if any(a.severity == "critical" for a in alerts):
            status = "critical"
        elif any(a.severity == "warning" for a in alerts):
            status = "warning"
            
        return {
            "symbol": symbol,
            "reference_samples": len(ref_features),
            "live_samples": len(live_features),
            "alerts_count": len(alerts_data),
            "alerts": alerts_data,
            "status": status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Drift analysis failed: {str(e)}")
