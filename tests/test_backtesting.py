# tests/test_backtesting.py
"""
Critical test: verify no lookahead bias in the backtest engine.
This is the most important test in the entire codebase.
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from ml.backtesting.engine import BacktestEngine, SlippageModel, CommissionModel
from backend.services.risk_engine import RiskTolerance


def make_synthetic_ohlcv(n_bars: int = 500, seed: int = 42) -> pd.DataFrame:
    rng   = np.random.default_rng(seed)
    dates = pd.date_range(start="2020-01-01", periods=n_bars, freq="B", tz="UTC")
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n_bars)))
    return pd.DataFrame({
        "Open":   prices * (1 + rng.uniform(-0.005, 0.005, n_bars)),
        "High":   prices * (1 + rng.uniform(0.005, 0.020, n_bars)),
        "Low":    prices * (1 - rng.uniform(0.005, 0.020, n_bars)),
        "Close":  prices,
        "Volume": rng.uniform(1e6, 1e7, n_bars),
    }, index=dates)


class OraclePerfectModel:
    """Knows the future — catastrophically profitable if lookahead exists."""
    def __init__(self, ohlcv_df: pd.DataFrame, horizon: int = 5):
        self.ohlcv_df = ohlcv_df
        self.horizon  = horizon

    def predict(self, features: pd.DataFrame) -> dict:
        i = len(features) - 1
        if i + self.horizon >= len(self.ohlcv_df):
            return {"action": "HOLD", "prob_profit": 0.5,
                    "confidence": 0.0, "model_version": "oracle"}
        up = self.ohlcv_df["Close"].iloc[i + self.horizon] > self.ohlcv_df["Close"].iloc[i]
        return {"action": "BUY" if up else "HOLD",
                "prob_profit": 0.99 if up else 0.01,
                "confidence": 0.99, "model_version": "oracle"}


class RandomModel:
    def predict(self, features: pd.DataFrame) -> dict:
        action = np.random.choice(["BUY", "HOLD"], p=[0.3, 0.7])
        return {"action": action,
                "prob_profit": np.random.uniform(0.4, 0.6),
                "confidence":  np.random.uniform(0.1, 0.5),
                "model_version": "random"}


def test_no_lookahead_oracle():
    """Oracle with 1-bar delay: profitable but NOT impossibly so."""
    df = make_synthetic_ohlcv(500)
    engine = BacktestEngine(
        initial_capital=10_000,
        risk_tolerance=RiskTolerance.MODERATE,
        slippage_model=SlippageModel(fixed_bps=0),
        commission_model=CommissionModel(percentage=0, per_trade_flat=0),
    )
    results = engine.run(df, OraclePerfectModel(df))
    sharpe = results["risk"]["sharpe_ratio"]
    total_return = results["summary"]["total_return_pct"]

    assert total_return > 0,  "Oracle should be profitable"
    assert sharpe < 50,       f"Sharpe={sharpe:.1f} is impossibly high — lookahead suspected"
    assert results["summary"]["final_capital"] < 10_000 * 1000,         "Returns absurdly high — lookahead confirmed"


def test_bars_held_in_valid_range():
    """bars_held must be [1, max_hold_bars] — not the entry bar index."""
    df = make_synthetic_ohlcv(500)
    engine = BacktestEngine(initial_capital=10_000, max_hold_bars=20)
    results = engine.run(df, OraclePerfectModel(df))
    for trade in results["trade_log"]:
        assert 0 < trade["bars_held"] <= 20,             f"bars_held={trade['bars_held']} out of [1,20]"


def test_transaction_costs_reduce_return():
    """Higher costs must always reduce returns."""
    df = make_synthetic_ohlcv(500)
    engine_low  = BacktestEngine(10_000,
        slippage_model=SlippageModel(fixed_bps=1),
        commission_model=CommissionModel(percentage=0.001))
    engine_high = BacktestEngine(10_000,
        slippage_model=SlippageModel(fixed_bps=50),
        commission_model=CommissionModel(percentage=0.01))
    oracle = OraclePerfectModel(df)
    r_low  = engine_low.run(df, oracle)["summary"]["total_return_pct"]
    r_high = engine_high.run(df, oracle)["summary"]["total_return_pct"]
    assert r_low > r_high, "High costs should produce lower returns"


def test_slippage_cost_captures_both_legs():
    """Slippage must be non-zero and reflect both entry and exit."""
    df = make_synthetic_ohlcv(500)
    engine = BacktestEngine(10_000,
        slippage_model=SlippageModel(fixed_bps=20),
        commission_model=CommissionModel(percentage=0))
    results = engine.run(df, OraclePerfectModel(df))
    assert results["trades"]["total_slippage_usd"] > 0,         "Non-zero slippage expected when fixed_bps > 0"


def test_stop_loss_limits_drawdown():
    """With a tight stop loss and crashing asset, drawdown is bounded."""
    dates  = pd.date_range("2021-01-01", periods=300, freq="B", tz="UTC")
    prices = 100.0 * np.exp(-np.linspace(0, 2, 300))
    df = pd.DataFrame({
        "Open": prices * 0.998, "High": prices * 1.005,
        "Low":  prices * 0.990, "Close": prices,
        "Volume": np.ones(300) * 1e6,
    }, index=dates)

    class AlwaysBuy:
        def predict(self, f):
            return {"action":"BUY","prob_profit":0.8,"confidence":0.8,"model_version":"ab"}

    engine = BacktestEngine(10_000, risk_tolerance=RiskTolerance.CONSERVATIVE)
    results = engine.run(df, AlwaysBuy())
    max_dd = abs(results["risk"]["max_drawdown_pct"])
    assert max_dd < 60, f"Stop-loss not working: drawdown={max_dd:.1f}%"


def test_random_model_near_buy_hold():
    """Random model alpha vs buy-and-hold should be < 50pp."""
    np.random.seed(123)
    df = make_synthetic_ohlcv(500)
    engine = BacktestEngine(10_000, risk_tolerance=RiskTolerance.CONSERVATIVE)
    results = engine.run(df, RandomModel())
    alpha = (results["summary"]["total_return_pct"] -
             results["summary"]["benchmark_bh_return_pct"])
    assert alpha < 50, f"Random model beat B&H by {alpha:.1f}% — engine bug"
