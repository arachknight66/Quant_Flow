# backend/api/routers/analysis.py
"""
Analysis endpoints — the core of the platform.
Fetches data, computes features, runs ML inference, applies risk engine.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta, timezone
import pandas as pd

from backend.core.database import get_db
from backend.core.config import settings
from backend.services.market_data_service import MarketDataService
from backend.services.risk_engine import RiskEngine, RiskTolerance
from backend.services.ml_service import MLService
from ml.features.technical_indicators import build_feature_matrix, IndicatorConfig
from shared.schemas.signal import SignalResponse

router = APIRouter()
risk_engine = RiskEngine()
ml_service = MLService()  # Singleton — loads model on startup


# ---- Request / Response schemas ----

class AnalysisRequest(BaseModel):
    symbol: str = Field(..., example="AAPL", description="Ticker symbol")
    asset_type: str = Field("stock", example="stock")
    timeframe: str = Field("1d", example="1d")
    risk_tolerance: RiskTolerance = Field(RiskTolerance.MODERATE)
    capital: Optional[float] = Field(
        None,
        ge=100,
        le=10_000_000,
        description="Available capital in USD. Required for position sizing.",
    )
    lookback_days: int = Field(365, ge=90, le=1825)


class IndicatorValues(BaseModel):
    rsi: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]
    bb_upper: Optional[float]
    bb_middle: Optional[float]
    bb_lower: Optional[float]
    bb_pct_b: Optional[float]
    atr: Optional[float]
    atr_pct: Optional[float]
    vol_20d: Optional[float]
    momentum_10: Optional[float]


class PositionSizing(BaseModel):
    position_value_usd: float
    allocation_pct: float
    n_shares: float
    stop_loss_price: float
    take_profit_price: float
    risk_amount_usd: float
    risk_reward_ratio: float
    kelly_fraction_full: float
    kelly_fraction_applied: float


class FullAnalysisResponse(BaseModel):
    symbol: str
    asset_type: str
    timeframe: str
    current_price: float
    price_change_24h_pct: float
    action: str                       # "BUY" | "HOLD" | "SELL"
    confidence: float                 # 0–1
    prob_profit: float                # Calibrated probability
    expected_return_lo: float
    expected_return_hi: float
    var_95: float                     # 95% VaR as positive number
    indicators: IndicatorValues
    position_sizing: Optional[PositionSizing]
    model_version: str
    walk_forward_auc: Optional[float]  # Most recent WF AUC
    backtest_sharpe: Optional[float]
    analysis_timestamp: datetime
    warnings: list[str]


@router.post("/analyze", response_model=FullAnalysisResponse)
async def analyze_asset(
    request: AnalysisRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Full ML analysis for a single asset.

    Pipeline:
    1. Fetch or retrieve cached OHLCV data
    2. Compute technical indicators
    3. Run ML model (if trained for this symbol/timeframe)
    4. Apply risk engine for position sizing
    5. Compute expected return range via Monte Carlo
    6. Return complete analysis with warnings
    """
    symbol = request.symbol.upper().strip()
    warnings = []

    # ---- 1. Fetch data ----
    market_service = MarketDataService(db)
    start = datetime.now(timezone.utc) - timedelta(days=request.lookback_days)

    try:
        ohlcv_df = await market_service.get_ohlcv(
            symbol=symbol,
            interval=request.timeframe,
            start=start,
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to fetch data for {symbol}: {e}")

    if len(ohlcv_df) < 60:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient data for {symbol}: only {len(ohlcv_df)} bars available. "
                   "Need at least 60."
        )

    # ---- 2. Compute indicators ----
    features = build_feature_matrix(ohlcv_df, drop_na=False)
    latest_features = features.iloc[-1]
    latest_close = float(ohlcv_df["Close"].iloc[-1])
    prev_close = float(ohlcv_df["Close"].iloc[-2]) if len(ohlcv_df) > 1 else latest_close
    price_change_24h = (latest_close - prev_close) / prev_close * 100

    # ---- 3. ML inference ----
    try:
        signal = await ml_service.predict(symbol, request.timeframe, features)
    except Exception as e:
        # Model not available — return HOLD with warning
        signal = {
            "action": "HOLD",
            "prob_profit": 0.50,
            "confidence": 0.0,
            "model_version": "none",
        }
        warnings.append(f"ML model unavailable ({e}). Showing HOLD by default.")

    # ---- 4. Risk / position sizing ----
    atr = float(latest_features.get("atr", latest_close * 0.02))

    position_sizing = None
    if request.capital and signal["action"] == "BUY":
        sizing = risk_engine.compute_position_size(
            capital=request.capital,
            win_probability=signal["prob_profit"],
            current_price=latest_close,
            atr=atr,
            risk_tolerance=request.risk_tolerance,
            confidence=signal["confidence"],
        )
        position_sizing = PositionSizing(**{
            k: v for k, v in sizing.items()
            if k in PositionSizing.model_fields
        })

    # ---- 5. Expected return range (simplified Monte Carlo) ----
    returns = ohlcv_df["Close"].pct_change().dropna()
    mu = float(returns.mean() * 252)
    sigma = float(returns.std() * (252 ** 0.5))
    n_horizon = 5  # 5-day horizon

    # Use GBM approximation for range
    expected_lo = latest_close * ((1 + mu * n_horizon / 252) - 2 * sigma * (n_horizon / 252) ** 0.5)
    expected_hi = latest_close * ((1 + mu * n_horizon / 252) + 2 * sigma * (n_horizon / 252) ** 0.5)
    expected_return_lo = (expected_lo - latest_close) / latest_close
    expected_return_hi = (expected_hi - latest_close) / latest_close

    # ---- 6. VaR ----
    var_95 = risk_engine.compute_var(returns, confidence_level=0.95)

    # ---- 7. Confidence warnings ----
    if signal["confidence"] < 0.2:
        warnings.append(
            "Model confidence is low — signal is close to random. "
            "Consider waiting for higher conviction."
        )
    if abs(price_change_24h) > 5:
        warnings.append(
            f"Asset moved {price_change_24h:+.1f}% in the last session. "
            "High recent volatility — position sizing is more conservative."
        )
    if float(latest_features.get("vol_20d", 0)) > 0.40:
        warnings.append(
            "Annualised volatility >40%. This is a high-risk asset. "
            "Ensure position sizes reflect your risk tolerance."
        )

    warnings.append(
        "All signals are probabilistic. No model guarantees profit. "
        "This is not financial advice."
    )

    return FullAnalysisResponse(
        symbol=symbol,
        asset_type=request.asset_type,
        timeframe=request.timeframe,
        current_price=latest_close,
        price_change_24h_pct=round(price_change_24h, 2),
        action=signal["action"],
        confidence=round(signal["confidence"], 3),
        prob_profit=round(signal["prob_profit"], 3),
        expected_return_lo=round(expected_return_lo * 100, 2),
        expected_return_hi=round(expected_return_hi * 100, 2),
        var_95=round(var_95 * 100, 3),
        indicators=IndicatorValues(
            rsi=_safe_float(latest_features.get("rsi")),
            macd=_safe_float(latest_features.get("macd")),
            macd_signal=_safe_float(latest_features.get("macd_signal")),
            macd_hist=_safe_float(latest_features.get("macd_hist")),
            bb_upper=_safe_float(latest_features.get("bb_upper")),
            bb_middle=_safe_float(latest_features.get("bb_middle")),
            bb_lower=_safe_float(latest_features.get("bb_lower")),
            bb_pct_b=_safe_float(latest_features.get("bb_pct_b")),
            atr=_safe_float(latest_features.get("atr")),
            atr_pct=_safe_float(latest_features.get("atr_pct")),
            vol_20d=_safe_float(latest_features.get("vol_20d")),
            momentum_10=_safe_float(latest_features.get("momentum_10")),
        ),
        position_sizing=position_sizing,
        model_version=signal.get("model_version", "none"),
        walk_forward_auc=await ml_service.get_model_auc(symbol, request.timeframe),
        backtest_sharpe=None,  # Populated after backtest is run
        analysis_timestamp=datetime.now(timezone.utc),
        warnings=warnings,
    )


