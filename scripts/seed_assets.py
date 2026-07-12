import asyncio
from sqlalchemy import select
from backend.core.database import AsyncSessionLocal
from backend.models.asset import Asset, AssetType

DEFAULT_ASSETS = [
    {"symbol": "AAPL", "name": "Apple Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "TSLA", "name": "Tesla, Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "asset_type": AssetType.ETF, "exchange": "NYSE Arca", "currency": "USD"},
    {"symbol": "BTC-USD", "name": "Bitcoin USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "ETH-USD", "name": "Ethereum USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
]

async def seed():
    print("Starting asset seeding...")
    async with AsyncSessionLocal() as session:
        for item in DEFAULT_ASSETS:
            stmt = select(Asset).where(Asset.symbol == item["symbol"])
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                asset = Asset(**item)
                session.add(asset)
                print(f"Seeding asset: {item['symbol']}")
            else:
                print(f"Asset {item['symbol']} already exists, skipping")
        await session.commit()
    print("Seeding finished successfully.")

if __name__ == "__main__":
    asyncio.run(seed())
