import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from data_pipeline.collectors.binance_collector import BinanceCollector
from data_pipeline.collectors.alphavantage_collector import AlphaVantageCollector

class MockResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code
    def json(self):
        return self._json_data
    def raise_for_status(self):
        pass

@pytest.mark.asyncio
async def test_binance_collector(monkeypatch):
    collector = BinanceCollector()

    mock_response = [
        [1672531200000, "16500.0", "16600.0", "16400.0", "16550.0", "100.0", 1672534800000]
    ]

    monkeypatch.setattr("httpx.AsyncClient.get", AsyncMock(return_value=MockResponse(mock_response)))

    start = datetime.now(timezone.utc) - timedelta(days=2)
    records = await collector.fetch_historical("BTC-USD", "1d", start)

    assert len(records) == 1
    rec = records[0]
    assert rec.symbol == "BTC-USD"
    assert rec.open == 16500.0
    assert rec.high == 16600.0
    assert rec.low == 16400.0
    assert rec.close == 16550.0
    assert rec.volume == 100.0

@pytest.mark.asyncio
async def test_binance_collector_pagination(monkeypatch):
    collector = BinanceCollector()

    call_count = 0
    async def mock_get(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockResponse([
                [1672531200000, "16500.0", "16600.0", "16400.0", "16550.0", "100.0", 1672534800000],
                [1672534800000, "16500.0", "16600.0", "16400.0", "16550.0", "100.0", 1672538400000]
            ])
        else:
            return MockResponse([])

    monkeypatch.setattr("httpx.AsyncClient.get", mock_get)

    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = datetime(2023, 1, 3, tzinfo=timezone.utc)
    records = await collector.fetch_historical("BTC-USD", "1d", start, end)

    assert len(records) == 2
    assert call_count == 2

@pytest.mark.asyncio
async def test_alphavantage_collector(monkeypatch):
    collector = AlphaVantageCollector(api_key="test_key")

    mock_response = {
        "Time Series (Daily)": {
            "2023-10-27": {
                "1. open": "166.91",
                "2. high": "168.96",
                "3. low": "166.83",
                "4. close": "168.22",
                "5. volume": "58499129"
            }
        }
    }

    monkeypatch.setattr("httpx.AsyncClient.get", AsyncMock(return_value=MockResponse(mock_response)))

    start = datetime(2023, 10, 1, tzinfo=timezone.utc)
    records = await collector.fetch_historical("AAPL", "1d", start)

    assert len(records) == 1
    rec = records[0]
    assert rec.symbol == "AAPL"
    assert rec.open == 166.91
    assert rec.high == 168.96
    assert rec.low == 166.83
    assert rec.close == 168.22
    assert rec.volume == 58499129.0
