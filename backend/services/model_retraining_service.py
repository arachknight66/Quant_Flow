import asyncio
import structlog
from datetime import datetime, timezone
from sqlalchemy import select
from backend.core.database import get_db_context
from backend.models.asset import Asset
from backend.services.market_data_service import MarketDataService
from backend.services.ml_service import MLService

log = structlog.get_logger()
ml_service = MLService()

async def check_and_retrain_stale_models():
    """
    Scans the database for all assets, fetches their latest daily OHLCV data,
    and submits them for training. The MLService checks if the model is stale
    (trained > 30 days ago) before retraining.
    """
    log.info("Starting model retraining check...")
    async with get_db_context() as db:
        try:
            result = await db.execute(select(Asset))
            assets = result.scalars().all()
            if not assets:
                log.info("No assets found in database to retrain")
                return

            market_data_service = MarketDataService(db)
            for asset in assets:
                symbol = asset.symbol
                log.info("Checking model for symbol", symbol=symbol)
                try:
                    # Fetch 1d interval data (defaults to 5 years / 1825 days)
                    ohlcv_df = await market_data_service.get_ohlcv(symbol, "1d")
                    if len(ohlcv_df) < 200:
                        log.info("Insufficient data for training", symbol=symbol, bars=len(ohlcv_df))
                        continue

                    # MLService handles retraining decision and 30-day age checks
                    train_res = await ml_service.train_model_for_symbol(
                        symbol, "1d", ohlcv_df, force_retrain=False
                    )
                    log.info("Model training check completed", symbol=symbol, result=train_res)
                except Exception as e:
                    log.error("Failed to train model for symbol", symbol=symbol, error=str(e))
        except Exception as e:
            log.error("Error during model retraining check", error=str(e))

async def model_retraining_loop(poll_interval_hours: float = 168.0):
    """
    Background loop that runs model retraining check periodically.
    Default interval is 168 hours (weekly).
    """
    log.info("Model retraining background task initialized")
    # Brief initial startup sleep
    await asyncio.sleep(60.0)
    while True:
        try:
            await check_and_retrain_stale_models()
        except asyncio.CancelledError:
            log.info("Model retraining loop cancelled")
            raise
        except Exception as e:
            log.error("Unhandled error in model retraining loop", error=str(e))
        
        log.info("Model retraining loop sleeping", hours=poll_interval_hours)
        await asyncio.sleep(poll_interval_hours * 3600.0)
