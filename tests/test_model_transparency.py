import pytest
import uuid
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

from ml.models.xgboost_model import XGBoostSignalModel

class MockBaseClassifier:
    def __init__(self, n_features):
        self.feature_importances_ = [1.0 / n_features] * n_features

class MockCalibratedClassifier:
    def __init__(self, n_features):
        self.estimator = MockBaseClassifier(n_features)

class MockCalibratedClassifierCV:
    def __init__(self, n_features):
        self.calibrated_classifiers_ = [
            MockCalibratedClassifier(n_features),
            MockCalibratedClassifier(n_features)
        ]

@pytest.mark.asyncio
async def test_xgboost_model_save_includes_feature_importances(tmp_path):
    model = XGBoostSignalModel(version="v1.0.test")
    model.feature_names = ["feat1", "feat2"]
    
    # Mock fitted model
    model.model = MockCalibratedClassifierCV(2)
    
    save_dir = tmp_path / "model_test"
    
    # Mock joblib.dump to avoid real model saving
    with patch("joblib.dump") as mock_dump:
        model.save(str(save_dir))
        assert mock_dump.called

    meta_file = save_dir / "metadata.json"
    assert meta_file.exists()
    
    meta = json.loads(meta_file.read_text())
    assert "feature_importances" in meta
    assert meta["feature_importances"] == {"feat1": 0.5, "feat2": 0.5}


@pytest.mark.asyncio
async def test_get_model_info_returns_correct_metadata(app_client, monkeypatch, tmp_path):
    # Setup mock metadata
    meta = {
        "version": "test_v2",
        "prediction_horizon": 7,
        "profit_threshold": 0.02,
        "feature_names": ["feat1", "feat2"],
        "feature_importances": {"feat1": 0.3, "feat2": 0.7},
        "walk_forward_metrics": {
            "mean_auc": 0.65,
            "std_auc": 0.05,
            "mean_brier": 0.18,
            "fold_metrics": [{"auc": 0.6}, {"auc": 0.7}]
        },
        "trained_at": (datetime.utcnow() - timedelta(days=5)).isoformat()
    }
    
    # Patch MLService model path to point to a temp dir containing our metadata
    meta_dir = tmp_path / "AAPL_1d"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "metadata.json").write_text(json.dumps(meta))
    
    monkeypatch.setattr(
        "backend.services.ml_service.MLService._model_path",
        lambda self, sym, tf: meta_dir
    )

    resp = await app_client.get("/api/v1/analysis/model-info?symbol=AAPL&timeframe=1d")
    assert resp.status_code == 200
    data = resp.json()
    
    assert data["version"] == "test_v2"
    assert data["prediction_horizon"] == 7
    assert data["profit_threshold"] == 0.02
    assert data["feature_importances"] == {"feat1": 0.3, "feat2": 0.7}
    assert data["mean_auc"] == 0.65
    assert data["std_auc"] == 0.05
    assert data["n_folds"] == 2
    assert data["model_age_days"] == 5
    assert data["staleness_warning"] is False


@pytest.mark.asyncio
async def test_get_model_info_returns_404_when_missing(app_client, monkeypatch, tmp_path):
    # Setup non-existent model path
    monkeypatch.setattr(
        "backend.services.ml_service.MLService._model_path",
        lambda self, sym, tf: tmp_path / "nonexistent"
    )

    resp = await app_client.get("/api/v1/analysis/model-info?symbol=AAPL&timeframe=1d")
    assert resp.status_code == 404
    assert "Model metadata not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_model_info_computes_staleness_correctly(app_client, monkeypatch, tmp_path):
    # Metadata trained 35 days ago (should trigger staleness_warning=True)
    meta = {
        "version": "test_v2",
        "feature_names": ["feat1"],
        "trained_at": (datetime.utcnow() - timedelta(days=35)).isoformat()
    }
    
    meta_dir = tmp_path / "AAPL_1d_stale"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "metadata.json").write_text(json.dumps(meta))
    
    monkeypatch.setattr(
        "backend.services.ml_service.MLService._model_path",
        lambda self, sym, tf: meta_dir
    )

    resp = await app_client.get("/api/v1/analysis/model-info?symbol=AAPL&timeframe=1d")
    assert resp.status_code == 200
    data = resp.json()
    
    assert data["model_age_days"] == 35
    assert data["staleness_warning"] is True
