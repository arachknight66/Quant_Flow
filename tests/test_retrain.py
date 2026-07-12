import pytest
import pandas as pd
import shutil
from unittest.mock import AsyncMock
from backend.models.asset import Asset, AssetType
from tests.conftest import AsyncSessionLocal
from scripts.retrain_models import retrain_all_assets
from sqlalchemy import select

@pytest.mark.asyncio
async def test_retrain_all_assets_script(monkeypatch, db_session):
    # 1. Seed asset in DB
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Asset).where(Asset.symbol == "MSFT"))
        asset = res.scalar_one_or_none()
        if not asset:
            asset = Asset(
                symbol="MSFT",
                name="Microsoft",
                asset_type=AssetType.STOCK,
                exchange="NASDAQ",
                currency="USD"
            )
            session.add(asset)
            await session.commit()

    # 2. Mock MarketDataService.get_ohlcv to return a 150-bar dataframe
    import numpy as np
    rng = np.random.default_rng(42)
    n = 150
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    mock_df = pd.DataFrame({
        "Open": prices * 0.99,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Close": prices,
        "Volume": rng.uniform(1e6, 5e6, n),
    }, index=pd.date_range("2021-01-01", periods=n, freq="B", tz="UTC"))

    mock_get = AsyncMock(return_value=mock_df)
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        mock_get
    )

    # 3. Run retraining
    test_artifacts = "./ml/artifacts/test_retrain_dir"
    try:
        await retrain_all_assets(years=1, interval="1d", artifacts_dir=test_artifacts)
        
        # Verify it was called and saved model components exist
        from pathlib import Path
        model_path = Path(test_artifacts) / "MSFT" / "1d"
        assert model_path.exists()
        assert (model_path / "meta_model.joblib").exists()
        assert (model_path / "metadata.json").exists()
    finally:
        shutil.rmtree(test_artifacts, ignore_errors=True)