def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return round(v, 6) if not (v != v) else None  # NaN check
    except (TypeError, ValueError):
        return None


# ---- Backtest endpoint ----

class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "1d"
    start_date: str = Field(..., example="2020-01-01")
    end_date: str = Field(..., example="2024-01-01")
    initial_capital: float = Field(10_000.0, ge=1000)
    risk_tolerance: RiskTolerance = RiskTolerance.MODERATE
    slippage_bps: float = Field(5.0, ge=0, le=100)
    commission_pct: float = Field(0.1, ge=0, le=2.0)


@router.post("/backtest")
async def run_backtest(
    request: BacktestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Run a complete backtest and return performance metrics + equity curve.

    This is a potentially slow operation (seconds to minutes depending on
    date range and asset). In production, offload to a background task
    and return a job_id; poll for completion.
    """
    from ml.backtesting.engine import BacktestEngine, SlippageModel, CommissionModel
    from ml.backtesting.engine import BacktestEngine

    symbol = request.symbol.upper().strip()
    start = datetime.fromisoformat(request.start_date).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(request.end_date).replace(tzinfo=timezone.utc)

    market_service = MarketDataService(db)
    ohlcv_df = await market_service.get_ohlcv(symbol, request.timeframe, start, end)

    if len(ohlcv_df) < 300:
        raise HTTPException(422, "Need at least 300 bars for a meaningful backtest")

    model = await ml_service.get_model(symbol, request.timeframe)
    if model is None:
        raise HTTPException(
            422,
            f"No trained model found for {symbol}/{request.timeframe}. "
            "Train a model first via POST /analysis/train"
        )

    engine = BacktestEngine(
        initial_capital=request.initial_capital,
        risk_tolerance=request.risk_tolerance,
        slippage_model=SlippageModel(fixed_bps=request.slippage_bps),
        commission_model=CommissionModel(percentage=request.commission_pct / 100),
    )

    results = engine.run(ohlcv_df, model)
    return results