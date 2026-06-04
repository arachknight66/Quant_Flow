# backend/monitoring/model_monitor.py
"""
Production model monitoring — detecting when models degrade.

Models in production degrade for two reasons:
1. Data drift: the distribution of input features changes
   (e.g. volatility regime shifts, new market structure)
2. Concept drift: the feature→target relationship changes
   (e.g. RSI divergence that worked in 2019 stops working in 2022)

We monitor:
  - Feature drift: KS test comparing live feature distribution
    to training distribution
  - Prediction drift: is the model's probability distribution
    shifting significantly?
  - Accuracy drift: is realised accuracy degrading vs backtest?
  - Data quality: are features arriving with correct statistics?

When drift is detected, the system alerts — it does NOT automatically
retrain, because automated retraining without human review can
amplify problems.
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
    """Raised when significant drift is detected."""
    feature_name: str
    drift_type: str          # "feature_drift", "prediction_drift", "accuracy_drift"
    statistic: float         # KS statistic or similar
    p_value: float
    severity: str            # "warning" | "critical"
    message: str


class ModelMonitor:
    """
    Tracks feature distributions, prediction distributions, and
    realised accuracy for a deployed model.

    Usage:
        monitor = ModelMonitor()
        monitor.set_reference_distribution(training_features)

        # Every day, after new predictions:
        alerts = monitor.check_drift(live_features, live_predictions, realised_outcomes)
        if alerts:
            notify_team(alerts)
    """

    def __init__(
        self,
        ks_alpha: float = 0.01,         # Significance level for KS test
        psi_warning: float = 0.1,       # PSI warning threshold
        psi_critical: float = 0.25,     # PSI critical threshold
        accuracy_window: int = 60,      # Days to measure rolling accuracy
        min_accuracy_drop: float = 0.05, # Alert if accuracy drops >5pp vs reference
    ):
        self.ks_alpha = ks_alpha
        self.psi_warning = psi_warning
        self.psi_critical = psi_critical
        self.accuracy_window = accuracy_window
        self.min_accuracy_drop = min_accuracy_drop

        self._reference_features: Optional[pd.DataFrame] = None
        self._reference_accuracy: Optional[float] = None
        self._prediction_log: list[dict] = []

    def set_reference_distribution(
        self,
        training_features: pd.DataFrame,
        reference_accuracy: Optional[float] = None,
    ):
        """
        Store training feature distributions as the reference.
        Run this once when deploying a new model version.
        """
        self._reference_features = training_features.copy()
        self._reference_accuracy = reference_accuracy
        log.info(
            "Reference distribution set",
            n_samples=len(training_features),
            n_features=len(training_features.columns),
        )

    def log_prediction(
        self,
        timestamp: str,
        symbol: str,
        features: dict,
        prediction: dict,
        realised_outcome: Optional[int] = None,  # 1=profit, 0=loss, None=pending
    ):
        """Log a prediction for monitoring. Call after each live signal."""
        self._prediction_log.append({
            "timestamp": timestamp,
            "symbol": symbol,
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
        """
        Run drift detection on the most recent window of live data.
        Returns a list of DriftAlerts (empty = no drift detected).
        """
        if self._reference_features is None:
            log.warning("No reference distribution set — cannot check drift")
            return []

        alerts = []
        recent = live_features.tail(window_days)

        for col in self._reference_features.columns:
            if col not in recent.columns:
                continue

            ref_vals = self._reference_features[col].dropna().values
            live_vals = recent[col].dropna().values

            if len(live_vals) < 20:
                continue

            # Kolmogorov-Smirnov test for distribution shift
            ks_stat, p_value = stats.ks_2samp(ref_vals, live_vals)

            if p_value < self.ks_alpha:
                severity = "critical" if ks_stat > 0.3 else "warning"
                alerts.append(DriftAlert(
                    feature_name=col,
                    drift_type="feature_drift",
                    statistic=round(float(ks_stat), 4),
                    p_value=round(float(p_value), 6),
                    severity=severity,
                    message=(
                        f"Feature '{col}' distribution has shifted significantly "
                        f"(KS={ks_stat:.3f}, p={p_value:.4f}). "
                        f"Live mean={live_vals.mean():.4f}, "
                        f"ref mean={ref_vals.mean():.4f}."
                    ),
                ))

            # Population Stability Index (PSI) — industry standard for feature drift
            psi = self._compute_psi(ref_vals, live_vals)
            if psi > self.psi_warning:
                severity = "critical" if psi > self.psi_critical else "warning"
                alerts.append(DriftAlert(
                    feature_name=col,
                    drift_type="psi_drift",
                    statistic=round(float(psi), 4),
                    p_value=0.0,
                    severity=severity,
                    message=(
                        f"PSI for '{col}' = {psi:.3f} "
                        f"({'critical' if psi > self.psi_critical else 'warning'} threshold). "
                        "Consider retraining."
                    ),
                ))

        # Accuracy drift
        accuracy_alert = self._check_accuracy_drift()
        if accuracy_alert:
            alerts.append(accuracy_alert)

        # Prediction distribution drift
        pred_alert = self._check_prediction_drift()
        if pred_alert:
            alerts.append(pred_alert)

        if alerts:
            log.warning(
                "Drift detected",
                n_alerts=len(alerts),
                critical=sum(1 for a in alerts if a.severity == "critical"),
            )
        else:
            log.info("Drift check passed", window_days=window_days)

        return alerts

    def _compute_psi(
        self,
        reference: np.ndarray,
        production: np.ndarray,
        n_bins: int = 10,
    ) -> float:
        """
        Population Stability Index.
        PSI = Σ (actual% - expected%) × ln(actual% / expected%)

        Interpretation:
          PSI < 0.1:  No significant change
          PSI < 0.25: Moderate change — monitor
          PSI >= 0.25: Significant change — investigate / retrain
        """
        bins = np.percentile(reference, np.linspace(0, 100, n_bins + 1))
        bins = np.unique(bins)
        if len(bins) < 2:
            return 0.0

        ref_counts, _ = np.histogram(reference, bins=bins)
        prod_counts, _ = np.histogram(production, bins=bins)

        ref_pct = (ref_counts + 0.001) / (len(reference) + 0.001 * n_bins)
        prod_pct = (prod_counts + 0.001) / (len(production) + 0.001 * n_bins)

        psi = np.sum((prod_pct - ref_pct) * np.log(prod_pct / ref_pct))
        return float(psi)

    def _check_accuracy_drift(self) -> Optional[DriftAlert]:
        """Compare recent realised accuracy vs reference accuracy."""
        if self._reference_accuracy is None:
            return None

        recent_labelled = [
            p for p in self._prediction_log[-self.accuracy_window:]
            if p["realised_outcome"] is not None and p["action"] == "BUY"
        ]

        if len(recent_labelled) < 15:
            return None

        recent_accuracy = np.mean([p["realised_outcome"] for p in recent_labelled])
        accuracy_drop = self._reference_accuracy - recent_accuracy

        if accuracy_drop > self.min_accuracy_drop:
            return DriftAlert(
                feature_name="prediction_accuracy",
                drift_type="accuracy_drift",
                statistic=round(float(accuracy_drop), 4),
                p_value=0.0,
                severity="critical" if accuracy_drop > 0.10 else "warning",
                message=(
                    f"BUY signal accuracy dropped {accuracy_drop:.1%} "
                    f"from reference {self._reference_accuracy:.1%} to "
                    f"{recent_accuracy:.1%} over last {len(recent_labelled)} signals."
                ),
            )
        return None

    def _check_prediction_drift(self) -> Optional[DriftAlert]:
        """Detect if the model is producing systematically different probabilities."""
        if len(self._prediction_log) < 100:
            return None

        reference_probs = [p["prob_profit"] for p in self._prediction_log[:100]]
        recent_probs = [p["prob_profit"] for p in self._prediction_log[-50:]]

        ks_stat, p_value = stats.ks_2samp(reference_probs, recent_probs)

        if p_value < 0.01 and ks_stat > 0.2:
            return DriftAlert(
                feature_name="prediction_probabilities",
                drift_type="prediction_drift",
                statistic=round(float(ks_stat), 4),
                p_value=round(float(p_value), 6),
                severity="warning",
                message=(
                    f"Model probability distribution has shifted (KS={ks_stat:.3f}). "
                    "Recent predictions are systematically different. Review model."
                ),
            )
        return None

    def get_dashboard_stats(self) -> dict:
        """Summary statistics for a monitoring dashboard."""
        if not self._prediction_log:
            return {"status": "no_predictions"}

        recent = self._prediction_log[-30:]
        buy_signals = [p for p in recent if p["action"] == "BUY"]
        labelled = [p for p in recent if p["realised_outcome"] is not None]

        return {
            "total_predictions": len(self._prediction_log),
            "recent_30d": {
                "buy_signals": len(buy_signals),
                "avg_prob": round(np.mean([p["prob_profit"] for p in recent]), 4),
                "realised_accuracy": (
                    round(float(np.mean([p["realised_outcome"] for p in labelled])), 4)
                    if labelled else None
                ),
            },
            "reference_accuracy": self._reference_accuracy,
        }