# backend/services/ml_service.py
"""
ML service — model registry and inference orchestration.

Responsibilities:
  1. Load trained models from disk (lazy, on first request)
  2. Version management — track which model version applies to which symbol
  3. Async inference (runs model in thread pool, non-blocking)
  4. Feature computation pipeline (fetch → features → predict)
  5. Caching predictions for the same symbol/timeframe (30s TTL)
  6. Fallback handling when no model is available

Model versioning:
  Each (symbol, timeframe) pair has its own model. A general market
  model trained on multiple assets is also available as fallback.
  Models are stored in /ml/artifacts/{symbol}/{timeframe}/
  with metadata.json tracking walk-forward AUC and train date.
"""
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import structlog

from backend.core.config import settings
from ml.features.technical_indicators import build_feature_matrix, IndicatorConfig
import pandas as pd

log = structlog.get_logger()


class MLService:
    """Singleton service for ML inference across all endpoints."""

    def __init__(self):
        self._model_cache: dict = {}      # {key: model}
        self._metadata_cache: dict = {}   # {key: metadata dict}
        self._prediction_cache: dict = {} # {key: (timestamp, prediction)}
        self._prediction_ttl = 30         # seconds

    def _model_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol.upper()}_{timeframe}"

    def _model_path(self, symbol: str, timeframe: str) -> Path:
        return Path(settings.MODEL_ARTIFACTS_DIR) / symbol.upper() / timeframe

    async def get_model(self, symbol: str, timeframe: str):
        """
        Load model from disk (with in-memory cache).
        Returns None if no model exists for this symbol/timeframe.
        Falls back to general model if available.
        """
        key = self._model_key(symbol, timeframe)

        if key in self._model_cache:
            return self._model_cache[key]

        model_path = self._model_path(symbol, timeframe)
        fallback_path = Path(settings.MODEL_ARTIFACTS_DIR) / "GENERAL" / timeframe

        for path in [model_path, fallback_path]:
            if (path / "metadata.json").exists():
                try:
                    model = await self._load_model_async(path)
                    self._model_cache[key] = model

                    with open(path / "metadata.json") as f:
                        self._metadata_cache[key] = json.load(f)

                    log.info(
                        "Model loaded",
                        symbol=symbol,
                        timeframe=timeframe,
                        path=str(path),
                        version=self._metadata_cache[key].get("version"),
                    )
                    return model
                except Exception as e:
                    log.error("Failed to load model", path=str(path), error=str(e))

        return None

    async def _load_model_async(self, path: Path):
        """Load model in thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()

        def _load():
            from ml.models.xgboost_model import XGBoostSignalModel
            return XGBoostSignalModel.load(str(path))

        return await loop.run_in_executor(None, _load)

    async def predict(
        self,
        symbol: str,
        timeframe: str,
        features: pd.DataFrame,
    ) -> dict:
        """
        Run inference for a symbol/timeframe.

        Checks prediction cache first (30s TTL) to avoid running
        the model on every API request for popular symbols.
        """
        key = self._model_key(symbol, timeframe)
        now = datetime.now(timezone.utc).timestamp()

        # Check prediction cache
        if key in self._prediction_cache:
            cached_time, cached_pred = self._prediction_cache[key]
            if now - cached_time < self._prediction_ttl:
                return cached_pred

        model = await self.get_model(symbol, timeframe)
        if model is None:
            return {
                "action": "HOLD",
                "prob_profit": 0.50,
                "confidence": 0.0,
                "model_version": "none",
                "error": "no_model_available",
            }

        # Run inference in thread pool
        loop = asyncio.get_event_loop()
        try:
            prediction = await loop.run_in_executor(
                None, model.predict, features
            )
        except Exception as e:
            log.error("Model inference failed", symbol=symbol, error=str(e))
            return {
                "action": "HOLD",
                "prob_profit": 0.50,
                "confidence": 0.0,
                "model_version": "error",
                "error": str(e),
            }

        # Cache the prediction
        self._prediction_cache[key] = (now, prediction)
        return prediction

    async def get_model_auc(self, symbol: str, timeframe: str) -> Optional[float]:
        """Return the walk-forward AUC for the current model, if available."""
        key = self._model_key(symbol, timeframe)

        if key not in self._metadata_cache:
            await self.get_model(symbol, timeframe)

        metadata = self._metadata_cache.get(key, {})
        wf_metrics = metadata.get("walk_forward_metrics", [])
        if wf_metrics:
            return round(
                sum(m.get("roc_auc", 0) for m in wf_metrics) / len(wf_metrics), 4
            )
        return None

    async def train_model_for_symbol(
        self,
        symbol: str,
        timeframe: str,
        ohlcv_df: pd.DataFrame,
        force_retrain: bool = False,
    ) -> dict:
        """
        Train or retrain a model for a specific symbol.
        Called by the /analysis/train endpoint or a scheduled job.

        Returns walk-forward metrics. Does NOT deploy automatically —
        a human review step should happen before deploying to production.
        """
        from ml.models.xgboost_model import XGBoostSignalModel

        key = self._model_key(symbol, timeframe)
        model_path = self._model_path(symbol, timeframe)

        if not force_retrain and (model_path / "metadata.json").exists():
            with open(model_path / "metadata.json") as f:
                metadata = json.load(f)
            trained_at = datetime.fromisoformat(metadata.get("trained_at", "2000-01-01"))
            age_days = (datetime.now(timezone.utc) - trained_at.replace(tzinfo=timezone.utc)).days
            if age_days < 30:
                return {"status": "skipped", "reason": f"Model trained {age_days} days ago, < 30 day threshold"}

        log.info("Training model", symbol=symbol, timeframe=timeframe, bars=len(ohlcv_df))

        loop = asyncio.get_event_loop()

        def _train():
            features = build_feature_matrix(ohlcv_df, drop_na=False)
            close = ohlcv_df["Close"]

            model = XGBoostSignalModel(version=f"xgb_{symbol}_{timeframe}_v1")

            # Walk-forward evaluation
            wf_metrics = model.walk_forward_evaluate(features, close)

            if wf_metrics["mean_auc"] < 0.52:
                return {
                    "status": "rejected",
                    "reason": f"Walk-forward AUC {wf_metrics['mean_auc']:.4f} < 0.52 threshold",
                    "metrics": wf_metrics,
                }

            # Train final model
            model.train_final(features, close)
            model.save(str(model_path))

            return {
                "status": "trained",
                "symbol": symbol,
                "timeframe": timeframe,
                "walk_forward_metrics": wf_metrics,
                "model_path": str(model_path),
            }

        result = await loop.run_in_executor(None, _train)

        # Invalidate cached model so next request loads the new one
        self._model_cache.pop(key, None)
        self._metadata_cache.pop(key, None)
        self._prediction_cache.pop(key, None)

        return result