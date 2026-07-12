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

