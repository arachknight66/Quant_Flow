# ml/models/volatility/garch_model.py
"""
GARCH(1,1) volatility forecasting.

Why GARCH before LSTM?
Because GARCH provably captures volatility clustering with 2 parameters
(α and β). An LSTM would need thousands of parameters and vastly more
data to learn what GARCH expresses in a closed form. For volatility
specifically, GARCH is the right tool.

GARCH forecasts are used for:
  1. Dynamic position sizing (scale down in high-vol regimes)
  2. ATR supplement for stop-loss placement
  3. Option pricing approximation
  4. Regime classification features for the ML model
  5. VaR estimation (GARCH-filtered historical simulation)
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import warnings
import structlog

log = structlog.get_logger()

# arch library for proper MLE estimation of GARCH parameters
try:
    from arch import arch_model
    ARCH_AVAILABLE = True
except ImportError:
    ARCH_AVAILABLE = False
    log.warning("arch library not available. Install: pip install arch")


@dataclass
class GARCHParams:
    """Fitted GARCH(1,1) parameters."""
    omega: float      # Long-run variance floor
    alpha: float      # ARCH term — shock persistence
    beta: float       # GARCH term — variance persistence
    mu: float         # Mean return (usually ~0 for short horizons)
    log_likelihood: float
    aic: float
    bic: float
    persistence: float   # alpha + beta — how long shocks last

    @property
    def long_run_variance(self) -> float:
        """
        Unconditional (long-run) variance.
        E[σ²] = ω / (1 - α - β)
        Only valid if alpha + beta < 1.
        """
        denom = 1 - self.alpha - self.beta
        if denom <= 0:
            return float("inf")
        return self.omega / denom

    @property
    def long_run_volatility_annual(self) -> float:
        """Annualised long-run volatility."""
        return np.sqrt(self.long_run_variance * 252)


class GARCHVolatilityModel:
    """
    Fits GARCH(1,1) to log returns and generates rolling volatility forecasts.

    Usage pattern:
        model = GARCHVolatilityModel()
        model.fit(log_returns)
        forecasts = model.forecast(horizon=5)
        regime = model.classify_regime(current_vol, historical_vol)
    """

    def __init__(self, p: int = 1, q: int = 1):
        self.p = p  # GARCH order
        self.q = q  # ARCH order
        self.params: Optional[GARCHParams] = None
        self._fitted_model = None
        self._returns: Optional[pd.Series] = None

    def fit(self, log_returns: pd.Series) -> GARCHParams:
        """
        Fit GARCH(1,1) via Maximum Likelihood Estimation.

        The log-likelihood function for GARCH assumes standardised residuals
        follow a Student-t distribution (better than Normal for fat tails):
            L = Σ [-0.5 * log(σ²ₜ) - 0.5 * (εₜ/σₜ)²]

        The arch library handles the numerical optimisation (L-BFGS-B).
        We multiply returns by 100 for numerical stability (common practice).

        Minimum data: ~500 observations for reliable parameter estimation.
        """
        if not ARCH_AVAILABLE:
            return self._fit_manual(log_returns)

        if len(log_returns) < 100:
            raise ValueError(f"Need at least 100 observations, got {len(log_returns)}")

        self._returns = log_returns.copy()
        returns_scaled = log_returns * 100  # Scale for numerical stability

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            am = arch_model(
                returns_scaled,
                vol="Garch",
                p=self.p,
                q=self.q,
                dist="StudentsT",  # Fat tails — more realistic than Normal
                mean="Constant",
            )
            result = am.fit(
                disp="off",
                show_warning=False,
                options={"maxiter": 200},
            )

        self._fitted_model = result

        params = result.params
        self.params = GARCHParams(
            omega=float(params["omega"]) / 10_000,   # Unscale
            alpha=float(params["alpha[1]"]),
            beta=float(params["beta[1]"]),
            mu=float(params.get("mu", 0)) / 100,
            log_likelihood=float(result.loglikelihood),
            aic=float(result.aic),
            bic=float(result.bic),
            persistence=float(params["alpha[1]"]) + float(params["beta[1]"]),
        )

        log.info(
            "GARCH fitted",
            alpha=round(self.params.alpha, 4),
            beta=round(self.params.beta, 4),
            persistence=round(self.params.persistence, 4),
            long_run_vol=round(self.params.long_run_volatility_annual * 100, 1),
        )

        if self.params.persistence >= 1.0:
            log.warning(
                "GARCH persistence >= 1.0: integrated variance (IGARCH). "
                "Shocks do not decay — long-run forecast unreliable."
            )

        return self.params

    def _fit_manual(self, log_returns: pd.Series) -> GARCHParams:
        """
        Manual GARCH(1,1) estimation when arch library unavailable.
        Uses simplified variance targeting approach.
        Not as precise as MLE but gives reasonable starting values.
        """
        returns = log_returns.values
        n = len(returns)

        # Variance targeting: set omega = long_run_var * (1 - alpha - beta)
        sigma2_unconditional = np.var(returns)

        # Typical starting values
        alpha = 0.10
        beta = 0.85
        omega = sigma2_unconditional * (1 - alpha - beta)

        sigma2 = np.full(n, sigma2_unconditional)
        for t in range(1, n):
            sigma2[t] = omega + alpha * returns[t-1]**2 + beta * sigma2[t-1]

        self._manual_variance = sigma2
        self.params = GARCHParams(
            omega=omega,
            alpha=alpha,
            beta=beta,
            mu=0.0,
            log_likelihood=0.0,
            aic=0.0,
            bic=0.0,
            persistence=alpha + beta,
        )
        return self.params

    def forecast(self, horizon: int = 5) -> dict:
        """
        Multi-step ahead variance forecast.

        GARCH h-step ahead forecast:
            σ²ₜ₊ₕ = ω·(1 + α+β + ... + (α+β)^(h-1)) + (α+β)^h · σ²ₜ

        As h → ∞, forecast reverts to unconditional variance ω/(1-α-β).
        The speed of mean reversion is governed by (α+β).

        For α+β=0.95 (typical), half-life ≈ 14 days.
        Volatility shocks persist for weeks, not days.
        """
        if self.params is None:
            raise RuntimeError("Model not fitted. Call fit() first.")

        if ARCH_AVAILABLE and self._fitted_model is not None:
            forecasts = self._fitted_model.forecast(horizon=horizon, reindex=False)
            # Unscale (we multiplied returns by 100, so variance by 10000)
            variance_forecasts = forecasts.variance.values[-1] / 10_000
            vol_daily = np.sqrt(variance_forecasts)
            vol_annual = vol_daily * np.sqrt(252)
        else:
            # Manual h-step ahead forecast
            p = self.params.persistence
            sigma2_current = self._manual_variance[-1] if hasattr(self, "_manual_variance") else \
                             self.params.long_run_variance
            lr_var = self.params.long_run_variance

            variance_forecasts = []
            for h in range(1, horizon + 1):
                forecast_h = lr_var + (p ** h) * (sigma2_current - lr_var)
                variance_forecasts.append(forecast_h)

            vol_daily = np.sqrt(variance_forecasts)
            vol_annual = vol_daily * np.sqrt(252)

        return {
            "horizon_days": list(range(1, horizon + 1)),
            "variance_daily": [round(float(v), 8) for v in variance_forecasts],
            "volatility_daily": [round(float(v), 6) for v in vol_daily],
            "volatility_annual": [round(float(v), 4) for v in vol_annual],
            "persistence": round(self.params.persistence, 4),
            "long_run_vol_annual": round(self.params.long_run_volatility_annual, 4),
        }

    def get_conditional_volatility_series(self, log_returns: pd.Series) -> pd.Series:
        """
        Compute the full historical conditional volatility time series.
        Used as a feature in the ML model.
        """
        if self.params is None:
            self.fit(log_returns)

        returns = log_returns.values
        n = len(returns)
        sigma2 = np.full(n, self.params.long_run_variance)

        for t in range(1, n):
            sigma2[t] = (self.params.omega
                         + self.params.alpha * returns[t-1]**2
                         + self.params.beta * sigma2[t-1])

        return pd.Series(
            np.sqrt(sigma2) * np.sqrt(252),  # Annualised
            index=log_returns.index,
            name="garch_vol_annual",
        )

    def classify_regime(
        self,
        current_vol: float,
        historical_vols: pd.Series,
        low_percentile: float = 33,
        high_percentile: float = 67,
    ) -> dict:
        """
        Classify current volatility regime using historical percentiles.

        Regimes matter for strategy performance:
        - Low vol: trend-following strategies tend to work
        - High vol: mean-reversion strategies tend to work (sometimes)
        - Transition: signals are least reliable

        Returns regime label and percentile rank.
        """
        pct_rank = float((historical_vols < current_vol).mean() * 100)
        low_thresh = float(np.percentile(historical_vols, low_percentile))
        high_thresh = float(np.percentile(historical_vols, high_percentile))

        if current_vol < low_thresh:
            regime = "low_volatility"
            signal_reliability = "higher"
        elif current_vol > high_thresh:
            regime = "high_volatility"
            signal_reliability = "lower"
        else:
            regime = "normal_volatility"
            signal_reliability = "moderate"

        return {
            "regime": regime,
            "current_vol_annual": round(current_vol, 4),
            "percentile_rank": round(pct_rank, 1),
            "low_threshold": round(low_thresh, 4),
            "high_threshold": round(high_thresh, 4),
            "signal_reliability": signal_reliability,
        }