import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from data_pipeline.collectors.google_finance_collector import GoogleFinanceCollector

class MockResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
    def raise_for_status(self):
        pass

@pytest.mark.asyncio
async def test_google_finance_collector_parse(monkeypatch):
    collector = GoogleFinanceCollector()

    mock_html = """
    <html>
      <head><title>Apple Inc (AAPL) Stock Price - Google Finance</title></head>
      <body>
        <div class="YMlKec">$333.02</div>
        <div class="YMlKec">$321.79</div>
        <div class="YMlKec">$334.37</div>
        <div class="YMlKec">$321.62</div>
      </body>
    </html>
    """

    monkeypatch.setattr("httpx.AsyncClient.get", AsyncMock(return_value=MockResponse(mock_html)))

    start = datetime.now(timezone.utc) - timedelta(days=2)
    records = await collector.fetch_historical("AAPL", "1d", start)

    assert len(records) == 1
    rec = records[0]
    assert rec.symbol == "AAPL"
    assert rec.close == 333.02
    assert rec.open == 321.79
    assert rec.high == 334.37
    assert rec.low == 321.62
