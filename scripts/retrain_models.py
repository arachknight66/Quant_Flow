#!/usr/bin/env python3
import argparse
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Ensure required env vars are set for local script run
os.environ.setdefault("SECRET_KEY", "retrain-script-key-not-for-production")
os.environ.setdefault("DEBUG", "true")

from backend.core.database import AsyncSessionLocal
from backend.models.asset import Asset
from backend.services.market_data_service import MarketDataService
from ml.features.technical_indicators import build_feature_matrix
from ml.models.ensemble_stacker import EnsembleStackerModel
from sqlalchemy import select

async def retrain_all_assets(years: int, interval: str, artifacts_dir: str):
    start_date = datetime.now(timezone.utc) - timedelta(days=years * 365)
    async with AsyncSessionLocal() as db:
        service = MarketDataService(db)
        
        # 1. Fetch all active assets in the database
        res = await db.execute(select(Asset))
        assets = res.scalars().all()
        if not assets:
            print("No assets found in the database. Run seed_assets.py first.")
            return

        print(f"Found {len(assets)} assets to retrain.")

        for asset in assets:
            symbol = asset.symbol
            print(f"\nRetraining model for {symbol} ({interval})...")
            try:
                # 2. Get OHLCV data
                df = await service.get_ohlcv(symbol, interval=interval, start=start_date)
                if df.empty or len(df) < 100:
                    print(f"  Skipping {symbol}: insufficient data points ({len(df)})")
                    continue

                # 3. Build features
                features = build_feature_matrix(df, drop_na=False)

                # 4. Train Ensemble Stacker
                print(f"  Fitting Ensemble Stacker on {len(features)} rows...")
                stacker = EnsembleStackerModel(prediction_horizon=5, profit_threshold=0.01)
                fit_res = stacker.fit_and_stack(features, df["Close"], n_splits=3)
                print(f"  Out-of-sample Stacker Mean AUC: {fit_res['mean_auc']:.4f}")

                # 5. Save model
                save_path = Path(artifacts_dir) / symbol.upper() / interval
                stacker.save(str(save_path))
                print(f"  Model saved to {save_path}")

            except Exception as e:
                print(f"  Error retraining {symbol}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Retrain ML models for all database assets.")
    parser.add_argument("--years", type=int, default=5, help="Years of history to train on")
    parser.add_argument("--interval", default="1d", help="Bar interval")
    parser.add_argument("--artifacts", default="./ml/artifacts", help="Artifacts output directory")
    args = parser.parse_args()

    asyncio.run(retrain_all_assets(args.years, args.interval, args.artifacts))

if __name__ == "__main__":
    main()
