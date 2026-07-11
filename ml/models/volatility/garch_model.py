# ml/models/volatility/garch_model.py
"""
GARCH(1,1) volatility model for conditional variance forecasting.

Why GARCH?
- Volatility clusters in financial time series (Mandelbrot 1963)
- Yesterday's volatility predicts today's volatility better than
  a rolling window average
- GARCH(1,1) is parsimonious — 3 parameters, captures 90% of
  what more complex models add

GARCH(1,1):
    sigma_t^2 = omega + alpha * epsilon_{t-1}^2 + beta * sigma_{t-1}^2
    where:
        omega  = long-run variance weight
        alpha  = ARCH term (reaction to shocks)
        beta   = GARCH term (persistence)
        alpha + beta < 1 required for stationarity

Uses the `arch` library if installed (recommended).
Falls back to manual MLE via scipy.optimize if not.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import structlog

log = structlog.get_logger()

try:
    from arch import arch_model
    ARCH_AVAILABLE = True
except ImportError:
    ARCH_AVAILABLE = False
    log.warning("arch library not available. Install: pip install arch")


@dataclass
class GARCHParams:
    omega: float
    alpha: float
    beta: float

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    @property
    def long_run_variance(self) -> float:
        if self.persistence >= 1.0:
            return float("inf")
        return self.omega / (1.0 - self.persistence)

    @property
    def long_run_volatility_annual(self) -> float:
        return float(np.sqrt(self.long_run_variance * 252))


class GARCHVolatilityModel:
    """
    GARCH(1,1) model for conditional variance forecasting.

    Usage:
        model = GARCHVolatilityModel()
        params = model.fit(log_returns)
        vol_forecast = model.forecast_1day_vol(log_returns)
        # Returns annualised 1-day-ahead vol forecast
    """

    def __init__(self):
        self.params: Optional[GARCHParams] = None
        self._fitted_variance: Optional[np.ndarray] = None

    def fit(self, log_returns: pd.Series) -> GARCHParams:
        """
        Fit GARCH(1,1) to log returns.
        Returns fitted parameters.
        """
        returns_pct = log_returns.dropna() * 100  # arch library expects % returns

        if ARCH_AVAILABLE:
            return self._fit_arch(returns_pct)
        else:
            return self._fit_manual(log_returns.dropna())

    def _fit_arch(self, returns_pct: pd.Series) -> GARCHParams:
        model = arch_model(
            returns_pct,
            vol="Garch",
            p=1, q=1,
            dist="normal",
            rescale=False,
        )
        result = model.fit(disp="off", show_warning=False)

        omega = float(result.params.get("omega", 0.01))
        alpha = float(result.params.get("alpha[1]", 0.05))
        beta  = float(result.params.get("beta[1]",  0.90))

        self.params = GARCHParams(omega=omega, alpha=alpha, beta=beta)
        self._fitted_variance = result.conditional_volatility.values ** 2 / 10_000

        log.info("GARCH fitted via arch library",
                 omega=round(omega, 6), alpha=round(alpha, 4),
                 beta=round(beta, 4),
                 persistence=round(self.params.persistence, 4),
                 long_run_vol=round(self.params.long_run_volatility_annual, 4))

        return self.params

    def _fit_manual(self, log_returns: np.ndarray | pd.Series) -> GARCHParams:
        """
        Manual GARCH(1,1) MLE via scipy.optimize.
        Used when arch library is not installed.
        Less numerically stable but avoids the dependency.
        """
        from scipy.optimize import minimize

        r = np.asarray(log_returns)
        n = len(r)

        def neg_log_likelihood(params):
            omega, alpha, beta = params
            if omega <= 0 or alpha <= 0 or beta <= 0 or alpha + beta >= 0.9999:
                return 1e10
            sigma2 = np.empty(n)
            sigma2[0] = r.var()
            for t in range(1, n):
                sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
            if np.any(sigma2 <= 0):
                return 1e10
            ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + r**2 / sigma2)
            return -ll

        x0 = [r.var() * 0.05, 0.10, 0.85]
        bounds = [(1e-8, None), (1e-6, 0.5), (1e-6, 0.9999)]
        result = minimize(neg_log_likelihood, x0, method="L-BFGS-B", bounds=bounds)

        omega, alpha, beta = result.x
        self.params = GARCHParams(omega=float(omega), alpha=float(alpha), beta=float(beta))

        # Compute fitted conditional variances
        sigma2 = np.empty(n)
        sigma2[0] = r.var()
        for t in range(1, n):
            sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
        self._fitted_variance = sigma2

        log.info("GARCH fitted manually",
                 omega=round(float(omega), 6), alpha=round(float(alpha), 4),
                 beta=round(float(beta), 4),
                 persistence=round(self.params.persistence, 4))

        return self.params

    def forecast_1day_vol(self, log_returns: pd.Series) -> float:
        """
        1-step-ahead conditional volatility forecast (annualised).
        Requires model to be fitted first.
        """
        if self.params is None:
            raise RuntimeError("Model not fitted. Call fit() first.")

        r = log_returns.dropna().values
        n = len(r)

        # Reconstruct conditional variance up to last observation
        sigma2 = np.empty(n)
        sigma2[0] = r.var()
        for t in range(1, n):
            sigma2[t] = (self.params.omega
                         + self.params.alpha * r[t-1]**2
                         + self.params.beta  * sigma2[t-1])

        # 1-step ahead
        sigma2_next = (self.params.omega
                       + self.params.alpha * r[-1]**2
                       + self.params.beta  * sigma2[-1])

        return float(np.sqrt(sigma2_next * 252))  # annualised

    def get_conditional_volatility(self) -> Optional[np.ndarray]:
        """Return the in-sample conditional volatility series (annualised)."""
        if self._fitted_variance is None:
            return None
        return np.sqrt(self._fitted_variance * 252)
