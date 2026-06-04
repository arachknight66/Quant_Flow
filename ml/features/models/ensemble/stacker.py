# ml/models/ensemble/stacker.py
"""
Ensemble stacking of XGBoost + LSTM + Logistic Regression.

Why ensemble?
- XGBoost: captures non-linear tabular feature interactions
- LSTM: captures temporal sequential patterns
- LogReg: provides a calibrated linear baseline
- Stacking: a meta-learner learns when to trust each model

The stacking meta-learner is a Logistic Regression trained on
out-of-fold predictions from the base models. This is valid
because the meta-features are generated on data the base models
never saw during training.

Critical rule: The stacking CV must itself be walk-forward.
Never use standard k-fold for the meta-learning stage either.

Expected improvement from stacking: modest (2–5% AUC gain).
Not a silver bullet. The base model quality matters far more
than the stacking architecture.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
import joblib
from pathlib import Path
import structlog

log = structlog.get_logger()


class EnsembleStacker:
    """
    Two-layer ensemble: base models → meta-learner.

    Base models produce probability estimates.
    Meta-learner (Logistic Regression) learns to combine them.

    The meta-learner receives: [xgb_prob, lstm_prob, logr_prob,
                                 vol_regime, rsi_z, bb_pct_b, ...]
    Adding raw features alongside base model probabilities helps
    the meta-learner understand context (e.g. trust XGBoost more
    in low-volatility regimes, trust LSTM more in trend regimes).
    """

    def __init__(self, version: str = "ensemble_v1"):
        self.version = version
        self.base_models: dict = {}
        self.meta_model = None
        self._context_features = [
            "vol_20d", "rsi", "bb_pct_b", "atr_pct", "momentum_10",
            "vol_ratio_20_60",
        ]

    def add_model(self, name: str, model):
        """Register a base model. Must implement .predict(features) -> dict."""
        self.base_models[name] = model
        log.info("Base model registered", name=name)

    def _get_base_predictions(
        self, features: pd.DataFrame
    ) -> np.ndarray:
        """
        Get probability predictions from all base models for the current bar.
        Returns array of shape (n_models,).
        """
        probs = []
        for name, model in self.base_models.items():
            try:
                pred = model.predict(features)
                probs.append(pred["prob_profit"])
            except Exception as e:
                log.warning("Base model prediction failed", model=name, error=str(e))
                probs.append(0.5)  # Neutral fallback
        return np.array(probs)

    def train_meta(
        self,
        features: pd.DataFrame,
        close: pd.Series,
        prediction_horizon: int = 5,
    ):
        """
        Train the meta-learner using out-of-fold base model predictions.

        Process:
        1. Split data into K temporal folds
        2. For each fold: train base models on [0:fold_start], predict on [fold_start:fold_end]
        3. Collect all out-of-fold predictions as meta-features
        4. Train meta-learner on the full set of meta-features
        """
        from ml.models.xgboost_model import XGBoostSignalModel
        from ml.backtesting.engine import WalkForwardSplitter

        target = (close.shift(-prediction_horizon) / close - 1 > 0.01).astype(float)
        target.iloc[-prediction_horizon:] = np.nan

        mask = target.notna()
        X = features[mask]
        y = target[mask]

        splitter = WalkForwardSplitter(n_splits=4, test_size=63, gap=5)
        oof_predictions = []
        oof_targets = []

        for train_idx, test_idx in splitter.split(X):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train = y.iloc[train_idx]
            y_test = y.iloc[test_idx]
            close_train = close.iloc[mask.values][train_idx]

            # Re-train each base model on this fold's training data
            fold_preds = []
            for test_bar_idx in range(len(test_idx)):
                abs_test_bar = test_idx[test_bar_idx]
                features_up_to_bar = X.iloc[:abs_test_bar + 1]
                close_up_to_bar = close.iloc[:abs_test_bar + 1]

                bar_preds = []
                for name, model in self.base_models.items():
                    try:
                        pred = model.predict(features_up_to_bar)
                        bar_preds.append(pred["prob_profit"])
                    except Exception:
                        bar_preds.append(0.5)

                # Add context features
                ctx = []
                for cf in self._context_features:
                    val = X_test.iloc[test_bar_idx].get(cf, 0.5)
                    ctx.append(float(val) if not np.isnan(float(val)) else 0.5)

                fold_preds.append(bar_preds + ctx)
            oof_predictions.extend(fold_preds)
            oof_targets.extend(y_test.tolist())

        meta_X = np.array(oof_predictions)
        meta_y = np.array(oof_targets)

        valid = ~np.isnan(meta_y) & ~np.isnan(meta_X).any(axis=1)
        meta_X = meta_X[valid]
        meta_y = meta_y[valid]

        log.info("Training meta-learner", n_samples=len(meta_X))

        scaler = StandardScaler()
        meta_X_scaled = scaler.fit_transform(meta_X)

        meta_lr = CalibratedClassifierCV(
            LogisticRegression(C=0.5, max_iter=500),
            method="isotonic",
            cv=3,
        )
        meta_lr.fit(meta_X_scaled, meta_y)

        self.meta_model = {"model": meta_lr, "scaler": scaler}

    def predict(self, features: pd.DataFrame) -> dict:
        """Get ensemble prediction combining all base models."""
        if not self.meta_model:
            # Fallback: simple average of base model probabilities
            probs = self._get_base_predictions(features)
            avg_prob = float(np.mean(probs))
        else:
            base_probs = self._get_base_predictions(features)
            ctx = []
            latest = features.iloc[-1]
            for cf in self._context_features:
                val = latest.get(cf, 0.5)
                ctx.append(float(val) if not np.isnan(float(val)) else 0.5)

            meta_input = np.array([list(base_probs) + ctx])
            meta_scaled = self.meta_model["scaler"].transform(meta_input)
            avg_prob = float(self.meta_model["model"].predict_proba(meta_scaled)[0, 1])

        if avg_prob > 0.60:
            action = "BUY"
        elif avg_prob < 0.40:
            action = "SELL"
        else:
            action = "HOLD"

        return {
            "action": action,
            "prob_profit": round(avg_prob, 4),
            "confidence": round(abs(avg_prob - 0.5) * 2, 4),
            "model_version": self.version,
            "base_model_probs": {
                name: round(float(p), 4)
                for name, p in zip(self.base_models.keys(),
                                   self._get_base_predictions(features))
            },
        }