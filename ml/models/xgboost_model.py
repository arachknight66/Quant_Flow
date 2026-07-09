import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, roc_auc_score, log_loss
import joblib
from pathlib import Path
from datetime import datetime
import json
import structlog
from ml.backtesting.engine import WalkForwardSplitter

log = structlog.get_logger()

class XGBoostSignalModel:
    def __init__(self, prediction_horizon=5, profit_threshold=0.01, version="v1.0"):
        self.prediction_horizon = prediction_horizon
        self.profit_threshold   = profit_threshold
        self.version            = version
        self.model              = None
        self.feature_names      = None
        self.walk_forward_metrics = []

    def _create_target(self, close: pd.Series) -> pd.Series:
        future_return = close.shift(-self.prediction_horizon) / close - 1
        target = (future_return > self.profit_threshold).astype(int)
        target.iloc[-self.prediction_horizon:] = np.nan
        return target

    def _select_ml_features(self, df: pd.DataFrame) -> pd.DataFrame:
        ml_feature_prefixes = [
            "log_return_", "rsi", "macd_hist", "bb_pct_b", "bb_width",
            "atr_pct", "price_ema_", "price_sma_", "price_vwap_deviation",
            "vol_", "momentum_", "roc", "volume_ratio", "volume_zscore",
            "obv_zscore", "golden_cross",
        ]
        selected = []
        for col in df.columns:
            for prefix in ml_feature_prefixes:
                if col.startswith(prefix) or col == prefix.rstrip("_"):
                    selected.append(col)
                    break
        return df[selected]

    def walk_forward_evaluate(self, features: pd.DataFrame, close: pd.Series,
                               n_splits: int = 5) -> dict:
        target = self._create_target(close)
        ml_features = self._select_ml_features(features)
        mask = target.notna()
        X, y = ml_features[mask], target[mask]
        splitter = WalkForwardSplitter(n_splits=n_splits)
        fold_metrics = []
        for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(X)):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
            class_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
            model = self._build_model(class_weight)
            model.fit(X_train, y_train)
            proba = model.predict_proba(X_test)[:, 1]
            fold_metrics.append({
                "fold": fold_idx, "train_size": len(X_train), "test_size": len(X_test),
                "brier_score": float(brier_score_loss(y_test, proba)),
                "roc_auc":     float(roc_auc_score(y_test, proba)),
                "log_loss":    float(log_loss(y_test, proba)),
                "positive_rate": float(y_test.mean()),
            })
            log.info("Walk-forward fold complete", fold=fold_idx,
                     auc=f"{fold_metrics[-1]['roc_auc']:.4f}")
        self.walk_forward_metrics = fold_metrics
        avg_metrics = {
            "mean_brier":    float(np.mean([m["brier_score"] for m in fold_metrics])),
            "mean_auc":      float(np.mean([m["roc_auc"] for m in fold_metrics])),
            "std_auc":       float(np.std([m["roc_auc"] for m in fold_metrics])),
            "mean_log_loss": float(np.mean([m["log_loss"] for m in fold_metrics])),
            "n_folds": len(fold_metrics), "folds": fold_metrics,
        }
        if avg_metrics["mean_auc"] < 0.52:
            log.warning("Model AUC near random — do not deploy.", auc=avg_metrics["mean_auc"])
        return avg_metrics

    def _build_model(self, scale_pos_weight=1.0):
        base = xgb.XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
            reg_alpha=0.1, reg_lambda=1.0, scale_pos_weight=scale_pos_weight,
            eval_metric="logloss", random_state=42, n_jobs=-1,
        )
        return CalibratedClassifierCV(base, method="sigmoid", cv=3)

    def train_final(self, features: pd.DataFrame, close: pd.Series):
        target = self._create_target(close)
        ml_features = self._select_ml_features(features)
        self.feature_names = list(ml_features.columns)
        mask = target.notna()
        X, y = ml_features[mask], target[mask]
        class_weight = (y == 0).sum() / max((y == 1).sum(), 1)
        self.model = self._build_model(class_weight)
        self.model.fit(X, y)
        log.info("Final model trained", version=self.version, n_samples=len(X))

    def predict(self, features: pd.DataFrame) -> dict:
        if self.model is None:
            raise RuntimeError("Model not trained. Call train_final() first.")
        ml_features = self._select_ml_features(features)
        X_latest = ml_features.iloc[[-1]][self.feature_names]
        if X_latest.isnull().any().any():
            raise ValueError("Latest features contain NaN — insufficient data")
        proba = self.model.predict_proba(X_latest)[0, 1]
        action = "BUY" if proba > 0.60 else "SELL" if proba < 0.40 else "HOLD"
        return {
            "action": action,
            "prob_profit": float(proba),
            "confidence": float(abs(proba - 0.5) * 2),
            "model_version": self.version,
            "feature_snapshot": X_latest.iloc[0].to_dict(),
        }

    def save(self, path: str):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, path / "model.joblib")
        metadata = {
            "version": self.version,
            "prediction_horizon": self.prediction_horizon,
            "profit_threshold": self.profit_threshold,
            "feature_names": self.feature_names,
            "walk_forward_metrics": self.walk_forward_metrics,
            "trained_at": datetime.utcnow().isoformat(),
        }
        (path / "metadata.json").write_text(json.dumps(metadata, indent=2))

    @classmethod
    def load(cls, path: str) -> "XGBoostSignalModel":
        path = Path(path)
        metadata = json.loads((path / "metadata.json").read_text())
        instance = cls(prediction_horizon=metadata["prediction_horizon"],
                       profit_threshold=metadata["profit_threshold"],
                       version=metadata["version"])
        instance.model = joblib.load(path / "model.joblib")
        instance.feature_names = metadata["feature_names"]
        instance.walk_forward_metrics = metadata.get("walk_forward_metrics", [])
        return instance
