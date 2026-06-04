# ml/models/regime/hmm_regime_detector.py
"""
Hidden Markov Model for market regime detection.

Markets don't have a single statistical regime — they alternate between
distinct states (bull/bear/sideways, low/high volatility, trending/mean-reverting).
A model trained on bull market data will fail in bear markets.

The HMM approach:
  - Observable: log returns (and optionally volatility, volume)
  - Hidden states: "regimes" (e.g. 2–4 states)
  - Transition matrix: probability of moving between regimes
  - Emission distributions: Gaussian per regime

We use this to:
  1. CONDITION signals: "This is a bear regime — reduce position sizes"
  2. DETECT shifts early: transition probability spikes before prices move
  3. Add regime as a feature to the XGBoost model
  4. Avoid deploying bull-market models in bear regimes

Critical limitation: HMM regimes are unlabelled — we label them
post-hoc by their properties (mean return, volatility). Labels
can flip between training runs (the "label switching" problem).
"""
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
    """Statistical properties of a detected regime."""
    regime_id: int
    label: str            # "bull", "bear", "sideways" (assigned post-hoc)
    mean_return_daily: float
    std_return_daily: float
    mean_return_annual: float
    vol_annual: float
    avg_duration_days: float
    transition_prob_self: float  # Probability of staying in this regime


