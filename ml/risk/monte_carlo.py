# ml/risk/monte_carlo.py
"""
Monte Carlo simulation for forward return distribution estimation.

Two modes:
1. Historical bootstrap (preferred): sample from actual observed returns.
   Preserves fat tails. Scale by GARCH variance if available.
2. Parametric GBM (fallback): normally distributed returns.
   Underestimates tail risk but tractable.

Limitations acknowledged:
- GBM assumes constant vol (use GARCH instead)
- GBM ignores jumps (earnings gaps, black swans)
- Bootstrap assumes IID returns (autocorrelation exists)
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import structlog

log = structlog.get_logger()


@dataclass
class SimulationResult:
    horizon_days: int
    n_simulations: int
    initial_price: float
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    expected_return_pct: float
    prob_positive_return: float
    prob_10pct_loss: float
    prob_20pct_loss: float
    var_95_pct: float
    var_99_pct: float
    cvar_95_pct: float
    sample_paths: list[list[float]]


def run_monte_carlo(
    current_price: float,
    log_returns: pd.Series,
    horizon_days: int = 20,
    n_simulations: int = 10_000,
    garch_vol_forecast: Optional[float] = None,
    use_historical_bootstrap: bool = True,
    n_sample_paths: int = 100,
    random_seed: int = 42,
) -> SimulationResult:
    """
    Run Monte Carlo price path simulation.

    Args:
        current_price:          Current asset price
        log_returns:            Historical daily log returns (pd.Series)
        horizon_days:           Simulation horizon in trading days
        n_simulations:          Number of Monte Carlo paths
        garch_vol_forecast:     1-day annualised vol forecast from GARCH (optional)
        use_historical_bootstrap: If True, sample from empirical distribution
        n_sample_paths:         Paths to return for visualisation
        random_seed:            For reproducibility

    Returns:
        SimulationResult with full distribution statistics
    """
    rng = np.random.default_rng(random_seed)
    clean = log_returns.dropna().values

    if len(clean) < 50:
        raise ValueError("Need at least 50 return observations for simulation")

    # ── Generate return matrix (n_simulations × horizon_days) ────────────────
    if use_historical_bootstrap:
        sampled = rng.choice(clean, size=(n_simulations, horizon_days), replace=True)
        if garch_vol_forecast is not None:
            hist_vol_annual = clean.std() * np.sqrt(252)
            scale = garch_vol_forecast / max(hist_vol_annual, 1e-6)
            sampled = sampled * scale
    else:
        mu    = clean.mean() * 252
        sigma = garch_vol_forecast / np.sqrt(252) if garch_vol_forecast else clean.std()
        dt    = 1 / 252
        z     = rng.standard_normal((n_simulations, horizon_days))
        sampled = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z

    # ── Cumulative price paths ─────────────────────────────────────────────────
    cum_log = np.cumsum(sampled, axis=1)
    paths   = current_price * np.exp(cum_log)
    finals  = paths[:, -1]
    returns = (finals - current_price) / current_price

    # ── Statistics ────────────────────────────────────────────────────────────
    pcts    = np.percentile(finals, [5, 25, 50, 75, 95])
    var_95  = float(np.percentile(returns, 5))
    var_99  = float(np.percentile(returns, 1))
    cvar_95 = float(returns[returns <= var_95].mean())

    path_idx     = rng.choice(n_simulations, size=min(n_sample_paths, n_simulations), replace=False)
    sample_paths = [[round(float(v), 4) for v in paths[i]] for i in path_idx]

    result = SimulationResult(
        horizon_days=horizon_days, n_simulations=n_simulations,
        initial_price=current_price,
        p5=round(float(pcts[0]), 4), p25=round(float(pcts[1]), 4),
        p50=round(float(pcts[2]), 4), p75=round(float(pcts[3]), 4),
        p95=round(float(pcts[4]), 4),
        expected_return_pct=round(float(returns.mean() * 100), 3),
        prob_positive_return=round(float((returns > 0).mean()), 4),
        prob_10pct_loss=round(float((returns < -0.10).mean()), 4),
        prob_20pct_loss=round(float((returns < -0.20).mean()), 4),
        var_95_pct=round(float(abs(var_95) * 100), 3),
        var_99_pct=round(float(abs(var_99) * 100), 3),
        cvar_95_pct=round(float(abs(cvar_95) * 100), 3),
        sample_paths=sample_paths,
    )

    log.info("Monte Carlo complete", n=n_simulations, horizon=horizon_days,
             expected_return_pct=result.expected_return_pct,
             prob_positive=result.prob_positive_return,
             var_95=result.var_95_pct)

    return result
