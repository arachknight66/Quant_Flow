import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score
from ml.models.xgboost_model import XGBoostSignalModel
from ml.backtesting.engine import WalkForwardSplitter
import joblib
from pathlib import Path
import json
from datetime import datetime

class EnsembleStackerModel:
    """
    Ensemble model that stacks multiple base models (XGBoost models with different hyperparameter sets)
    and trains a Logistic Regression meta-model on their walk-forward out-of-sample predictions.
    """
    def __init__(self, base_params_list=None, prediction_horizon=5, profit_threshold=0.01, version="v1.0"):
        self.prediction_horizon = prediction_horizon
        self.profit_threshold   = profit_threshold
        self.version            = version
        self.base_params_list = base_params_list or [
            {"max_depth": 3, "learning_rate": 0.03, "n_estimators": 100},
            {"max_depth": 5, "learning_rate": 0.05, "n_estimators": 150},
            {"max_depth": 6, "learning_rate": 0.08, "n_estimators": 120}
        ]
        self.base_models = []
        self.meta_model = None
        self.feature_names = None

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
            "obv_zscore", "golden_cross", "garch_", "regime_",
        ]
        selected = []
        for col in df.columns:
            for prefix in ml_feature_prefixes:
                if col.startswith(prefix) or col == prefix.rstrip("_"):
                    selected.append(col)
                    break
        return df[selected]

    def fit_and_stack(self, features: pd.DataFrame, close: pd.Series, n_splits: int = 5) -> dict:
        target = self._create_target(close)
        ml_features = self._select_ml_features(features)
        self.feature_names = list(ml_features.columns)
        mask = target.notna()
        X, y = ml_features[mask], target[mask]

        # Dynamically scale splitter parameters if dataset is small
        n = len(X)
        if n < 300:
            test_size = max(n // 10, 5)
            min_train = max(n // 3, 20)
            splitter = WalkForwardSplitter(n_splits=n_splits, test_size=test_size, gap=1, min_train_size=min_train)
        else:
            splitter = WalkForwardSplitter(n_splits=n_splits)
        oof_preds = np.zeros((len(X), len(self.base_params_list)))
        
        self.base_models = [
            XGBoostSignalModel(
                prediction_horizon=self.prediction_horizon,
                profit_threshold=self.profit_threshold,
                model_params=params
            )
            for params in self.base_params_list
        ]

        for train_idx, test_idx in splitter.split(X):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
            
            for m_idx, base_model in enumerate(self.base_models):
                class_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
                temp_model = base_model._build_model(class_weight)
                temp_model.fit(X_train, y_train)
                proba = temp_model.predict_proba(X_test)[:, 1]
                oof_preds[test_idx, m_idx] = proba

        test_indices = []
        for train_idx, test_idx in splitter.split(X):
            test_indices.extend(test_idx)
        test_indices = sorted(list(set(test_indices)))

        X_meta = oof_preds[test_indices]
        y_meta = y.iloc[test_indices].values

        self.meta_model = LogisticRegression(C=1.0, random_state=42)
        self.meta_model.fit(X_meta, y_meta)

        for base_model in self.base_models:
            base_model.train_final(features, close)

        meta_preds = self.meta_model.predict_proba(X_meta)[:, 1]
        auc = roc_auc_score(y_meta, meta_preds)

        return {
            "mean_auc": float(auc),
            "n_folds": n_splits,
            "base_models_count": len(self.base_models)
        }

    def predict(self, features: pd.DataFrame) -> dict:
        if self.meta_model is None:
            raise RuntimeError("Model not trained.")
        base_probs = []
        for base_model in self.base_models:
            res = base_model.predict(features)
            base_probs.append(res["prob_profit"])

        X_meta_latest = np.array(base_probs).reshape(1, -1)
        proba = self.meta_model.predict_proba(X_meta_latest)[0, 1]
        action = "BUY" if proba > 0.60 else "SELL" if proba < 0.40 else "HOLD"

        return {
            "action": action,
            "prob_profit": float(proba),
            "confidence": float(abs(proba - 0.5) * 2),
            "model_version": self.version,
            "base_probabilities": base_probs
        }

    def save(self, path: str):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.meta_model, path / "meta_model.joblib")
        for idx, base_model in enumerate(self.base_models):
            base_model.save(str(path / f"base_model_{idx}"))
        metadata = {
            "version": self.version,
            "prediction_horizon": self.prediction_horizon,
            "profit_threshold": self.profit_threshold,
            "feature_names": self.feature_names,
            "base_params_list": self.base_params_list,
            "trained_at": datetime.utcnow().isoformat(),
        }
        (path / "metadata.json").write_text(json.dumps(metadata, indent=2))

    @classmethod
    def load(cls, path: str) -> "EnsembleStackerModel":
        path = Path(path)
        metadata = json.loads((path / "metadata.json").read_text())
        instance = cls(base_params_list=metadata["base_params_list"],
                        prediction_horizon=metadata["prediction_horizon"],
                        profit_threshold=metadata["profit_threshold"],
                        version=metadata["version"])
        instance.meta_model = joblib.load(path / "meta_model.joblib")
        instance.feature_names = metadata["feature_names"]
        
        instance.base_models = []
        for idx in range(len(metadata["base_params_list"])):
            bm = XGBoostSignalModel.load(str(path / f"base_model_{idx}"))
            instance.base_models.append(bm)
        return instance
