import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from backend.core.config import settings
from backend.models.signal import Signal
from backend.models.asset import Asset
from backend.services.market_data_service import MarketDataService

log = structlog.get_logger()

async def evaluate_signal_outcome(
    db: AsyncSession, signal: Signal, market_service: MarketDataService
) -> Optional[dict]:
    """
    Returns None if not enough time has passed yet to evaluate
    (created_at + horizon trading days hasn't occurred yet), or if
    the outcome can't be determined (missing OHLCV data for the
    resolution date).
    Returns {"resolved": True, "correct": bool, "actual_return_pct": float,
             "resolution_date": str} otherwise.
    """
    if signal.resolved:
        return {
            "resolved": True,
            "correct": signal.outcome_correct,
            "actual_return_pct": signal.actual_return_pct,
            "resolution_date": (signal.created_at + timedelta(days=7)).isoformat() # fallback string, or resolution date if stored
        }

    # 1. Load asset
    asset_res = await db.execute(select(Asset).where(Asset.id == signal.asset_id))
    asset = asset_res.scalar_one_or_none()
    if not asset:
        log.warning("Asset not found for signal evaluation", asset_id=signal.asset_id)
        return None

    symbol = asset.symbol

    # 2. Fetch model metadata for horizon/threshold
    horizon = 5
    profit_threshold = 0.01

    model_path = Path(settings.MODEL_ARTIFACTS_DIR) / symbol.upper() / "1d"
    fallback_path = Path(settings.MODEL_ARTIFACTS_DIR) / "GENERAL" / "1d"
    metadata_file = None
    for p in [model_path, fallback_path]:
        if (p / "metadata.json").exists():
            metadata_file = p / "metadata.json"
            break

    if metadata_file:
        try:
            metadata = json.loads(metadata_file.read_text())
            horizon = metadata.get("prediction_horizon", 5)
            profit_threshold = metadata.get("profit_threshold", 0.01)
        except Exception as e:
            log.warning("Failed to parse model metadata", path=str(metadata_file), error=str(e))
    else:
        log.warning("No model metadata found. Using default parameters (5 days, 1% threshold).", symbol=symbol)

    # 3. Fetch OHLCV data starting from 10 days before signal creation to today
    # We fetch a wide enough window to cover weekend gaps and the horizon
    start_date = signal.created_at - timedelta(days=15)
    df = await market_service.get_ohlcv(symbol, interval="1d", start=start_date)
    if df.empty:
        log.warning("No OHLCV data found for signal symbol", symbol=symbol)
        return None

    # 4. Find the daily bar corresponding to the signal creation date
    # Normalize created_at to UTC date
    sig_date = signal.created_at.date()
    bar_idx = None
    for idx, ts in enumerate(df.index):
        if ts.date() >= sig_date:
            # Check that it's within a reasonable gap (at most 4 calendar days)
            if (ts.date() - sig_date).days <= 4:
                bar_idx = idx
                break

    if bar_idx is None:
        log.warning("Could not find matching daily bar for signal date", symbol=symbol, date=sig_date)
        return None

    # 5. Check if enough trading days have passed
    if len(df) <= bar_idx + horizon:
        # Not enough data yet
        return None

    # 6. Evaluate outcome
    close_t = float(df["Close"].iloc[bar_idx])
    res_bar = df.iloc[bar_idx + horizon]
    close_res = float(res_bar["Close"])
    resolution_date = df.index[bar_idx + horizon].date().isoformat()

    actual_return = (close_res - close_t) / close_t
    actual_return_pct = actual_return * 100

    action = signal.action.upper()
    correct = False

    if action == "BUY":
        correct = actual_return > profit_threshold
    elif action == "SELL":
        correct = actual_return < -profit_threshold
    else:
        # HOLD is never scored as correct/incorrect
        return None

    # Update database columns
    signal.resolved = True
    signal.outcome_correct = correct
    signal.actual_return_pct = actual_return_pct
    db.add(signal)
    await db.commit()

    return {
        "resolved": True,
        "correct": correct,
        "actual_return_pct": actual_return_pct,
        "resolution_date": resolution_date
    }
