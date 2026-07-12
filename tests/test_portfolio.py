import pytest
from httpx import AsyncClient
from backend.services.auth_service import auth_service
from backend.models.user import User
from backend.models.asset import Asset, AssetType
from backend.models.signal import Signal
from tests.conftest import AsyncSessionLocal
from sqlalchemy import select

@pytest.mark.asyncio
async def test_portfolio_paper_trading_flow(app_client: AsyncClient, monkeypatch):
    # 1. Setup user with capital
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == "portfolio_user@example.com"))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                email="portfolio_user@example.com",
                hashed_password="some-hashed-password",
                risk_tolerance="moderate",
                capital_usd=100000.0,
                is_active=True
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        user_id = user.id

        # Seed asset
        result_asset = await session.execute(select(Asset).where(Asset.symbol == "AAPL"))
        asset = result_asset.scalar_one_or_none()
        if not asset:
            asset = Asset(
                symbol="AAPL",
                name="Apple Inc.",
                asset_type=AssetType.STOCK,
                exchange="NASDAQ",
                currency="USD"
            )
            session.add(asset)
            await session.commit()
            await session.refresh(asset)
        asset_id = asset.id

        # Seed signal
        signal = Signal(
            user_id=user_id,
            asset_id=asset_id,
            action="BUY",
            confidence=0.8,
            prob_profit=0.7,
            model_version="v1"
        )
        session.add(signal)
        await session.commit()
        await session.refresh(signal)
        signal_id = signal.id

    # 2. Get Access Token
    token = auth_service.create_access_token(user_id=user_id, email="portfolio_user@example.com")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Requested-With": "XMLHttpRequest"
    }

    # 3. Open Position
    open_payload = {
        "signal_id": str(signal_id),
        "quantity": 10.0,
        "entry_price": 150.0,
        "stop_loss": 140.0,
        "take_profit": 170.0,
        "notes": "Testing paper trading open"
    }
    resp = await app_client.post("/api/v1/portfolio/positions/open", json=open_payload, headers=headers)
    assert resp.status_code == 200
    open_data = resp.json()
    assert open_data["status"] == "success"
    assert "position_id" in open_data
    position_id = open_data["position_id"]
    assert open_data["new_cash_balance"] == 98500.0 # 100000 - 1500

    # Mock MarketDataService.get_ohlcv for AAPL to return a price of 160.0
    import pandas as pd
    mock_df = pd.DataFrame({"Close": [160.0]}, index=[pd.Timestamp.now()])
    from unittest.mock import AsyncMock
    monkeypatch.setattr(
        "backend.services.market_data_service.MarketDataService.get_ohlcv",
        AsyncMock(return_value=mock_df)
    )

    # 4. Get Summary
    resp = await app_client.get("/api/v1/portfolio/summary", headers=headers)
    assert resp.status_code == 200
    summary_data = resp.json()
    assert summary_data["cash_usd"] == 98500.0
    assert summary_data["invested_usd"] == 1500.0
    assert summary_data["total_value_usd"] == 100100.0 # 98500 + 10 * 160
    assert summary_data["total_pnl_usd"] == 100.0
    assert summary_data["total_pnl_pct"] == 6.67 # 100 / 1500 * 100
    assert summary_data["n_positions"] == 1

    # 5. Get Positions list
    resp = await app_client.get("/api/v1/portfolio/positions", headers=headers)
    assert resp.status_code == 200
    positions_list = resp.json()
    assert len(positions_list) >= 1
    assert any(p["id"] == position_id for p in positions_list)

    # 6. Close Position
    close_payload = {
        "exit_price": 160.0,
        "exit_reason": "Take profit hit"
    }
    resp = await app_client.post(f"/api/v1/portfolio/positions/{position_id}/close", json=close_payload, headers=headers)
    assert resp.status_code == 200
    close_data = resp.json()
    assert close_data["status"] == "success"
    assert close_data["pnl_usd"] == 100.0
    assert close_data["new_cash_balance"] == 100100.0
