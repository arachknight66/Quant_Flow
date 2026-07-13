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
        valid_returns = log_returns.dropna()
        if len(valid_returns) < 10:
            return {"status": "insufficient_data"}
            
        fit_len = min(len(valid_returns), 150)
        fit_returns = valid_returns.iloc[:fit_len]
        
        self._returns = valid_returns.copy()
        
        if not HMM_AVAILABLE:
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler
            
            # Prepare features
            rolling_vol = valid_returns.rolling(20).std().bfill()
            features = np.column_stack([valid_returns.values, rolling_vol.values])
            
            # Fit scaler and kmeans on fit prefix
            self._scaler = StandardScaler()
            self._scaler.fit(features[:fit_len])
            features_scaled_fit = self._scaler.transform(features[:fit_len])
            
            self._kmeans = KMeans(n_clusters=self.n_regimes, random_state=self.random_state, n_init=10)
            fit_labels = self._kmeans.fit_predict(features_scaled_fit)
            
            # Classify regimes based on fit returns and fit labels
            self._classify_regimes_from_labels(fit_returns, fit_labels)
            
            # Compute lookahead-free state sequence for the entire dataset
            features_scaled = self._scaler.transform(features)
            self._state_sequence = self._kmeans.predict(features_scaled)
            
            log.info("KMeans fallback fitted lookahead-free", n_regimes=self.n_regimes)
            return {"method": "kmeans_fallback"}
        else:
            X_fit = fit_returns.values.reshape(-1, 1)
            model = hmm.GaussianHMM(n_components=self.n_regimes, covariance_type="full",
                                     n_iter=self.n_iter, random_state=self.random_state, verbose=False)
            model.fit(X_fit)
            self._model = model
            
            # Classify regimes using in-sample fit
            fit_labels = model.predict(X_fit)
            self._classify_regimes_from_labels(fit_returns, fit_labels)
            
            # Compute lookahead-free state sequence for the entire dataset
            X_all = valid_returns.values.reshape(-1, 1)
            states = np.empty(len(valid_returns), dtype=int)
            states[:fit_len] = fit_labels
            
            for t in range(fit_len, len(valid_returns)):
                probs = model.predict_proba(X_all[:t+1])[-1]
                states[t] = np.argmax(probs)
                
            self._state_sequence = states
            log.info("HMM fitted lookahead-free", n_regimes=self.n_regimes,
                     labels=[r.label for r in self.regime_properties.values()])
            
            return {
                "transition_matrix": model.transmat_.tolist(),
                "regime_means": model.means_.flatten().tolist(),
                "regime_properties": {k: {"label": v.label, "vol_annual": v.vol_annual}
                                       for k, v in self.regime_properties.items()},
            }

    def _classify_regimes_from_labels(self, log_returns: pd.Series, state_sequence: np.ndarray):
        regime_stats = {}
        for r in range(self.n_regimes):
            mask = state_sequence == r
            r_returns = log_returns.values[mask]
            if len(r_returns) == 0:
                continue
            runs, cur = [], 0
            for s in state_sequence:
                if s == r: cur += 1
                elif cur > 0: runs.append(cur); cur = 0
            regime_stats[r] = {
                "mean_daily": float(np.mean(r_returns)),
                "std_daily":  float(np.std(r_returns)),
                "avg_duration": float(np.mean(runs)) if runs else 10.0,
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
            if self._model:
                tp = self._model.transmat_[r, r]
            else:
                tp = 0.9
            self.regime_properties[r] = RegimeProperties(
                regime_id=r, label=labels.get(r, f"regime_{r}"),
                mean_return_daily=stats["mean_daily"], std_return_daily=stats["std_daily"],
                mean_return_annual=stats["mean_daily"] * 252, vol_annual=stats["std_daily"] * np.sqrt(252),
                avg_duration_days=stats["avg_duration"], transition_prob_self=float(tp),
            )

    def predict_current_regime(self, recent_returns: pd.Series) -> dict:
        if self._model is None:
            if hasattr(self, "_kmeans") and self._kmeans is not None:
                vol = recent_returns.std()
                if pd.isna(vol) or vol == 0:
                    vol = 0.01
                X_new = np.array([[recent_returns.iloc[-1], vol]])
                X_scaled = self._scaler.transform(X_new)
                current_state = int(self._kmeans.predict(X_scaled)[0])
                regime = self.regime_properties.get(current_state)
                current_probs = [1.0 if i == current_state else 0.0 for i in range(self.n_regimes)]
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
        valid_returns = log_returns.dropna()
        for r in range(self.n_regimes):
            rp = self.regime_properties.get(r)
            col = f"regime_{rp.label if rp else r}"
            df[col] = pd.Series(
                (self._state_sequence == r).astype(float),
                index=valid_returns.index)
        if self._model:
            X_all = valid_returns.values.reshape(-1, 1)
            fit_len = min(len(valid_returns), 150)
            entropy = np.empty(len(valid_returns))
            fit_probs = self._model.predict_proba(X_all[:fit_len])
            entropy[:fit_len] = -np.sum(fit_probs * np.log(fit_probs + 1e-10), axis=1)
            
            for t in range(fit_len, len(valid_returns)):
                probs = self._model.predict_proba(X_all[:t+1])[-1]
                entropy[t] = -np.sum(probs * np.log(probs + 1e-10))
                
            df["regime_entropy"] = pd.Series(entropy, index=valid_returns.index)
        else:
            df["regime_entropy"] = pd.Series(0.0, index=valid_returns.index)
        return df
