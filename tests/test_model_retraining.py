import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch
from backend.services.model_retraining_service import check_and_retrain_stale_models
from backend.models.asset import Asset, AssetType
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
async def test_check_and_retrain_stale_models(db_session: AsyncSession):
    # Seed an asset in db
    asset = Asset(
        symbol="AAPL",
        name="Apple Inc.",
        asset_type=AssetType.STOCK,
        exchange="NASDAQ",
        currency="USD"
    )
    db_session.add(asset)
    await db_session.commit()

    # Create synthetic OHLCV dataframe
    df = pd.DataFrame(
        {"Close": [100.0] * 210},
        index=pd.date_range("2020-01-01", periods=210)
    )

    with patch("backend.services.market_data_service.MarketDataService.get_ohlcv", new_callable=AsyncMock) as mock_get_ohlcv, \
         patch("backend.services.ml_service.MLService.train_model_for_symbol", new_callable=AsyncMock) as mock_train:
        
        mock_get_ohlcv.return_value = df
        mock_train.return_value = {"status": "trained"}

        await check_and_retrain_stale_models()

        mock_get_ohlcv.assert_called_once_with("AAPL", "1d")
        mock_train.assert_called_once()
