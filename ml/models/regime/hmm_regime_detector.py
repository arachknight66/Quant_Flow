import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import structlog

log = structlog.get_logger()

try:
    from hmmlearn import hmm
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    log.warning("hmmlearn not available. Install: pip install hmmlearn")


@dataclass
class RegimeProperties:
    regime_id: int
    label: str
    mean_return_daily: float
    std_return_daily: float
    mean_return_annual: float
    vol_annual: float
    avg_duration_days: float
    transition_prob_self: float


class HMMRegimeDetector:
    """
    Gaussian Hidden Markov Model for market regime detection.
    3 hidden states: bull / sideways / bear.
    """

    def __init__(self, n_regimes: int = 3, n_iter: int = 200, random_state: int = 42):
        self.n_regimes    = n_regimes
        self.n_iter       = n_iter
        self.random_state = random_state
        self._model       = None
        self.regime_properties: dict[int, RegimeProperties] = {}
        self._state_sequence: Optional[np.ndarray] = None
        self._returns: Optional[pd.Series] = None

    def fit(self, log_returns: pd.Series) -> dict:
        if not HMM_AVAILABLE:
            return self._fit_simple(log_returns)
        self._returns = log_returns.copy()
        X = log_returns.values.reshape(-1, 1)
        model = hmm.GaussianHMM(n_components=self.n_regimes, covariance_type="full",
                                 n_iter=self.n_iter, random_state=self.random_state, verbose=False)
        model.fit(X)
        self._model = model
        self._state_sequence = model.predict(X)
        self._classify_regimes(log_returns)
        log.info("HMM fitted", n_regimes=self.n_regimes,
                 labels=[r.label for r in self.regime_properties.values()])
        return {
            "transition_matrix": model.transmat_.tolist(),
            "regime_means": model.means_.flatten().tolist(),
            "regime_properties": {k: {"label": v.label, "vol_annual": v.vol_annual}
                                   for k, v in self.regime_properties.items()},
        }

    def _classify_regimes(self, log_returns: pd.Series):
        regime_stats = {}
        for r in range(self.n_regimes):
            mask = self._state_sequence == r
            r_returns = log_returns.values[mask]
            if len(r_returns) == 0:
                continue
            runs, cur = [], 0
            for s in self._state_sequence:
                if s == r: cur += 1
                elif cur > 0: runs.append(cur); cur = 0
            regime_stats[r] = {
                "mean_daily": float(np.mean(r_returns)),
                "std_daily":  float(np.std(r_returns)),
                "avg_duration": float(np.mean(runs)) if runs else 1.0,
            }
        sorted_r = sorted(regime_stats, key=lambda r: regime_stats[r]["mean_daily"])
        labels = {}
        if len(sorted_r) == 2:
            labels = {sorted_r[0]: "bear", sorted_r[1]: "bull"}
        elif len(sorted_r) == 3:
            labels = {sorted_r[0]: "bear", sorted_r[1]: "sideways", sorted_r[2]: "bull"}
        else:
            labels = {r: f"regime_{i}" for i, r in enumerate(sorted_r)}
        for r, stats in regime_stats.items():
            tp = self._model.transmat_[r, r] if self._model else 0.9
            self.regime_properties[r] = RegimeProperties(
                regime_id=r, label=labels.get(r, f"regime_{r}"),
                mean_return_daily=stats["mean_daily"], std_return_daily=stats["std_daily"],
                mean_return_annual=stats["mean_daily"] * 252,
                vol_annual=stats["std_daily"] * np.sqrt(252),
                avg_duration_days=stats["avg_duration"],
                transition_prob_self=float(tp),
            )

    def _fit_simple(self, log_returns: pd.Series) -> dict:
        """
        k-means fallback when hmmlearn is not installed.
        Phase 2.1 fix: .bfill() instead of deprecated fillna(method="bfill")
        """
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        self._returns = log_returns.copy()
        # Phase 2.1 fix: was .fillna(method="bfill"), deprecated in pandas 2.1+
        rolling_vol = log_returns.rolling(20).std().bfill()
        features = np.column_stack([log_returns.values, rolling_vol.values])
        scaler = StandardScaler()
        features_scaled = scaler.fit_transform(features)
        kmeans = KMeans(n_clusters=self.n_regimes, random_state=self.random_state, n_init=10)
        self._state_sequence = kmeans.fit_predict(features_scaled)
        self._classify_regimes_simple(log_returns)
        return {"method": "kmeans_fallback"}

    def _classify_regimes_simple(self, log_returns: pd.Series):
        for r in range(self.n_regimes):
            mask = self._state_sequence == r
            r_returns = log_returns.values[mask]
            if len(r_returns) == 0:
                continue
            mean_d = float(np.mean(r_returns))
            std_d  = float(np.std(r_returns))
            label  = "bull" if mean_d > 0.001 else "bear" if mean_d < -0.001 else "sideways"
            self.regime_properties[r] = RegimeProperties(
                regime_id=r, label=label,
                mean_return_daily=mean_d, std_return_daily=std_d,
                mean_return_annual=mean_d * 252, vol_annual=std_d * np.sqrt(252),
                avg_duration_days=10.0, transition_prob_self=0.9,
            )

    def predict_current_regime(self, recent_returns: pd.Series) -> dict:
        if self._model is None:
            raise RuntimeError("Model not fitted.")
        X = recent_returns.values.reshape(-1, 1)
        state_probs   = self._model.predict_proba(X)
        current_probs = state_probs[-1]
        current_state = int(np.argmax(current_probs))
        regime = self.regime_properties.get(current_state)
        return {
            "current_regime": regime.label if regime else f"state_{current_state}",
            "regime_id": current_state,
            "state_probabilities": {
                self.regime_properties.get(i, RegimeProperties(i,f"state_{i}",0,0,0,0,0,0)).label:
                round(float(p), 4) for i, p in enumerate(current_probs)
            },
            "position_size_multiplier": {"bull":1.0,"sideways":0.6,"bear":0.3}.get(
                regime.label if regime else "sideways", 0.5),
        }

    def add_regime_features(self, df: pd.DataFrame, log_returns: pd.Series) -> pd.DataFrame:
        if self._state_sequence is None:
            return df
        for r in range(self.n_regimes):
            rp = self.regime_properties.get(r)
            col = f"regime_{rp.label if rp else r}"
            df[col] = pd.Series(
                (self._state_sequence == r).astype(float),
                index=log_returns.index[:len(self._state_sequence)])
        if self._model:
            X = log_returns.values.reshape(-1, 1)
            probs = self._model.predict_proba(X)
            entropy = -np.sum(probs * np.log(probs + 1e-10), axis=1)
            df["regime_entropy"] = pd.Series(entropy, index=log_returns.index[:len(entropy)])
        else:
            df["regime_entropy"] = pd.Series(0.0, index=log_returns.index[:len(self._state_sequence)])
        return df
