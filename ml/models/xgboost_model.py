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
    def __init__(self, prediction_horizon=5, profit_threshold=0.01, version="v1.0", model_params=None, prune_correlation=False, prune_importance_pct=0.0):
        self.prediction_horizon = prediction_horizon
        self.profit_threshold   = profit_threshold
        self.version            = version
        self.model_params       = model_params or {}
        self.model              = None
        self.feature_names      = None
        self.walk_forward_metrics = []
        self.prune_correlation  = prune_correlation
        self.prune_importance_pct = prune_importance_pct

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
            "symbol_", "sector_", "market_", "cyclical_", "divergence_",
            "dist_52w", "acc_dist", "earnings_"
        ]
        selected = []
        for col in df.columns:
            for prefix in ml_feature_prefixes:
                if col.startswith(prefix) or col == prefix.rstrip("_"):
                    selected.append(col)
                    break
        return df[selected]

    def _get_pruned_features(self, X: pd.DataFrame, y: pd.Series) -> list[str]:
        features_to_keep = list(X.columns)
        
        # 1. Correlation pruning (|r| > 0.85)
        if self.prune_correlation and len(features_to_keep) > 1:
            # We exclude dummy categorical columns (symbol_*, sector_*) from correlation pruning
            # because we want to preserve symbol indicator identities even if they have high collinearity.
            non_cat_feats = [c for c in features_to_keep if not (c.startswith("symbol_") or c.startswith("sector_"))]
            if len(non_cat_feats) > 1:
                corr = X[non_cat_feats].corr().abs()
                upper_tri = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
                to_drop = [column for column in upper_tri.columns if any(upper_tri[column] > 0.85)]
                features_to_keep = [c for c in features_to_keep if c not in to_drop]
            
        # 2. Importance pruning (remove bottom 30%)
        if self.prune_importance_pct > 0.0 and len(features_to_keep) > 5:
            import xgboost as xgb
            quick_clf = xgb.XGBClassifier(
                n_estimators=50, max_depth=3, learning_rate=0.1,
                eval_metric="logloss", random_state=42, n_jobs=-1
            )
            quick_clf.fit(X[features_to_keep], y)
            imp = pd.Series(quick_clf.feature_importances_, index=features_to_keep).sort_values(ascending=False)
            
            n_to_keep = int(len(features_to_keep) * (1 - self.prune_importance_pct))
            features_to_keep = list(imp.head(n_to_keep).index)
            
        return features_to_keep

    def walk_forward_evaluate(self, features: pd.DataFrame, close: pd.Series,
                               n_splits: int = 5) -> dict:
        target = self._create_target(close)
        ml_features = self._select_ml_features(features)
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
        fold_metrics = []
        for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(X)):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
            
            # Prune features dynamically on the training split of the fold
            kept_features = self._get_pruned_features(X_train, y_train)
            X_train_pruned = X_train[kept_features]
            X_test_pruned = X_test[kept_features]
            
            class_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
            model = self._build_model(class_weight)
            model.fit(X_train_pruned, y_train)
            proba = model.predict_proba(X_test_pruned)[:, 1]
            
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
        params = {
            "n_estimators": 200,
            "max_depth": 4,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 10,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "scale_pos_weight": scale_pos_weight,
            "eval_metric": "logloss",
            "random_state": 42,
            "n_jobs": -1
        }
        params.update(self.model_params)
        base = xgb.XGBClassifier(**params)
        return CalibratedClassifierCV(base, method="sigmoid", cv=3)

    def train_final(self, features: pd.DataFrame, close: pd.Series):
        target = self._create_target(close)
        ml_features = self._select_ml_features(features)
        mask = target.notna()
        X, y = ml_features[mask], target[mask]
        
        # Apply pruning on the final dataset
        self.feature_names = self._get_pruned_features(X, y)
        X_pruned = X[self.feature_names]
        
        class_weight = (y == 0).sum() / max((y == 1).sum(), 1)
        self.model = self._build_model(class_weight)
        self.model.fit(X_pruned, y)
        log.info("Final model trained", version=self.version, n_samples=len(X), n_features=len(self.feature_names))

    def predict(self, features: pd.DataFrame) -> dict:
        if self.model is None:
            raise RuntimeError("Model not trained. Call train_final() first.")
        ml_features = self._select_ml_features(features)
        X_latest = ml_features.iloc[[-1]].reindex(columns=self.feature_names, fill_value=0.0)
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
        
        feature_importances = None
        if self.model and hasattr(self.model, "calibrated_classifiers_") and self.model.calibrated_classifiers_:
            try:
                importances = []
                for clf in self.model.calibrated_classifiers_:
                    est = getattr(clf, "estimator", getattr(clf, "base_estimator", None))
                    if est and hasattr(est, "feature_importances_"):
                        importances.append(est.feature_importances_)
                if importances:
                    mean_importances = np.mean(importances, axis=0).tolist()
                    feature_importances = dict(zip(self.feature_names, mean_importances))
            except Exception as e:
                log.warning("Could not extract feature importances from calibrated classifiers", error=str(e))

        metadata = {
            "version": self.version,
            "prediction_horizon": self.prediction_horizon,
            "profit_threshold": self.profit_threshold,
            "feature_names": self.feature_names,
            "feature_importances": feature_importances,
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
