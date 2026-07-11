# backend/monitoring/model_monitor.py
"""
Production model monitoring — detecting when models degrade.

Models degrade for two reasons:
1. Data drift: input feature distribution changes (volatility regime shift)
2. Concept drift: feature→target relationship breaks (RSI stops working)

We detect both via KS test + PSI on features, plus accuracy drift
on labelled predictions. Alerts are fired to logs/notifications.
We do NOT automatically retrain — human review is required.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
from scipy import stats
import structlog

log = structlog.get_logger()


@dataclass
class DriftAlert:
    feature_name: str
    drift_type: str        # "feature_drift" | "psi_drift" | "accuracy_drift" | "prediction_drift"
    statistic: float
    p_value: float
    severity: str          # "warning" | "critical"
    message: str


class ModelMonitor:
    """
    Tracks feature distributions, prediction distributions, and
    realised accuracy for a deployed model.

    Usage:
        monitor = ModelMonitor()
        monitor.set_reference_distribution(training_features, reference_accuracy=0.58)

        # After each batch of live predictions:
        alerts = monitor.check_drift(live_features_df)
        for alert in alerts:
            log.warning("Drift detected", **vars(alert))
    """

    def __init__(
        self,
        ks_alpha: float = 0.01,
        psi_warning: float = 0.10,
        psi_critical: float = 0.25,
        accuracy_window: int = 60,
        min_accuracy_drop: float = 0.05,
    ):
        self.ks_alpha          = ks_alpha
        self.psi_warning       = psi_warning
        self.psi_critical      = psi_critical
        self.accuracy_window   = accuracy_window
        self.min_accuracy_drop = min_accuracy_drop

        self._reference_features: Optional[pd.DataFrame] = None
        self._reference_accuracy: Optional[float]        = None
        self._prediction_log: list[dict]                 = []

    def set_reference_distribution(
        self,
        training_features: pd.DataFrame,
        reference_accuracy: Optional[float] = None,
    ):
        self._reference_features = training_features.copy()
        self._reference_accuracy = reference_accuracy
        log.info("Reference distribution set",
                 n_samples=len(training_features),
                 n_features=len(training_features.columns))

    def log_prediction(
        self,
        timestamp: str,
        symbol: str,
        features: dict,
        prediction: dict,
        realised_outcome: Optional[int] = None,
    ):
        self._prediction_log.append({
            "timestamp": timestamp, "symbol": symbol,
            "features": features,
            "prob_profit": prediction.get("prob_profit", 0.5),
            "action": prediction.get("action", "HOLD"),
            "realised_outcome": realised_outcome,
        })

    def check_drift(
        self,
        live_features: pd.DataFrame,
        window_days: int = 30,
    ) -> list[DriftAlert]:
        if self._reference_features is None:
            log.warning("No reference distribution — cannot check drift")
            return []

        alerts: list[DriftAlert] = []
        recent = live_features.tail(window_days)

        for col in self._reference_features.columns:
            if col not in recent.columns:
                continue
            ref_vals  = self._reference_features[col].dropna().values
            live_vals = recent[col].dropna().values
            if len(live_vals) < 20:
                continue

            # KS test
            ks_stat, p_value = stats.ks_2samp(ref_vals, live_vals)
            if p_value < self.ks_alpha:
                alerts.append(DriftAlert(
                    feature_name=col, drift_type="feature_drift",
                    statistic=round(float(ks_stat), 4),
                    p_value=round(float(p_value), 6),
                    severity="critical" if ks_stat > 0.3 else "warning",
                    message=(f"Feature '{col}' shifted "
                             f"(KS={ks_stat:.3f}, p={p_value:.4f}). "
                             f"Live mean={live_vals.mean():.4f}, "
                             f"ref mean={ref_vals.mean():.4f}."),
                ))

            # PSI
            psi = self._compute_psi(ref_vals, live_vals)
            if psi > self.psi_warning:
                alerts.append(DriftAlert(
                    feature_name=col, drift_type="psi_drift",
                    statistic=round(float(psi), 4), p_value=0.0,
                    severity="critical" if psi > self.psi_critical else "warning",
                    message=(f"PSI for '{col}' = {psi:.3f} "
                             f"(threshold: {self.psi_warning}/{self.psi_critical})."),
                ))

        acc_alert  = self._check_accuracy_drift()
        pred_alert = self._check_prediction_drift()
        if acc_alert:  alerts.append(acc_alert)
        if pred_alert: alerts.append(pred_alert)

        if alerts:
            log.warning("Drift detected", n_alerts=len(alerts),
                        critical=sum(1 for a in alerts if a.severity == "critical"))
        else:
            log.info("Drift check passed", window_days=window_days)

        return alerts

    def _compute_psi(self, reference: np.ndarray, production: np.ndarray,
                     n_bins: int = 10) -> float:
        bins = np.percentile(reference, np.linspace(0, 100, n_bins + 1))
        bins = np.unique(bins)
        if len(bins) < 2:
            return 0.0
        ref_counts,  _ = np.histogram(reference,  bins=bins)
        prod_counts, _ = np.histogram(production, bins=bins)
        ref_pct  = (ref_counts  + 0.001) / (len(reference)  + 0.001 * n_bins)
        prod_pct = (prod_counts + 0.001) / (len(production) + 0.001 * n_bins)
        return float(np.sum((prod_pct - ref_pct) * np.log(prod_pct / ref_pct)))

    def _check_accuracy_drift(self) -> Optional[DriftAlert]:
        if self._reference_accuracy is None:
            return None
        labelled = [
            p for p in self._prediction_log[-self.accuracy_window:]
            if p["realised_outcome"] is not None and p["action"] == "BUY"
        ]
        if len(labelled) < 15:
            return None
        recent_acc = float(np.mean([p["realised_outcome"] for p in labelled]))
        drop = self._reference_accuracy - recent_acc
        if drop > self.min_accuracy_drop:
            return DriftAlert(
                feature_name="prediction_accuracy", drift_type="accuracy_drift",
                statistic=round(drop, 4), p_value=0.0,
                severity="critical" if drop > 0.10 else "warning",
                message=(f"BUY accuracy dropped {drop:.1%}: "
                         f"ref={self._reference_accuracy:.1%} → "
                         f"recent={recent_acc:.1%} over {len(labelled)} signals."),
            )
        return None

    def _check_prediction_drift(self) -> Optional[DriftAlert]:
        if len(self._prediction_log) < 100:
            return None
        ref_probs    = [p["prob_profit"] for p in self._prediction_log[:100]]
        recent_probs = [p["prob_profit"] for p in self._prediction_log[-50:]]
        ks_stat, p_value = stats.ks_2samp(ref_probs, recent_probs)
        if p_value < 0.01 and ks_stat > 0.2:
            return DriftAlert(
                feature_name="prediction_probabilities", drift_type="prediction_drift",
                statistic=round(float(ks_stat), 4), p_value=round(float(p_value), 6),
                severity="warning",
                message=(f"Prediction distribution shifted (KS={ks_stat:.3f}). "
                         "Review model or retrain."),
            )
        return None

    def get_dashboard_stats(self) -> dict:
        if not self._prediction_log:
            return {"status": "no_predictions"}
        recent   = self._prediction_log[-30:]
        buys     = [p for p in recent if p["action"] == "BUY"]
        labelled = [p for p in recent if p["realised_outcome"] is not None]
        return {
            "total_predictions": len(self._prediction_log),
            "recent_30d": {
                "buy_signals": len(buys),
                "avg_prob": round(float(np.mean([p["prob_profit"] for p in recent])), 4),
                "realised_accuracy": (
                    round(float(np.mean([p["realised_outcome"] for p in labelled])), 4)
                    if labelled else None
                ),
            },
            "reference_accuracy": self._reference_accuracy,
        }