class HMMRegimeDetector:
    """
    Gaussian Hidden Markov Model for regime detection.

    Architecture:
    - 3 hidden states (empirically: bull, bear, sideways/low-vol)
    - Gaussian emissions on daily log returns
    - Baum-Welch EM algorithm for parameter estimation
    - Viterbi algorithm for most likely state sequence

    Hyperparameter choice:
    n_components=3 is almost always appropriate for equity markets.
    2 states is too coarse (misses sideways). 4+ overfits short regimes.
    Validate with AIC/BIC; rarely need more than 3.

    Practical note: Re-fit monthly with recent data for regime stability.
    """

    def __init__(self, n_regimes: int = 3, n_iter: int = 200, random_state: int = 42):
        self.n_regimes = n_regimes
        self.n_iter = n_iter
        self.random_state = random_state
        self._model = None
        self.regime_properties: dict[int, RegimeProperties] = {}
        self._state_sequence: Optional[np.ndarray] = None
        self._returns: Optional[pd.Series] = None

    def fit(self, log_returns: pd.Series) -> dict:
        """
        Fit the HMM to observed log returns.

        Returns regime properties (mean/vol per regime, transition matrix).
        """
        if not HMM_AVAILABLE:
            return self._fit_simple(log_returns)

        self._returns = log_returns.copy()
        X = log_returns.values.reshape(-1, 1)

        # GaussianHMM: each hidden state has a Gaussian emission distribution
        model = hmm.GaussianHMM(
            n_components=self.n_regimes,
            covariance_type="full",
            n_iter=self.n_iter,
            random_state=self.random_state,
            verbose=False,
        )

        model.fit(X)
        self._model = model

        # Decode: get most likely state sequence
        self._state_sequence = model.predict(X)

        # Compute regime properties
        self._classify_regimes(log_returns)

        log.info(
            "HMM fitted",
            n_regimes=self.n_regimes,
            regime_labels=[r.label for r in self.regime_properties.values()],
        )

        return {
            "transition_matrix": model.transmat_.tolist(),
            "regime_means": model.means_.flatten().tolist(),
            "regime_stds": np.sqrt(model.covars_.flatten()).tolist(),
            "regime_properties": {
                k: {
                    "label": v.label,
                    "mean_return_annual": v.mean_return_annual,
                    "vol_annual": v.vol_annual,
                    "avg_duration_days": v.avg_duration_days,
                }
                for k, v in self.regime_properties.items()
            },
        }

    def _classify_regimes(self, log_returns: pd.Series):
        """
        Label regimes post-hoc by their return and volatility characteristics.
        Regime with highest mean return = "bull".
        Regime with lowest mean return = "bear".
        Remaining = "sideways" or "transition".
        """
        regime_stats = {}
        for r in range(self.n_regimes):
            mask = self._state_sequence == r
            r_returns = log_returns.values[mask]

            if len(r_returns) == 0:
                continue

            # Average duration: count consecutive runs
            runs = []
            current_run = 0
            for s in self._state_sequence:
                if s == r:
                    current_run += 1
                elif current_run > 0:
                    runs.append(current_run)
                    current_run = 0
            avg_dur = np.mean(runs) if runs else 1.0

            regime_stats[r] = {
                "mean_daily": float(np.mean(r_returns)),
                "std_daily": float(np.std(r_returns)),
                "count": int(np.sum(mask)),
                "avg_duration": float(avg_dur),
            }

        # Sort by mean return to assign labels
        sorted_regimes = sorted(regime_stats.keys(), key=lambda r: regime_stats[r]["mean_daily"])

        labels = {}
        if len(sorted_regimes) == 2:
            labels = {sorted_regimes[0]: "bear", sorted_regimes[1]: "bull"}
        elif len(sorted_regimes) == 3:
            labels = {
                sorted_regimes[0]: "bear",
                sorted_regimes[1]: "sideways",
                sorted_regimes[2]: "bull",
            }
        else:
            for i, r in enumerate(sorted_regimes):
                labels[r] = f"regime_{i}"

        for r, stats in regime_stats.items():
            trans_prob = self._model.transmat_[r, r] if self._model else 0.9
            self.regime_properties[r] = RegimeProperties(
                regime_id=r,
                label=labels.get(r, f"regime_{r}"),
                mean_return_daily=stats["mean_daily"],
                std_return_daily=stats["std_daily"],
                mean_return_annual=stats["mean_daily"] * 252,
                vol_annual=stats["std_daily"] * np.sqrt(252),
                avg_duration_days=stats["avg_duration"],
                transition_prob_self=float(trans_prob),
            )

    def _fit_simple(self, log_returns: pd.Series) -> dict:
        """Fallback regime detection without hmmlearn: k-means on (return, vol)."""
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler

        self._returns = log_returns.copy()
        rolling_vol = log_returns.rolling(20).std().fillna(method="bfill")
        features = np.column_stack([log_returns.values, rolling_vol.values])

        scaler = StandardScaler()
        features_scaled = scaler.fit_transform(features)

        kmeans = KMeans(n_clusters=self.n_regimes, random_state=self.random_state, n_init=10)
        self._state_sequence = kmeans.fit_predict(features_scaled)
        self._classify_regimes_simple(log_returns)

        return {"method": "kmeans_fallback"}

    def _classify_regimes_simple(self, log_returns: pd.Series):
        """Label clusters for k-means fallback."""
        for r in range(self.n_regimes):
            mask = self._state_sequence == r
            r_returns = log_returns.values[mask]
            if len(r_returns) == 0:
                continue
            mean_d = float(np.mean(r_returns))
            std_d = float(np.std(r_returns))
            if mean_d > 0.001:
                label = "bull"
            elif mean_d < -0.001:
                label = "bear"
            else:
                label = "sideways"
            self.regime_properties[r] = RegimeProperties(
                regime_id=r, label=label,
                mean_return_daily=mean_d, std_return_daily=std_d,
                mean_return_annual=mean_d * 252,
                vol_annual=std_d * np.sqrt(252),
                avg_duration_days=10.0, transition_prob_self=0.9,
            )

    def predict_current_regime(self, recent_returns: pd.Series) -> dict:
        """
        Predict the most likely current regime given recent returns.

        Returns regime label + probability of being in each regime.
        """
        if self._model is None:
            raise RuntimeError("Model not fitted.")

        X = recent_returns.values.reshape(-1, 1)
        state_probs = self._model.predict_proba(X)
        current_probs = state_probs[-1]
        current_state = int(np.argmax(current_probs))
        regime = self.regime_properties.get(current_state)

        return {
            "current_regime": regime.label if regime else f"state_{current_state}",
            "regime_id": current_state,
            "state_probabilities": {
                self.regime_properties.get(i, RegimeProperties(i, f"state_{i}", 0, 0, 0, 0, 0, 0)).label:
                round(float(p), 4)
                for i, p in enumerate(current_probs)
            },
            "regime_properties": {
                "mean_return_annual": round(regime.mean_return_annual * 100, 2) if regime else 0,
                "vol_annual": round(regime.vol_annual * 100, 2) if regime else 0,
                "avg_duration_days": round(regime.avg_duration_days, 1) if regime else 0,
            },
            "position_size_multiplier": self._get_regime_multiplier(
                regime.label if regime else "sideways"
            ),
        }

    def _get_regime_multiplier(self, regime_label: str) -> float:
        """
        Scale position sizes based on regime.
        In a bear regime: reduce positions significantly.
        In a sideways regime: trade smaller (signals less reliable).
        In a bull regime: trade at normal size.
        """
        return {
            "bull": 1.0,
            "sideways": 0.6,
            "bear": 0.3,
        }.get(regime_label, 0.5)

    def add_regime_features(self, df: pd.DataFrame, log_returns: pd.Series) -> pd.DataFrame:
        """
        Append regime-based features to a feature DataFrame.
        These become inputs to the XGBoost classifier.
        """
        if self._model is None or self._state_sequence is None:
            return df

        # One-hot encode regime state
        for r in range(self.n_regimes):
            regime_label = self.regime_properties.get(r)
            col = f"regime_{regime_label.label if regime_label else r}"
            regime_series = pd.Series(
                (self._state_sequence == r).astype(float),
                index=log_returns.index[:len(self._state_sequence)],
            )
            df[col] = regime_series

        # Regime transition probability (detect regime change early)
        if self._model:
            X = log_returns.values.reshape(-1, 1)
            state_probs = self._model.predict_proba(X)
            # "Entropy" of regime — high = uncertain which regime we're in
            entropy = -np.sum(state_probs * np.log(state_probs + 1e-10), axis=1)
            df["regime_entropy"] = pd.Series(
                entropy, index=log_returns.index[:len(entropy)]
            )

        return df