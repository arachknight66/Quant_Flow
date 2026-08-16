from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator
import re
from typing import Optional
from datetime import datetime, timedelta, timezone
from backend.core.limiter import limiter
import pandas as pd
from backend.core.database import get_db
from backend.core.config import settings
from backend.services.market_data_service import MarketDataService
from backend.services.risk_engine import RiskEngine, RiskTolerance
from backend.services.ml_service import MLService
from ml.features.technical_indicators import build_feature_matrix
from shared.schemas.signal import SignalResponse

router = APIRouter()
risk_engine = RiskEngine()
ml_service  = MLService()

class AnalysisRequest(BaseModel):
    symbol: str = Field(..., pattern=r"^[A-Z0-9\-\.]{1,10}$", example="AAPL")
    asset_type: str = Field("stock")
    timeframe: str = Field("1d")
    risk_tolerance: RiskTolerance = Field(RiskTolerance.MODERATE)
    capital: Optional[float] = Field(None, ge=100, le=10_000_000)
    lookback_days: int = Field(1825, ge=90, le=1825)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        if not re.match(r'^[A-Z0-9\-\.]{1,10}$', v.upper()):
            raise ValueError("Invalid symbol format")
        return v.upper()

class IndicatorValues(BaseModel):
    rsi: Optional[float]; macd: Optional[float]; macd_signal: Optional[float]
    macd_hist: Optional[float]; bb_upper: Optional[float]; bb_middle: Optional[float]
    bb_lower: Optional[float]; bb_pct_b: Optional[float]; atr: Optional[float]
    atr_pct: Optional[float]; vol_20d: Optional[float]; momentum_10: Optional[float]

class PositionSizing(BaseModel):
    position_value_usd: float; allocation_pct: float; n_shares: float
    stop_loss_price: float; take_profit_price: float; risk_amount_usd: float
    risk_reward_ratio: float; kelly_fraction_full: float; kelly_fraction_applied: float

class FullAnalysisResponse(BaseModel):
    symbol: str; asset_type: str; timeframe: str; current_price: float
    price_change_24h_pct: float; action: str; confidence: float; prob_profit: float
    expected_return_lo: float; expected_return_hi: float; var_95: float
    indicators: IndicatorValues; position_sizing: Optional[PositionSizing]
    model_version: str; walk_forward_auc: Optional[float]; backtest_sharpe: Optional[float]
    analysis_timestamp: datetime; warnings: list[str]; currency: str = "USD"
    regime: Optional[str] = None
    regime_confidence: Optional[float] = None
    garch_vol_forecast: Optional[float] = None

def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return round(v, 6) if v == v else None
    except (TypeError, ValueError):
        return None

