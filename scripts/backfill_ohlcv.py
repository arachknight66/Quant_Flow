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
os.environ.setdefault("SECRET_KEY", "backfill-script-key-not-for-production")
os.environ.setdefault("DEBUG", "true")

from backend.core.database import AsyncSessionLocal
from backend.services.market_data_service import MarketDataService

async def backfill(symbols: list[str], years: int, interval: str):
    start_date = datetime.now(timezone.utc) - timedelta(days=years * 365)
    async with AsyncSessionLocal() as db:
        service = MarketDataService(db)
        for symbol in symbols:
            symbol = symbol.strip().upper()
            print(f"Backfilling {symbol} ({interval}) for the last {years} years...")
            try:
                df = await service.get_ohlcv(symbol, interval=interval, start=start_date)
                print(f"  Successfully loaded {len(df)} bars for {symbol}")
            except Exception as e:
                print(f"  Error backfilling {symbol}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Backfill OHLCV data for specified symbols.")
    parser.add_argument("--symbols", required=True, help="Comma-separated ticker symbols (e.g. AAPL,MSFT,TSLA)")
    parser.add_argument("--years", type=int, default=5, help="Years of history to backfill")
    parser.add_argument("--interval", default="1d", help="Bar interval (e.g. 1d, 1h)")
    args = parser.parse_args()

    symbols_list = args.symbols.split(",")
    asyncio.run(backfill(symbols_list, args.years, args.interval))

if __name__ == "__main__":
    main()
