import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from unittest.mock import AsyncMock
from backend.services.market_data_service import MarketDataService
from backend.models.asset import Asset, AssetType
from backend.models.ohlcv import OHLCVData
from data_pipeline.collectors.base import OHLCVRecord

# Test keys pattern matching
def test_scan_iter_pattern_isolated():
    """scan_iter pattern ohlcv:AAPL:* does NOT match ohlcv:MSFT:*."""
    import fnmatch
    pattern = "ohlcv:AAPL:*"
    assert fnmatch.fnmatch("ohlcv:AAPL:1d:xyz", pattern) is True
    assert fnmatch.fnmatch("ohlcv:MSFT:1d:xyz", pattern) is False

async def test_market_endpoints_and_cache(app_client: AsyncClient, db_session, mock_redis, monkeypatch):
    # Mock YFinanceCollector
    mock_records = [
        OHLCVRecord(
            symbol="AAPL", interval="1d", ts=datetime.now(timezone.utc) - timedelta(days=2),
            open=150.0, high=155.0, low=149.0, close=152.0, volume=10000.0, adj_close=152.0
        ),
        OHLCVRecord(
            symbol="AAPL", interval="1d", ts=datetime.now(timezone.utc) - timedelta(days=1),
            open=152.0, high=156.0, low=151.0, close=154.0, volume=12000.0, adj_close=154.0
        )
    ]
    mock_fetch = AsyncMock(return_value=mock_records)
    monkeypatch.setattr("data_pipeline.collectors.yfinance_collector.YFinanceCollector.fetch_historical", mock_fetch)

    # 1. First request -> Cache miss -> DB miss -> API fetch -> saved in DB -> saved in Redis cache
    resp = await app_client.get("/api/v1/market/ohlcv?symbol=AAPL&interval=1d&days=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["count"] == 2
    assert len(mock_fetch.mock_calls) == 1

    # 2. Second request -> Cache hit (from Redis)
    mock_fetch.reset_mock()
    resp = await app_client.get("/api/v1/market/ohlcv?symbol=AAPL&interval=1d&days=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert len(mock_fetch.mock_calls) == 0  # No API call, served from Cache!

    # 3. Test invalidate_cache deletes correct keys
    service = MarketDataService(db_session)
    
    # Pre-populate Redis with both AAPL and MSFT keys
    mock_redis.store["ohlcv:AAPL:1d:xyz"] = "AAPL-data"
    mock_redis.store["ohlcv:MSFT:1d:xyz"] = "MSFT-data"

    await service.invalidate_cache("AAPL")
    
    # Assert AAPL key is gone but MSFT key remains
    assert "ohlcv:AAPL:1d:xyz" not in mock_redis.store
    assert "ohlcv:MSFT:1d:xyz" in mock_redis.store

async def test_symbol_validation(app_client: AsyncClient):
    # Invalid symbols
    invalid_symbols = ["AAPL12345678", "AAPL!", "a_b", "LONG-SYMBOL-NAME"]
    for sym in invalid_symbols:
        resp = await app_client.get(f"/api/v1/market/ohlcv?symbol={sym}")
        assert resp.status_code == 422


async def test_search_returns_seeded_assets(app_client: AsyncClient, db_session):
    asset = Asset(
        symbol="MSFT",
        name="Microsoft Corporation",
        asset_type=AssetType.STOCK,
        exchange="NASDAQ"
    )
    db_session.add(asset)
    await db_session.commit()

    resp = await app_client.get("/api/v1/market/search?q=MSF")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    assert results[0]["symbol"] == "MSFT"
    assert results[0]["name"] == "Microsoft Corporation"


async def test_search_falls_back_to_yfinance(app_client: AsyncClient, monkeypatch):
    class MockTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            self.info = {
                "regularMarketPrice": 150.0,
                "longName": "Mock Ticker Inc",
                "exchange": "NYSE"
            }

    monkeypatch.setattr("yfinance.Ticker", MockTicker)

    resp = await app_client.get("/api/v1/market/search?q=TSLA")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["symbol"] == "TSLA"
    assert results[0]["name"] == "Mock Ticker Inc"


async def test_search_no_results(app_client: AsyncClient, monkeypatch):
    class MockTickerFailed:
        def __init__(self, symbol):
            self.info = {}

    monkeypatch.setattr("yfinance.Ticker", MockTickerFailed)

    resp = await app_client.get("/api/v1/market/search?q=UNKNOWN")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 0


async def test_data_health_endpoint(app_client: AsyncClient, mock_redis):
    resp = await app_client.get("/api/v1/market/health/data")
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "healthy"
    assert isinstance(res["redis_connected"], bool)
    assert isinstance(res["ohlcv_bars_in_db"], int)


