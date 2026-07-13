import asyncio
from sqlalchemy import select
from backend.core.database import AsyncSessionLocal
from backend.models.asset import Asset, AssetType

DEFAULT_ASSETS = [
    # Stocks
    {"symbol": "AAPL", "name": "Apple Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "TSLA", "name": "Tesla, Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "AMZN", "name": "Amazon.com, Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "META", "name": "Meta Platforms, Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "V", "name": "Visa Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "UNH", "name": "UnitedHealth Group Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "XOM", "name": "Exxon Mobil Corp.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "WMT", "name": "Walmart Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "PG", "name": "Procter & Gamble Co.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "LLY", "name": "Eli Lilly & Co.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "AVGO", "name": "Broadcom Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "MA", "name": "Mastercard Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "HD", "name": "Home Depot, Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "CVX", "name": "Chevron Corp.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "MRK", "name": "Merck & Co., Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "COST", "name": "Costco Wholesale Corp.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "PEP", "name": "PepsiCo, Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "KO", "name": "Coca-Cola Co.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "ADBE", "name": "Adobe Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "ORCL", "name": "Oracle Corp.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "BAC", "name": "Bank of America Corp.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "MCD", "name": "McDonald's Corp.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "CRM", "name": "Salesforce, Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "AMD", "name": "Advanced Micro Devices, Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "NFLX", "name": "Netflix, Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "TMO", "name": "Thermo Fisher Scientific Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "ABT", "name": "Abbott Laboratories", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    {"symbol": "CSCO", "name": "Cisco Systems, Inc.", "asset_type": AssetType.STOCK, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "NKE", "name": "Nike, Inc.", "asset_type": AssetType.STOCK, "exchange": "NYSE", "currency": "USD"},
    
    # Cryptos
    {"symbol": "BTC-USD", "name": "Bitcoin USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "ETH-USD", "name": "Ethereum USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "SOL-USD", "name": "Solana USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "BNB-USD", "name": "Binance Coin USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "ADA-USD", "name": "Cardano USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "XRP-USD", "name": "XRP USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "DOT-USD", "name": "Polkadot USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "DOGE-USD", "name": "Dogecoin USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "LTC-USD", "name": "Litecoin USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    {"symbol": "LINK-USD", "name": "Chainlink USD", "asset_type": AssetType.CRYPTO, "exchange": "CCCAGG", "currency": "USD"},
    
    # ETFs
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "asset_type": AssetType.ETF, "exchange": "NYSE Arca", "currency": "USD"},
    {"symbol": "QQQ", "name": "Invesco QQQ Trust", "asset_type": AssetType.ETF, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "GLD", "name": "SPDR Gold Shares", "asset_type": AssetType.ETF, "exchange": "NYSE Arca", "currency": "USD"},
    {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "asset_type": AssetType.ETF, "exchange": "NASDAQ", "currency": "USD"},
    {"symbol": "VXX", "name": "iPath Series B S&P 500 VIX Short-Term Futures ETN", "asset_type": AssetType.ETF, "exchange": "BATS", "currency": "USD"},
    {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "asset_type": AssetType.ETF, "exchange": "NYSE Arca", "currency": "USD"},
    {"symbol": "DIA", "name": "SPDR Dow Jones Industrial Average ETF Trust", "asset_type": AssetType.ETF, "exchange": "NYSE Arca", "currency": "USD"},
    {"symbol": "XLF", "name": "Financial Select Sector SPDR Fund", "asset_type": AssetType.ETF, "exchange": "NYSE Arca", "currency": "USD"},
    {"symbol": "XLK", "name": "Technology Select Sector SPDR Fund", "asset_type": AssetType.ETF, "exchange": "NYSE Arca", "currency": "USD"},
    {"symbol": "XLE", "name": "Energy Select Sector SPDR Fund", "asset_type": AssetType.ETF, "exchange": "NYSE Arca", "currency": "USD"},
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
