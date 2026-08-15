import pytest
from pathlib import Path
import json
import pandas as pd
from unittest.mock import MagicMock
from backend.services.ml_service import MLService
from backend.core.config import settings

@pytest.mark.asyncio
async def test_get_model_falls_back_to_general(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACTS_DIR", str(tmp_path))

    # Create GENERAL/1d model metadata
    general_dir = tmp_path / "GENERAL" / "1d"
    general_dir.mkdir(parents=True, exist_ok=True)
    (general_dir / "metadata.json").write_text(json.dumps({
        "trained_at": "2026-08-15T00:00:00",
        "walk_forward_metrics": [{"roc_auc": 0.55}]
    }))

    ml_service = MLService()
    mock_model = MagicMock()
    monkeypatch.setattr(ml_service, "_load_sync", lambda path: mock_model)

    model = await ml_service.get_model("AAPL", "1d")
    assert model is mock_model
    assert ml_service._metadata_cache["AAPL_1d"]["walk_forward_metrics"][0]["roc_auc"] == 0.55


@pytest.mark.asyncio
async def test_get_model_returns_none_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACTS_DIR", str(tmp_path))
    ml_service = MLService()
    model = await ml_service.get_model("AAPL", "1d")
    assert model is None


@pytest.mark.asyncio
async def test_predict_returns_hold_when_no_model(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACTS_DIR", str(tmp_path))
    ml_service = MLService()
    features = pd.DataFrame()
    pred = await ml_service.predict("AAPL", "1d", features)
    assert pred["action"] == "HOLD"
    assert pred["model_version"] == "none"


@pytest.mark.asyncio
async def test_train_model_for_symbol_skips_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACTS_DIR", str(tmp_path))
    
    model_dir = tmp_path / "AAPL" / "1d"
    model_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone, timedelta
    recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    (model_dir / "metadata.json").write_text(json.dumps({
        "trained_at": recent_date
    }))

    ml_service = MLService()
    res = await ml_service.train_model_for_symbol("AAPL", "1d", pd.DataFrame(), force_retrain=False)
    assert res["status"] == "skipped"
    assert "Trained 5d ago" in res["reason"]


@pytest.mark.asyncio
async def test_train_model_rejects_low_auc(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACTS_DIR", str(tmp_path))
    
    mock_model_class = MagicMock()
    mock_model_instance = MagicMock()
    mock_model_instance.walk_forward_evaluate.return_value = {"mean_auc": 0.50}
    mock_model_class.return_value = mock_model_instance
    
    monkeypatch.setattr("ml.models.xgboost_model.XGBoostSignalModel", mock_model_class)
    monkeypatch.setattr("backend.services.ml_service.build_feature_matrix", lambda df, drop_na: pd.DataFrame())

    ml_service = MLService()
    df = pd.DataFrame({"Close": [100.0, 101.0, 102.0]})
    res = await ml_service.train_model_for_symbol("AAPL", "1d", df, force_retrain=True)
    
    assert res["status"] == "rejected"
    assert "AUC 0.5000 < 0.52" in res["reason"]
    assert not mock_model_instance.save.called