@router.post("/analyze", response_model=FullAnalysisResponse)
@limiter.limit("10/minute")
async def analyze_asset(request: Request, request_data: AnalysisRequest, db: AsyncSession = Depends(get_db)):
    symbol   = request_data.symbol.upper().strip()
    warnings = []
    service  = MarketDataService(db)
    start    = datetime.now(timezone.utc) - timedelta(days=request_data.lookback_days)
    try:
        ohlcv_df = await service.get_ohlcv(symbol=symbol, interval=request_data.timeframe, start=start)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to fetch {symbol}: {e}")

    from sqlalchemy import select
    from backend.models.asset import Asset
    result = await db.execute(select(Asset).where(Asset.symbol == symbol))
    asset = result.scalar_one_or_none()
    currency = asset.currency if asset else "USD"
    if len(ohlcv_df) < 60:
        raise HTTPException(status_code=422, detail=f"Insufficient data: {len(ohlcv_df)} bars")
    features      = build_feature_matrix(ohlcv_df, drop_na=False)
    latest_features = features.iloc[-1]
    latest_close  = float(ohlcv_df["Close"].iloc[-1])
    prev_close    = float(ohlcv_df["Close"].iloc[-2]) if len(ohlcv_df) > 1 else latest_close
    price_change  = (latest_close - prev_close) / prev_close * 100
    try:
        signal = await ml_service.predict(symbol, request_data.timeframe, features)
    except Exception as e:
        signal   = {"action":"HOLD","prob_profit":0.50,"confidence":0.0,"model_version":"none"}
        warnings.append(f"ML model unavailable: {e}")
    atr = float(latest_features.get("atr", latest_close * 0.02))
    position_sizing = None
    if request_data.capital and signal["action"] == "BUY":
        sizing = risk_engine.compute_position_size(
            capital=request_data.capital, win_probability=signal["prob_profit"],
            current_price=latest_close, atr=atr,
            risk_tolerance=request_data.risk_tolerance, confidence=signal["confidence"])
        position_sizing = PositionSizing(**{k: v for k, v in sizing.items()
                                            if k in PositionSizing.model_fields})
    returns  = ohlcv_df["Close"].pct_change().dropna()
    mu, sigma = float(returns.mean() * 252), float(returns.std() * 252 ** 0.5)
    n_h = 5
    expected_lo = latest_close * ((1 + mu*n_h/252) - 2*sigma*(n_h/252)**0.5)
    expected_hi = latest_close * ((1 + mu*n_h/252) + 2*sigma*(n_h/252)**0.5)
    var_95 = risk_engine.compute_var(returns, confidence_level=0.95)
    if signal["confidence"] < 0.2:
        warnings.append("Model confidence is low — signal is close to random.")
    warnings.append("All signals are probabilistic. This is not financial advice.")

    # Optionally persist the signal in the database if user is authenticated
    current_user = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            from backend.services.auth_service import auth_service
            from backend.models.user import User
            from sqlalchemy import select
            payload = auth_service.decode_token(token)
            if payload.get("type") == "access":
                from backend.services.market_data_service import get_redis
                redis = await get_redis()
                jti = payload.get("jti")
                if not (jti and await redis.get(f"revoked:{jti}")):
                    res = await db.execute(select(User).where(User.id == payload.get("sub")))
                    current_user = res.scalar_one_or_none()
        except Exception:
            pass

    if current_user:
        try:
            from backend.models.asset import Asset
            from backend.models.signal import Signal
            res_asset = await db.execute(select(Asset).where(Asset.symbol == symbol))
            asset = res_asset.scalar_one_or_none()
            if asset:
                clean_snapshot = {}
                for k, v in latest_features.to_dict().items():
                    try:
                        clean_snapshot[k] = float(v) if v == v else None
                    except Exception:
                        clean_snapshot[k] = str(v)
                
                db_signal = Signal(
                    user_id=current_user.id,
                    asset_id=asset.id,
                    action=signal["action"],
                    confidence=signal["confidence"],
                    prob_profit=signal["prob_profit"],
                    kelly_fraction=position_sizing.kelly_fraction_applied if position_sizing else None,
                    suggested_allocation=position_sizing.allocation_pct if position_sizing else None,
                    expected_return_lo=(expected_lo - latest_close) / latest_close * 100,
                    expected_return_hi=(expected_hi - latest_close) / latest_close * 100,
                    var_95=var_95,
                    sharpe_est=None,
                    features_snapshot=clean_snapshot,
                    model_version=signal.get("model_version", "none")
                )
                
                # Check for active alert subscription and trigger email alert if signal changes
                try:
                    from backend.models.alert_subscription import AlertSubscription
                    res_sub = await db.execute(
                        select(AlertSubscription)
                        .where(AlertSubscription.user_id == current_user.id,
                               AlertSubscription.asset_id == asset.id,
                               AlertSubscription.is_active == True)
                    )
                    if res_sub.scalar_one_or_none():
                        res_prev = await db.execute(
                            select(Signal)
                            .where(Signal.user_id == current_user.id, Signal.asset_id == asset.id)
                            .order_by(Signal.created_at.desc())
                            .limit(1)
                        )
                        prev_signal = res_prev.scalar_one_or_none()
                        if prev_signal and prev_signal.action != signal["action"]:
                            from backend.services.email_service import send_signal_alert_email
                            await send_signal_alert_email(
                                email=current_user.email,
                                symbol=symbol,
                                old_action=prev_signal.action,
                                new_action=signal["action"]
                            )
                except Exception as alert_err:
                    warnings.append(f"Alert processing issue: {alert_err}")

                db.add(db_signal)
                await db.commit()
        except Exception as e:
            warnings.append(f"Could not persist signal in database: {e}")

    # Extract GARCH + HMM regime data
    regime = None
    if "regime_bull" in latest_features and float(latest_features["regime_bull"]) == 1.0:
        regime = "bull"
    elif "regime_bear" in latest_features and float(latest_features["regime_bear"]) == 1.0:
        regime = "bear"
    elif "regime_sideways" in latest_features and float(latest_features["regime_sideways"]) == 1.0:
        regime = "sideways"

    regime_entropy = latest_features.get("regime_entropy")
    regime_confidence = None
    if regime_entropy is not None and regime_entropy == regime_entropy:
        regime_confidence = float(1.0 - regime_entropy)
        regime_confidence = max(0.0, min(1.0, regime_confidence))

    garch_vol_val = latest_features.get("garch_vol_forecast", latest_features.get("garch_vol_1d", latest_features.get("garch_vol")))
    garch_vol_forecast = None
    if garch_vol_val is not None and garch_vol_val == garch_vol_val:
        garch_vol_forecast = float(garch_vol_val)

    return FullAnalysisResponse(
        symbol=symbol, asset_type=request_data.asset_type, timeframe=request_data.timeframe,
        current_price=latest_close, price_change_24h_pct=round(price_change, 2),
        action=signal["action"], confidence=round(signal["confidence"], 3),
        prob_profit=round(signal["prob_profit"], 3),
        expected_return_lo=round((expected_lo - latest_close) / latest_close * 100, 2),
        expected_return_hi=round((expected_hi - latest_close) / latest_close * 100, 2),
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
        walk_forward_auc=await ml_service.get_model_auc(symbol, request_data.timeframe),
        backtest_sharpe=None, analysis_timestamp=datetime.now(timezone.utc), warnings=warnings, currency=currency,
        regime=regime,
        regime_confidence=regime_confidence,
        garch_vol_forecast=garch_vol_forecast
    )

