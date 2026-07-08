import asyncio, json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import structlog
from backend.core.config import settings
from ml.features.technical_indicators import build_feature_matrix
import pandas as pd

log = structlog.get_logger()

class MLService:
    def __init__(self):
        self._model_cache: dict = {}
        self._metadata_cache: dict = {}
        self._prediction_cache: dict = {}
        self._prediction_ttl = 30

    def _model_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol.upper()}_{timeframe}"

    def _model_path(self, symbol: str, timeframe: str) -> Path:
        return Path(settings.MODEL_ARTIFACTS_DIR) / symbol.upper() / timeframe

    async def get_model(self, symbol: str, timeframe: str):
        key = self._model_key(symbol, timeframe)
        if key in self._model_cache:
            return self._model_cache[key]
        model_path   = self._model_path(symbol, timeframe)
        fallback_path = Path(settings.MODEL_ARTIFACTS_DIR) / "GENERAL" / timeframe
        for path in [model_path, fallback_path]:
            if (path / "metadata.json").exists():
                try:
                    model = await asyncio.get_event_loop().run_in_executor(
                        None, self._load_sync, path)
                    self._model_cache[key] = model
                    self._metadata_cache[key] = json.loads((path / "metadata.json").read_text())
                    return model
                except Exception as e:
                    log.error("Failed to load model", path=str(path), error=str(e))
        return None

    def _load_sync(self, path: Path):
        from ml.models.xgboost_model import XGBoostSignalModel
        return XGBoostSignalModel.load(str(path))

    async def predict(self, symbol: str, timeframe: str, features: pd.DataFrame) -> dict:
        key = self._model_key(symbol, timeframe)
        now = datetime.now(timezone.utc).timestamp()
        if key in self._prediction_cache:
            cached_time, cached_pred = self._prediction_cache[key]
            if now - cached_time < self._prediction_ttl:
                return cached_pred
        model = await self.get_model(symbol, timeframe)
        if model is None:
            return {"action": "HOLD", "prob_profit": 0.50, "confidence": 0.0,
                    "model_version": "none", "error": "no_model_available"}
        try:
            prediction = await asyncio.get_event_loop().run_in_executor(
                None, model.predict, features)
        except Exception as e:
            log.error("Model inference failed", symbol=symbol, error=str(e))
            return {"action": "HOLD", "prob_profit": 0.50, "confidence": 0.0,
                    "model_version": "error", "error": str(e)}
        self._prediction_cache[key] = (now, prediction)
        return prediction

    async def get_model_auc(self, symbol: str, timeframe: str) -> Optional[float]:
        key = self._model_key(symbol, timeframe)
        if key not in self._metadata_cache:
            await self.get_model(symbol, timeframe)
        metadata = self._metadata_cache.get(key, {})
        wf = metadata.get("walk_forward_metrics", [])
        return round(sum(m.get("roc_auc", 0) for m in wf) / len(wf), 4) if wf else None

    async def train_model_for_symbol(self, symbol: str, timeframe: str,
                                      ohlcv_df: pd.DataFrame, force_retrain=False) -> dict:
        from ml.models.xgboost_model import XGBoostSignalModel
        key = self._model_key(symbol, timeframe)
        model_path = self._model_path(symbol, timeframe)
        if not force_retrain and (model_path / "metadata.json").exists():
            metadata = json.loads((model_path / "metadata.json").read_text())
            trained_at = datetime.fromisoformat(metadata.get("trained_at", "2000-01-01"))
            age_days = (datetime.now(timezone.utc) - trained_at.replace(tzinfo=timezone.utc)).days
            if age_days < 30:
                return {"status": "skipped", "reason": f"Trained {age_days}d ago"}
        def _train():
            features = build_feature_matrix(ohlcv_df, drop_na=False)
            close = ohlcv_df["Close"]
            model = XGBoostSignalModel(version=f"xgb_{symbol}_{timeframe}_v1")
            wf = model.walk_forward_evaluate(features, close)
            if wf["mean_auc"] < 0.52:
                return {"status": "rejected",
                        "reason": f"AUC {wf['mean_auc']:.4f} < 0.52", "metrics": wf}
            model.train_final(features, close)
            model.save(str(model_path))
            return {"status": "trained", "symbol": symbol, "timeframe": timeframe,
                    "walk_forward_metrics": wf}
        result = await asyncio.get_event_loop().run_in_executor(None, _train)
        for cache in [self._model_cache, self._metadata_cache, self._prediction_cache]:
            cache.pop(key, None)
        return result
