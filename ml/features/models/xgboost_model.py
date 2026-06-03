# ml/models/xgboost_model.py
"""
XGBoost binary classifier for directional prediction.

TARGET VARIABLE:
    y = 1 if forward_return(t, horizon) > threshold else 0

    We predict whether the next N-day return will be positive,
    NOT the exact return magnitude. Classification is more robust
    than regression for noisy financial data.

WALK-FORWARD VALIDATION:
    MANDATORY for time-series financial data.
    Standard k-fold cross-validation causes SEVERE lookahead bias
    because it trains on future data to predict the past.

    Walk-forward splits time chronologically:
    Train: [t0, t1]  Test: [t1+gap, t2]
    Train: [t0, t2]  Test: [t2+gap, t3]
    ...
    The gap prevents leakage around the train/test boundary.
"""
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss, roc_auc_score, log_loss
from sklearn.pipeline import Pipeline
import optuna
import joblib
from pathlib import Path
from datetime import datetime
import json
import structlog

log = structlog.get_logger()


class WalkForwardSplitter:
    """
    Time-series cross-validation that respects temporal ordering.

    Parameters:
        n_splits: Number of train/test folds
        test_size: Number of samples in each test set
        gap: Samples to skip between train and test (prevents leakage)
        min_train_size: Minimum samples needed for first training fold
    """

    def __init__(
        self,
        n_splits: int = 5,
        test_size: int = 63,       # ~3 months of trading days
        gap: int = 5,              # 1 week gap to prevent leakage
        min_train_size: int = 252, # 1 year minimum training data
    ):
        self.n_splits = n_splits
        self.test_size = test_size
        self.gap = gap
        self.min_train_size = min_train_size

    def split(self, X: pd.DataFrame):
        """
        Yields (train_indices, test_indices) tuples.

        The key invariant: ALL training indices < ALL test indices.
        No future data ever appears in training.
        """
        n = len(X)
        splits = []

        for i in range(self.n_splits):
            # Test window: work backwards from end of data
            test_end = n - i * self.test_size
            test_start = test_end - self.test_size
            train_end = test_start - self.gap

            if train_end < self.min_train_size:
                log.warning(f"Skipping fold {i}: insufficient training data")
                continue

            train_indices = np.arange(0, train_end)
            test_indices = np.arange(test_start, test_end)
            splits.append((train_indices, test_indices))

        return reversed(splits)  # Chronological order


