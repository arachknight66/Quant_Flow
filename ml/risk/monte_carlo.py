# ml/risk/monte_carlo.py
"""
Monte Carlo simulation for forward return distribution estimation.

We use GBM to model price paths, but acknowledge its limitations:
- GBM assumes constant volatility (wrong — use GARCH variance instead)
- GBM assumes normal returns (wrong — fat tails exist)
- GBM ignores jumps (wrong — earnings gaps, black swans exist)

Despite these limitations, Monte Carlo with GBM gives a reasonable
first approximation of the probability distribution of outcomes,
especially useful for risk visualisation.

For more accurate tail risk: use historical simulation with
GARCH-filtered residuals (bootstrap from standardised residuals,
scale by GARCH forecasted variance). This preserves the
empirically observed fat tails.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import structlog

log = structlog.get_logger()


@dataclass
class SimulationResult:
    """Output of a Monte Carlo simulation."""
    horizon_days: int
    n_simulations: int
    initial_price: float
    # Percentile outcomes
    p5: float   # 5th percentile — bad scenario
    p25: float  # 25th percentile
    p50: float  # Median
    p75: float  # 75th percentile
    p95: float  # 95th percentile — good scenario
    # Return statistics
    expected_return_pct: float
    prob_positive_return: float
    prob_10pct_loss: float
    prob_20pct_loss: float
    # VaR (already positive — represents loss amount)
    var_95_pct: float
    var_99_pct: float
    cvar_95_pct: float  # Conditional VaR / Expected Shortfall
    # Path data for visualisation (subset of simulations)
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
    Run Monte Carlo simulation for price path generation.

    Two modes:
    1. Historical bootstrap (preferred): Sample from actual observed returns
       with replacement. Preserves fat tails and skewness from real data.
       Uses GARCH-forecasted volatility to scale if available.

    2. Parametric GBM (fallback): Generate normally-distributed returns.
       Faster, analytically tractable, but underestimates tail risk.

    Args:
        current_price: Current asset price
        log_returns: Historical daily log returns
        horizon_days: Simulation horizon in trading days
        n_simulations: Number of Monte Carlo paths
        garch_vol_forecast: GARCH 1-day vol forecast (annualised).
                            If provided, scales bootstrapped returns.
        use_historical_bootstrap: If True, use empirical distribution
        n_sample_paths: Number of paths to return for visualisation
        random_seed: For reproducibility

    Returns:
        SimulationResult with distribution statistics and sample paths
    """
    rng = np.random.default_rng(random_seed)

    clean_returns = log_returns.dropna().values
    if len(clean_returns) < 50:
        raise ValueError("Need at least 50 return observations for simulation")

    # ---- Generate return matrix: (n_simulations, horizon_days) ----
    if use_historical_bootstrap:
        # Bootstrap: sample from empirical distribution with replacement
        # Each row is one simulated path of daily returns
        sampled_returns = rng.choice(
            clean_returns,
            size=(n_simulations, horizon_days),
            replace=True,
        )

        # If GARCH forecast available, scale returns to reflect current vol
        if garch_vol_forecast is not None:
            historical_vol_annual = clean_returns.std() * np.sqrt(252)
            scaling_factor = garch_vol_forecast / max(historical_vol_annual, 1e-6)
            # Scale returns but preserve sign
            sampled_returns = sampled_returns * scaling_factor

    else:
        # Parametric GBM
        mu = clean_returns.mean() * 252
        sigma = (garch_vol_forecast / np.sqrt(252)
                 if garch_vol_forecast else clean_returns.std())

        dt = 1 / 252
        z = rng.standard_normal((n_simulations, horizon_days))
        sampled_returns = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z

    # ---- Compute cumulative price paths ----
    # Shape: (n_simulations, horizon_days)
    cumulative_log_returns = np.cumsum(sampled_returns, axis=1)
    price_paths = current_price * np.exp(cumulative_log_returns)

    # Final prices at horizon
    final_prices = price_paths[:, -1]
    final_returns = (final_prices - current_price) / current_price

    # ---- Compute statistics ----
    percentiles = np.percentile(final_prices, [5, 25, 50, 75, 95])

    var_95 = float(np.percentile(final_returns, 5))  # 5th percentile return
    var_99 = float(np.percentile(final_returns, 1))
    # CVaR: expected loss given we're in the tail
    cvar_95 = float(final_returns[final_returns <= var_95].mean())

    # Sample paths for visualisation
    path_indices = rng.choice(n_simulations, size=min(n_sample_paths, n_simulations), replace=False)
    sample_paths = [
        [round(float(p), 4) for p in price_paths[i]]
        for i in path_indices
    ]

    result = SimulationResult(
        horizon_days=horizon_days,
        n_simulations=n_simulations,
        initial_price=current_price,
        p5=round(float(percentiles[0]), 4),
        p25=round(float(percentiles[1]), 4),
        p50=round(float(percentiles[2]), 4),
        p75=round(float(percentiles[3]), 4),
        p95=round(float(percentiles[4]), 4),
        expected_return_pct=round(float(final_returns.mean() * 100), 3),
        prob_positive_return=round(float((final_returns > 0).mean()), 4),
        prob_10pct_loss=round(float((final_returns < -0.10).mean()), 4),
        prob_20pct_loss=round(float((final_returns < -0.20).mean()), 4),
        var_95_pct=round(float(abs(var_95) * 100), 3),
        var_99_pct=round(float(abs(var_99) * 100), 3),
        cvar_95_pct=round(float(abs(cvar_95) * 100), 3),
        sample_paths=sample_paths,
    )

    log.info(
        "Monte Carlo complete",
        n=n_simulations,
        horizon=horizon_days,
        expected_return_pct=result.expected_return_pct,
        prob_positive=result.prob_positive_return,
        var_95=result.var_95_pct,
    )

    return result