class BacktestRequest(BaseModel):
    symbol: str = Field(..., pattern=r"^[A-Z0-9\-\.]{1,10}$", example="AAPL")
    timeframe: str = "1d"
    start_date: str = Field(..., example="2020-01-01")
    end_date:   str = Field(..., example="2024-01-01")
    initial_capital: float = Field(10_000.0, ge=1000)
    risk_tolerance: RiskTolerance = RiskTolerance.MODERATE
    slippage_bps: float = Field(5.0, ge=0, le=100)
    commission_pct: float = Field(0.1, ge=0, le=2.0)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        if not re.match(r'^[A-Z0-9\-\.]{1,10}$', v.upper()):
            raise ValueError("Invalid symbol format")
        return v.upper()

@router.post("/backtest")
async def run_backtest(request: BacktestRequest, db: AsyncSession = Depends(get_db)):
    from ml.backtesting.engine import BacktestEngine, SlippageModel, CommissionModel
    symbol = request.symbol.upper().strip()
    start  = datetime.fromisoformat(request.start_date).replace(tzinfo=timezone.utc)
    end    = datetime.fromisoformat(request.end_date).replace(tzinfo=timezone.utc)
    ohlcv_df = await MarketDataService(db).get_ohlcv(symbol, request.timeframe, start, end)
    if len(ohlcv_df) < 300:
        raise HTTPException(422, "Need at least 300 bars for a meaningful backtest")
    model = await ml_service.get_model(symbol, request.timeframe)
    if model is None:
        raise HTTPException(422, f"No trained model for {symbol}/{request.timeframe}")
    engine = BacktestEngine(
        initial_capital=request.initial_capital, risk_tolerance=request.risk_tolerance,
        slippage_model=SlippageModel(fixed_bps=request.slippage_bps),
        commission_model=CommissionModel(percentage=request.commission_pct / 100))
    return engine.run(ohlcv_df, model)

class ModelInfoResponse(BaseModel):
    symbol: str
    timeframe: str
    version: str
    trained_at: str
    prediction_horizon: int
    profit_threshold: float
    n_features: int
    feature_names: list[str]
    feature_importances: Optional[dict[str, float]] = None
    mean_auc: Optional[float] = None
    std_auc: Optional[float] = None
    mean_brier: Optional[float] = None
    n_folds: Optional[int] = None
    model_age_days: int
    staleness_warning: bool

@router.get("/model-info", response_model=ModelInfoResponse)
async def get_model_info(
    symbol: str,
    timeframe: str = "1d"
):
    symbol = symbol.upper().strip()
    import json
    model_dir = ml_service._model_path(symbol, timeframe)
    meta_file = model_dir / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(404, f"Model metadata not found for {symbol}/{timeframe}")
    
    try:
        with open(meta_file, "r") as f:
            meta = json.load(f)
    except Exception as e:
        raise HTTPException(500, f"Failed to load metadata: {str(e)}")

    wf_metrics = meta.get("walk_forward_metrics", {})
    fold_metrics = wf_metrics.get("fold_metrics", [])
    
    trained_at_str = meta.get("trained_at", datetime.utcnow().isoformat())
    try:
        trained_at_dt = datetime.fromisoformat(trained_at_str)
    except ValueError:
        trained_at_dt = datetime.utcnow()
        
    if trained_at_dt.tzinfo is not None:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.utcnow()
    model_age_days = (now - trained_at_dt).days
    staleness_warning = model_age_days > 30

    feature_names = meta.get("feature_names", [])

    return ModelInfoResponse(
        symbol=symbol,
        timeframe=timeframe,
        version=meta.get("version", "unknown"),
        trained_at=trained_at_str,
        prediction_horizon=meta.get("prediction_horizon", 5),
        profit_threshold=meta.get("profit_threshold", 0.01),
        n_features=len(feature_names),
        feature_names=feature_names,
        feature_importances=meta.get("feature_importances"),
        mean_auc=wf_metrics.get("mean_auc"),
        std_auc=wf_metrics.get("std_auc"),
        mean_brier=wf_metrics.get("mean_brier"),
        n_folds=len(fold_metrics) if fold_metrics else None,
        model_age_days=model_age_days,
        staleness_warning=staleness_warning
    )