class XGBoostSignalModel:
    """
    Production XGBoost model for BUY/HOLD/SELL signal generation.

    Architecture decisions:
    - XGBoost over Random Forest: better handles financial data characteristics,
      more interpretable via SHAP, faster inference
    - Calibrated probabilities: raw XGBoost probabilities are not calibrated
      (they don't represent true event frequencies). Platt scaling corrects this.
    - Feature scaling: XGBoost is tree-based (scale-invariant), but we scale
      anyway for potential future model blending
    - Optuna tuning: Bayesian hyperparameter search is more efficient than
      grid search for the XGBoost parameter space

    Known limitations:
    - Assumes stationarity of feature-target relationship (likely violated!)
    - Ignores market regime changes
    - Feature importance can shift dramatically over time
    - Calibration degrades if market structure changes post-training
    """

    def __init__(
        self,
        prediction_horizon: int = 5,  # Predict 5-day forward return
        profit_threshold: float = 0.01,  # 1% return = "profitable"
        version: str = "v1.0",
    ):
        self.prediction_horizon = prediction_horizon
        self.profit_threshold = profit_threshold
        self.version = version
        self.model = None
        self.feature_names = None
        self.walk_forward_metrics = []

    def _create_target(self, close: pd.Series) -> pd.Series:
        """
        Binary target: will the next N-day return exceed threshold?

        CRITICAL: This is future information. It must NEVER be included
        in the feature matrix. Always create target separately and align
        carefully.
        """
        future_return = close.shift(-self.prediction_horizon) / close - 1
        target = (future_return > self.profit_threshold).astype(int)
        # Remove last N rows (no future data available)
        target.iloc[-self.prediction_horizon:] = np.nan
        return target

    def _select_ml_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Select features appropriate for ML input.

        Exclude:
        - Raw OHLCV (non-stationary)
        - EMA/SMA levels (non-stationary)
        - Targets

        Include:
        - Returns (stationary)
        - Normalised ratios (stationary-ish)
        - Indicator values (RSI, normalised BB, etc.)
        - Volatility measures
        """
        # Features that are approximately stationary and scale-independent
        ml_feature_prefixes = [
            "log_return_",
            "rsi",
            "macd_hist",
            "bb_pct_b", "bb_width",
            "atr_pct",
            "price_ema_",
            "price_sma_",
            "price_vwap_deviation",
            "vol_",
            "momentum_",
            "roc",
            "volume_ratio",
            "volume_zscore",
            "obv_zscore",
            "golden_cross",
        ]

        selected = []
        for col in df.columns:
            for prefix in ml_feature_prefixes:
                if col.startswith(prefix) or col == prefix.rstrip("_"):
                    selected.append(col)
                    break

        return df[selected]

    def walk_forward_evaluate(
        self,
        features: pd.DataFrame,
        close: pd.Series,
        n_splits: int = 5,
    ) -> dict:
        """
        Run walk-forward validation and return aggregated metrics.

        Returns calibration-quality metrics across all folds.
        Brier score is the primary metric: it measures probability calibration.
        AUC measures discrimination. Both matter.
        """
        target = self._create_target(close)
        ml_features = self._select_ml_features(features)

        # Align: drop rows where target is NaN
        mask = target.notna()
        X = ml_features[mask]
        y = target[mask]

        splitter = WalkForwardSplitter(n_splits=n_splits)
        fold_metrics = []

        for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(X)):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

            # Handle class imbalance — financial data is often ~50/50 but
            # in bear markets might be 30/70
            class_weight = (y_train == 0).sum() / (y_train == 1).sum()

            model = self._build_model(scale_pos_weight=class_weight)
            model.fit(X_train, y_train)

            proba = model.predict_proba(X_test)[:, 1]

            metrics = {
                "fold": fold_idx,
                "train_size": len(X_train),
                "test_size": len(X_test),
                "brier_score": float(brier_score_loss(y_test, proba)),
                "roc_auc": float(roc_auc_score(y_test, proba)),
                "log_loss": float(log_loss(y_test, proba)),
                "positive_rate": float(y_test.mean()),
            }
            fold_metrics.append(metrics)

            log.info(
                "Walk-forward fold complete",
                fold=fold_idx,
                brier=f"{metrics['brier_score']:.4f}",
                auc=f"{metrics['roc_auc']:.4f}",
            )

        self.walk_forward_metrics = fold_metrics

        # Aggregate
        avg_metrics = {
            "mean_brier": np.mean([m["brier_score"] for m in fold_metrics]),
            "mean_auc": np.mean([m["roc_auc"] for m in fold_metrics]),
            "std_auc": np.std([m["roc_auc"] for m in fold_metrics]),
            "mean_log_loss": np.mean([m["log_loss"] for m in fold_metrics]),
            "n_folds": len(fold_metrics),
            "folds": fold_metrics,
        }

        # Interpret results honestly
        if avg_metrics["mean_auc"] < 0.52:
            log.warning(
                "Model AUC near random",
                auc=avg_metrics["mean_auc"],
                message="This model has no detectable edge. Do not deploy."
            )
        elif avg_metrics["mean_auc"] < 0.55:
            log.warning(
                "Model AUC marginal",
                auc=avg_metrics["mean_auc"],
                message="Marginal edge. Very sensitive to transaction costs."
            )

        return avg_metrics

    def _build_model(self, scale_pos_weight: float = 1.0):
        """
        Build XGBoost classifier with calibration wrapper.

        Calibration with CalibratedClassifierCV:
        - method='isotonic' is more flexible but needs more data (~500+ samples)
        - method='sigmoid' (Platt scaling) works with less data
        - cv='prefit' allows us to calibrate on a held-out set
        """
        xgb_params = {
            "n_estimators": 200,
            "max_depth": 4,          # Shallow trees prevent overfitting
            "learning_rate": 0.05,
            "subsample": 0.8,        # Row sampling
            "colsample_bytree": 0.8, # Feature sampling
            "min_child_weight": 10,  # Prevent splits on few samples
            "reg_alpha": 0.1,        # L1 regularisation
            "reg_lambda": 1.0,       # L2 regularisation
            "scale_pos_weight": scale_pos_weight,
            "eval_metric": "logloss",
            "use_label_encoder": False,
            "random_state": 42,
            "n_jobs": -1,
        }

        base_model = xgb.XGBClassifier(**xgb_params)

        # Wrap with calibration
        # cv=5 means calibration itself is cross-validated
        calibrated = CalibratedClassifierCV(
            base_model,
            method="sigmoid",
            cv=3,
        )
        return calibrated

    def train_final(
        self,
        features: pd.DataFrame,
        close: pd.Series,
    ):
        """
        Train on full dataset after walk-forward validation confirms edge.
        This is the model used for live inference.

        IMPORTANT: Only call this after walk_forward_evaluate confirms
        AUC > 0.52 and Brier score better than baseline.
        """
        target = self._create_target(close)
        ml_features = self._select_ml_features(features)
        self.feature_names = list(ml_features.columns)

        mask = target.notna()
        X = ml_features[mask]
        y = target[mask]

        class_weight = (y == 0).sum() / (y == 1).sum()
        self.model = self._build_model(class_weight)
        self.model.fit(X, y)

        log.info(
            "Final model trained",
            version=self.version,
            n_samples=len(X),
            n_features=len(self.feature_names),
        )

    def predict(
        self,
        features: pd.DataFrame,
    ) -> dict:
        """
        Generate signal with probability and confidence metadata.

        Returns a dict suitable for the Signal schema.
        """
        if self.model is None:
            raise RuntimeError("Model not trained. Call train_final() first.")

        ml_features = self._select_ml_features(features)

        # Use only the last row for inference (most recent state)
        X_latest = ml_features.iloc[[-1]][self.feature_names]

        if X_latest.isnull().any().any():
            raise ValueError("Latest features contain NaN — insufficient data")

        proba = self.model.predict_proba(X_latest)[0, 1]

        # Map probability to signal
        # Thresholds should be calibrated from backtest performance
        # Don't use fixed thresholds — they may be poorly calibrated
        if proba > 0.60:
            action = "BUY"
        elif proba < 0.40:
            action = "SELL"
        else:
            action = "HOLD"

        return {
            "action": action,
            "prob_profit": float(proba),
            "confidence": float(abs(proba - 0.5) * 2),  # 0 = neutral, 1 = max confidence
            "model_version": self.version,
            "feature_snapshot": X_latest.iloc[0].to_dict(),
        }

    def save(self, path: str):
        """Persist model and metadata for reproducibility."""
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
        with open(path / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "XGBoostSignalModel":
        path = Path(path)
        with open(path / "metadata.json") as f:
            metadata = json.load(f)

        instance = cls(
            prediction_horizon=metadata["prediction_horizon"],
            profit_threshold=metadata["profit_threshold"],
            version=metadata["version"],
        )
        instance.model = joblib.load(path / "model.joblib")
        instance.feature_names = metadata["feature_names"]
        instance.walk_forward_metrics = metadata.get("walk_forward_metrics", [])
        return instance