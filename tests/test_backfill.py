import pytest
import pandas as pd
from unittest.mock import AsyncMock
from scripts.backfill_ohlcv import backfill

@pytest.mark.asyncio
async def test_backfill_ohlcv_script(monkeypatch):
    mock_df = pd.DataFrame({"Close": [150.0]})
    mock_get = AsyncMock(return_value=mock_df)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        mock_get
    )

    # Run backfill
    await backfill(["AAPL"], years=1, interval="1d")

    # Assert it was called
    assert mock_get.called
    assert mock_get.call_args[0][0] == "AAPL"
