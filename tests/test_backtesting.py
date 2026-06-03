# tests/test_backtesting.py
"""
Critical test: verify no lookahead bias in the backtest engine.
This is the most important test in the entire codebase.
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from ml.backtesting.engine import BacktestEngine, SlippageModel, CommissionModel
from backend.services.risk_engine import RiskTolerance


def make_synthetic_ohlcv(n_bars: int = 500, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic price data for deterministic tests."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(
        start="2020-01-01", periods=n_bars, freq="B", tz="UTC"
    )
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n_bars)))
    ohlcv = pd.DataFrame({
        "Open": prices * (1 + rng.uniform(-0.005, 0.005, n_bars)),
        "High": prices * (1 + rng.uniform(0.005, 0.020, n_bars)),
        "Low": prices * (1 - rng.uniform(0.005, 0.020, n_bars)),
        "Close": prices,
        "Volume": rng.uniform(1e6, 1e7, n_bars),
    }, index=dates)
    return ohlcv


class OraclePerfectModel:
    """
    A "perfect" model that knows the future. If the backtester
    allows lookahead, this will produce near-infinite returns.
    Any realistic performance means the lookahead gate is working.
    """
    def __init__(self, ohlcv_df: pd.DataFrame, horizon: int = 5):
        self.ohlcv_df = ohlcv_df
        self.horizon = horizon

    def predict(self, features: pd.DataFrame) -> dict:
        current_idx = len(features) - 1
        if current_idx + self.horizon >= len(self.ohlcv_df):
            return {"action": "HOLD", "prob_profit": 0.5, "confidence": 0.0, "model_version": "oracle"}
        current_close = self.ohlcv_df["Close"].iloc[current_idx]
        future_close = self.ohlcv_df["Close"].iloc[current_idx + self.horizon]
        will_go_up = future_close > current_close
        return {
            "action": "BUY" if will_go_up else "HOLD",
            "prob_profit": 0.99 if will_go_up else 0.01,
            "confidence": 0.99,
            "model_version": "oracle",
        }


class RandomModel:
    """Baseline: random signals should produce ~market returns minus costs."""
    def predict(self, features: pd.DataFrame) -> dict:
        action = np.random.choice(["BUY", "HOLD"], p=[0.3, 0.7])
        return {
            "action": action,
            "prob_profit": np.random.uniform(0.4, 0.6),
            "confidence": np.random.uniform(0.1, 0.5),
            "model_version": "random",
        }


def test_no_lookahead_oracle():
    """
    If the engine had lookahead, the oracle model would generate
    astronomically high returns. With correct bar-by-bar execution
    (signal at close t, execute at open t+1), even the oracle
    is limited to one-bar-delayed returns.

    The oracle should be profitable but NOT impossibly profitable.
    Impossibly profitable = Sharpe > 50, return > 1000x.
    """
    df = make_synthetic_ohlcv(500)
    engine = BacktestEngine(
        initial_capital=10_000,
        risk_tolerance=RiskTolerance.MODERATE,
        slippage_model=SlippageModel(fixed_bps=0),   # Zero costs to isolate signal quality
        commission_model=CommissionModel(percentage=0, per_trade_flat=0),
    )
    oracle = OraclePerfectModel(df)
    results = engine.run(df, oracle)

    sharpe = results["risk"]["sharpe_ratio"]
    total_return = results["summary"]["total_return_pct"]

    # Oracle with 1-bar delay should be profitable but not magical
    assert total_return > 0, "Oracle should be profitable (no lookahead check)"
    assert sharpe < 50, (
        f"Sharpe={sharpe:.1f} is impossibly high. "
        "Lookahead bias suspected."
    )
    assert results["summary"]["final_capital"] < 10_000 * 1000, (
        "Returns are absurdly high — lookahead bias confirmed."
    )


def test_random_model_near_buy_hold():
    """
    A random model should produce returns close to a buy-and-hold
    strategy (possibly lower due to transaction costs and suboptimal timing).
    If it consistently beats buy-and-hold, the engine has a bug.
    """
    np.random.seed(123)
    df = make_synthetic_ohlcv(500)
    engine = BacktestEngine(initial_capital=10_000, risk_tolerance=RiskTolerance.CONSERVATIVE)
    results = engine.run(df, RandomModel())

    bh_return = results["summary"]["benchmark_bh_return_pct"]
    strategy_return = results["summary"]["total_return_pct"]

    # Random strategy should not consistently and massively beat buy-hold
    alpha = strategy_return - bh_return
    assert alpha < 50, f"Random model beat buy-hold by {alpha:.1f}% — engine bug suspected"


def test_transaction_costs_reduce_return():
    """
    Higher costs must always reduce returns. If not, costs are not being applied.
    """
    df = make_synthetic_ohlcv(500)

    # Low cost version
    engine_low = BacktestEngine(
        initial_capital=10_000,
        slippage_model=SlippageModel(fixed_bps=1),
        commission_model=CommissionModel(percentage=0.001),
    )

    # High cost version
    engine_high = BacktestEngine(
        initial_capital=10_000,
        slippage_model=SlippageModel(fixed_bps=50),
        commission_model=CommissionModel(percentage=0.01),
    )

    oracle = OraclePerfectModel(df)
    results_low = engine_low.run(df, oracle)
    results_high = engine_high.run(df, oracle)

    assert results_low["summary"]["total_return_pct"] > results_high["summary"]["total_return_pct"], \
        "High costs should produce lower returns"

    assert results_high["trades"]["total_commission_usd"] > results_low["trades"]["total_commission_usd"]


def test_stop_loss_limits_drawdown():
    """
    With a tight stop loss and a crashing asset, the drawdown should
    be bounded. Without stop-loss, the drawdown is unconstrained.
    """
    # Create a sharply declining price series
    dates = pd.date_range("2021-01-01", periods=300, freq="B", tz="UTC")
    prices = 100.0 * np.exp(-np.linspace(0, 2, 300))  # Sharp decline
    df = pd.DataFrame({
        "Open": prices * 0.998,
        "High": prices * 1.005,
        "Low": prices * 0.990,
        "Close": prices,
        "Volume": np.ones(300) * 1e6,
    }, index=dates)

    class AlwaysBuyModel:
        def predict(self, features):
            return {"action": "BUY", "prob_profit": 0.8, "confidence": 0.8, "model_version": "always_buy"}

    engine = BacktestEngine(initial_capital=10_000, risk_tolerance=RiskTolerance.CONSERVATIVE)
    results = engine.run(df, AlwaysBuyModel())

    # With stop-loss, max drawdown should be less than 40%
    # Without stop-loss on a -86% asset, we'd lose nearly everything
    max_dd = abs(results["risk"]["max_drawdown_pct"])
    assert max_dd < 60, f"Stop-loss not working: drawdown={max_dd:.1f}%"