# ml/backtesting/engine.py
"""
Professional event-driven backtesting engine.

CRITICAL DESIGN PRINCIPLES:

1. BAR-BY-BAR execution: At each timestep t, we only have access to
   data[0:t]. The model's prediction at t uses features computed from
   data[0:t-1] (to simulate real-world delay: you compute signals at
   close of bar t, execute at open of bar t+1).

2. EXECUTION REALISM:
   - Signals fire at bar close
   - Orders execute at NEXT bar's open (not the signal bar's close)
   - Slippage is applied to the execution price
   - Commission is charged on every round trip
   - Partial fills are not modelled (simplification for now)

3. POSITION SIZING: Kelly-based, ATR-adjusted, confidence-scaled
   — never "buy everything."

4. NO PEEKING: A common subtle bug is using `.shift(-n)` for targets
   during feature creation within the backtest loop. This creates
   lookahead. Targets are only used for training, never at inference.

PHASE 2.0/2.1 FIXES APPLIED:
- WalkForwardSplitter is now canonically defined HERE (not duplicated
  in ml/models/xgboost_model.py). Other modules (ensemble/stacker.py,
  xgboost_model.py) import it from this file.
- Trade.bars_held now correctly computed as
  current_bar_idx - bar_idx_at_entry, instead of being set to the
  entry index itself (the original bug).
- slippage_cost now accounts for BOTH the entry leg and the exit leg,
  instead of only approximating the entry leg.
- Running drawdown is tracked via a single float (self._peak_equity)
  updated incrementally each bar, instead of calling max() over the
  entire equity_curve list every bar (was O(n) per bar -> O(n^2) total).
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import structlog

from ml.features.technical_indicators import build_feature_matrix, IndicatorConfig
from backend.services.risk_engine import RiskEngine, RiskTolerance

log = structlog.get_logger()


class WalkForwardSplitter:
    """
    Time-series cross-validation that respects temporal ordering.

    CANONICAL LOCATION: this class previously had a near-duplicate
    definition in ml/models/xgboost_model.py. That duplication meant
    ml/models/ensemble/stacker.py's
        from ml.backtesting.engine import WalkForwardSplitter
    raised ImportError, since the class didn't actually live here yet.
    This is now the single source of truth — xgboost_model.py imports
    it from this module instead of redefining it.

    Parameters:
        n_splits: Number of train/test folds
        test_size: Number of samples in each test set
        gap: Samples to skip between train and test (prevents leakage)
        min_train_size: Minimum samples needed for first training fold
    """

    def __init__(
        self,
        n_splits: int = 5,
        test_size: int = 63,       # ~3 months of trading days
        gap: int = 5,              # 1 week gap to prevent leakage
        min_train_size: int = 252, # 1 year minimum training data
    ):
        self.n_splits = n_splits
        self.test_size = test_size
        self.gap = gap
        self.min_train_size = min_train_size

    def split(self, X: pd.DataFrame):
        """
        Yields (train_indices, test_indices) tuples.

        The key invariant: ALL training indices < ALL test indices.
        No future data ever appears in training.
        """
        n = len(X)
        splits = []

        for i in range(self.n_splits):
            # Test window: work backwards from end of data
            test_end = n - i * self.test_size
            test_start = test_end - self.test_size
            train_end = test_start - self.gap

            if train_end < self.min_train_size:
                log.warning(f"Skipping fold {i}: insufficient training data")
                continue

            train_indices = np.arange(0, train_end)
            test_indices = np.arange(test_start, test_end)
            splits.append((train_indices, test_indices))

        return reversed(splits)  # Chronological order


@dataclass
class SlippageModel:
    """
    Models the difference between expected and actual execution price.

    Three components:
    1. Fixed slippage: A fixed basis-point cost per trade (e.g. bid/ask spread)
    2. Volatility-proportional: Higher volatility → larger slippage
    3. Volume-proportional: Larger orders relative to daily volume → more impact

    For retail backtesting, fixed_bps=5 (0.05%) is a reasonable floor.
    For larger positions, volume impact becomes significant.
    """
    fixed_bps: float = 5.0        # Basis points (1 bp = 0.01%)
    vol_multiplier: float = 0.1   # Fraction of ATR added as slippage
    volume_impact: float = 0.0    # For now, ignore market impact

    def compute(
        self,
        price: float,
        atr: float,
        direction: int,  # +1 for buy, -1 for sell
    ) -> float:
        """
        Returns the execution price after slippage.
        Slippage always works against you:
          - Buy: execution_price > signal_price
          - Sell: execution_price < signal_price
        """
        fixed_cost = price * (self.fixed_bps / 10_000)
        vol_cost = atr * self.vol_multiplier
        total_slippage = fixed_cost + vol_cost
        return price + direction * total_slippage

    def cost(self, price: float, atr: float) -> float:
        """
        Returns just the per-share slippage COST (always positive),
        independent of direction. Used for cost-accounting on a trade,
        as opposed to compute() which returns the adjusted execution price.
        """
        fixed_cost = price * (self.fixed_bps / 10_000)
        vol_cost = atr * self.vol_multiplier
        return fixed_cost + vol_cost


@dataclass
class CommissionModel:
    """
    Brokerage commission model.

    Per-trade flat fee + percentage-based fee.
    Zerodha: Rs 20 flat or 0.03% (equities), zero for delivery.
    Interactive Brokers: $0.005/share, min $1.
    US retail (free): $0 commission but PFOF creates hidden spread costs.

    For backtesting: use 0.1% round-trip as a conservative estimate
    that covers commission + spread + implicit costs.
    """
    per_trade_flat: float = 0.0          # Flat fee per trade in currency
    percentage: float = 0.001            # 0.1% per trade (one-way)
    min_commission: float = 0.01

    def compute(self, trade_value: float) -> float:
        commission = max(
            self.per_trade_flat + trade_value * self.percentage,
            self.min_commission
        )
        return commission


@dataclass
class Trade:
    """Records a completed round-trip trade."""
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: str              # "long" or "short"
    entry_price: float
    exit_price: float
    shares: float
    position_value: float
    pnl_gross: float            # Before costs
    pnl_net: float              # After slippage and commission
    slippage_cost: float
    commission_cost: float
    entry_signal_prob: float    # Model's probability at entry
    exit_reason: str            # "signal", "stop_loss", "take_profit", "end_of_data"
    bars_held: int


@dataclass
class PortfolioState:
    """Mutable portfolio state, updated each bar."""
    cash: float
    equity: float = 0.0
    total_value: float = 0.0
    position_shares: float = 0.0
    position_entry_price: float = 0.0
    position_entry_time: Optional[pd.Timestamp] = None
    position_direction: Optional[str] = None
    position_entry_prob: float = 0.0
    position_entry_atr: float = 0.0   # FIX: needed to compute entry-leg slippage cost at exit time
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    bar_idx_at_entry: int = 0

    def has_position(self) -> bool:
        return self.position_shares != 0.0

    def update_equity(self, current_price: float):
        self.equity = self.position_shares * current_price
        self.total_value = self.cash + self.equity


class BacktestEngine:
    """
    Event-driven backtesting engine.

    Usage:
        engine = BacktestEngine(
            initial_capital=100_000,
            risk_tolerance=RiskTolerance.MODERATE,
        )
        results = engine.run(
            ohlcv_df=df,           # Historical OHLCV DataFrame
            model=trained_model,   # Trained XGBoostSignalModel
        )
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        risk_tolerance: RiskTolerance = RiskTolerance.MODERATE,
        slippage_model: Optional[SlippageModel] = None,
        commission_model: Optional[CommissionModel] = None,
        prediction_horizon: int = 5,
        warmup_bars: int = 252,    # Skip first N bars (indicator warmup)
        max_hold_bars: int = 20,   # Force-exit after N bars regardless
        benchmark_col: str = "Close",
    ):
        self.initial_capital = initial_capital
        self.risk_tolerance = risk_tolerance
        self.slippage = slippage_model or SlippageModel()
        self.commission = commission_model or CommissionModel()
        self.prediction_horizon = prediction_horizon
        self.warmup_bars = warmup_bars
        self.max_hold_bars = max_hold_bars
        self.risk_engine = RiskEngine()

        # State
        self._reset()

    def _reset(self):
        self.portfolio = PortfolioState(cash=self.initial_capital)
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []
        self.signal_log: list[dict] = []
        # FIX: track the running peak incrementally instead of recomputing
        # max(equity_curve) on every single bar (was O(n) per bar -> O(n^2)
        # total across a backtest). This is updated once per bar in run().
        self._peak_equity: float = self.initial_capital

    def run(
        self,
        ohlcv_df: pd.DataFrame,
        model,                      # XGBoostSignalModel or any model with .predict()
        indicator_config: Optional[IndicatorConfig] = None,
    ) -> dict:
        """
        Run the complete backtest.

        IMPORTANT: Features are computed on the FULL dataset first,
        then used bar-by-bar. This is valid because technical indicators
        are purely backward-looking by construction (they only use
        data up to and including the current bar).

        The model's predict() uses only the current row of features,
        which represents the state as of bar close. Execution happens
        at the NEXT bar's open — this is the critical timing detail.
        """
        self._reset()

        if len(ohlcv_df) < self.warmup_bars + self.prediction_horizon + 10:
            raise ValueError(
                f"Insufficient data: need at least "
                f"{self.warmup_bars + self.prediction_horizon + 10} bars, "
                f"got {len(ohlcv_df)}"
            )

        log.info(
            "Starting backtest",
            bars=len(ohlcv_df),
            capital=self.initial_capital,
            risk_tolerance=self.risk_tolerance,
        )

        # Compute features for the entire dataset (no leakage — all backward-looking)
        features = build_feature_matrix(ohlcv_df, indicator_config, drop_na=False)

        # Iterate bar by bar, starting after warmup
        for i in range(self.warmup_bars, len(ohlcv_df) - 1):
            bar_time = ohlcv_df.index[i]
            next_bar_open = ohlcv_df["Open"].iloc[i + 1]  # Execution price
            current_close = ohlcv_df["Close"].iloc[i]
            current_atr = features["atr"].iloc[i] if "atr" in features else current_close * 0.02

            # Update portfolio mark-to-market at current bar close
            self.portfolio.update_equity(current_close)

            # FIX: update running peak in O(1) instead of max() over the
            # whole history every bar.
            if self.portfolio.total_value > self._peak_equity:
                self._peak_equity = self.portfolio.total_value

            # Record equity curve
            self.equity_curve.append({
                "timestamp": bar_time,
                "total_value": self.portfolio.total_value,
                "cash": self.portfolio.cash,
                "equity": self.portfolio.equity,
                "drawdown": self._compute_running_drawdown(),
            })

            # ---- Check exit conditions for open position ----
            if self.portfolio.has_position():
                exit_reason = self._check_exit_conditions(
                    current_close=current_close,
                    current_bar_idx=i,
                )
                if exit_reason:
                    self._execute_exit(
                        exit_price_raw=next_bar_open,
                        exit_time=ohlcv_df.index[i + 1],
                        exit_reason=exit_reason,
                        atr=current_atr,
                        current_bar_idx=i,
                    )
                    continue  # Don't enter new position same bar as exit

            # ---- Generate signal ----
            # Only use features[0:i+1] — everything up to and including current bar
            current_features = features.iloc[[i]]

            if current_features.isnull().any().any():
                continue  # Skip bars with incomplete indicators

            try:
                signal = model.predict(features.iloc[:i+1])
            except Exception as e:
                log.warning("Model prediction failed", bar=str(bar_time), error=str(e))
                continue

            self.signal_log.append({
                "timestamp": bar_time,
                **signal,
            })

            # ---- Entry logic ----
            if not self.portfolio.has_position() and signal["action"] == "BUY":
                sizing = self.risk_engine.compute_position_size(
                    capital=self.portfolio.total_value,
                    win_probability=signal["prob_profit"],
                    current_price=current_close,
                    atr=current_atr,
                    risk_tolerance=self.risk_tolerance,
                    confidence=signal["confidence"],
                )

                if sizing["position_value_usd"] > 10:
                    self._execute_entry(
                        entry_price_raw=next_bar_open,
                        entry_time=ohlcv_df.index[i + 1],
                        position_value=sizing["position_value_usd"],
                        stop_loss=sizing["stop_loss_price"],
                        take_profit=sizing["take_profit_price"],
                        atr=current_atr,
                        signal_prob=signal["prob_profit"],
                        bar_idx=i,
                    )

        # Force-close any remaining position at end of data
        if self.portfolio.has_position():
            final_close = ohlcv_df["Close"].iloc[-1]
            final_atr = features["atr"].iloc[-1] if "atr" in features else final_close * 0.02
            self._execute_exit(
                exit_price_raw=final_close,
                exit_time=ohlcv_df.index[-1],
                exit_reason="end_of_data",
                atr=final_atr,
                current_bar_idx=len(ohlcv_df) - 1,
            )

        return self._compile_results(ohlcv_df)

    def _check_exit_conditions(
        self,
        current_close: float,
        current_bar_idx: int,
    ) -> Optional[str]:
        """
        Returns exit reason string if position should be closed, else None.
        Priority: stop_loss > take_profit > max_hold > signal
        """
        # Stop loss hit
        if (self.portfolio.position_direction == "long" and
                current_close <= self.portfolio.stop_loss_price):
            return "stop_loss"

        # Take profit hit
        if (self.portfolio.position_direction == "long" and
                current_close >= self.portfolio.take_profit_price):
            return "take_profit"

        # Max hold period
        bars_held = current_bar_idx - self.portfolio.bar_idx_at_entry
        if bars_held >= self.max_hold_bars:
            return "max_hold_expired"

        return None

    def _execute_entry(
        self,
        entry_price_raw: float,
        entry_time: pd.Timestamp,
        position_value: float,
        stop_loss: float,
        take_profit: float,
        atr: float,
        signal_prob: float,
        bar_idx: int,
    ):
        """Execute a long entry with slippage and commission."""
        # Apply slippage (buy at slightly higher than open)
        entry_price = self.slippage.compute(entry_price_raw, atr, direction=+1)

        # Compute shares
        commission = self.commission.compute(position_value)
        available_cash = position_value - commission
        shares = available_cash / entry_price

        if shares * entry_price > self.portfolio.cash:
            # Insufficient cash — size down
            shares = (self.portfolio.cash * 0.99 - commission) / entry_price

        if shares <= 0:
            return

        cost = shares * entry_price + commission
        self.portfolio.cash -= cost
        self.portfolio.position_shares = shares
        self.portfolio.position_entry_price = entry_price
        self.portfolio.position_entry_time = entry_time
        self.portfolio.position_direction = "long"
        self.portfolio.position_entry_prob = signal_prob
        self.portfolio.position_entry_atr = atr  # FIX: stash for exit-time slippage accounting
        self.portfolio.stop_loss_price = stop_loss
        self.portfolio.take_profit_price = take_profit
        self.portfolio.bar_idx_at_entry = bar_idx

    def _execute_exit(
        self,
        exit_price_raw: float,
        exit_time: pd.Timestamp,
        exit_reason: str,
        atr: float,
        current_bar_idx: int,
    ):
        """Execute exit with slippage, commission, and trade recording."""
        if not self.portfolio.has_position():
            return

        exit_price = self.slippage.compute(exit_price_raw, atr, direction=-1)
        commission = self.commission.compute(
            self.portfolio.position_shares * exit_price
        )

        proceeds = self.portfolio.position_shares * exit_price - commission
        self.portfolio.cash += proceeds

        pnl_gross = (exit_price - self.portfolio.position_entry_price) * self.portfolio.position_shares
        entry_commission = self.commission.compute(
            self.portfolio.position_shares * self.portfolio.position_entry_price
        )

        # FIX: slippage_cost previously only approximated the ENTRY leg
        # (and did so via a confusing backed-out formula). It silently
        # ignored the EXIT leg's slippage entirely, understating true
        # transaction costs on every trade. Now we use SlippageModel.cost()
        # directly for both legs, in per-share terms, scaled by shares.
        entry_slippage_per_share = self.slippage.cost(
            self.portfolio.position_entry_price, self.portfolio.position_entry_atr
        )
        exit_slippage_per_share = self.slippage.cost(exit_price_raw, atr)
        slippage_cost = (
            entry_slippage_per_share + exit_slippage_per_share
        ) * self.portfolio.position_shares

        pnl_net = pnl_gross - commission - entry_commission

        # FIX: bars_held was being set to self.portfolio.bar_idx_at_entry
        # (the ENTRY bar index itself) rather than the actual holding
        # period. Every trade log entry reported a nonsensical "bars held"
        # value (e.g. "held for bar 287" instead of "held for 6 bars").
        bars_held = current_bar_idx - self.portfolio.bar_idx_at_entry

        trade = Trade(
            entry_time=self.portfolio.position_entry_time,
            exit_time=exit_time,
            direction="long",
            entry_price=self.portfolio.position_entry_price,
            exit_price=exit_price,
            shares=self.portfolio.position_shares,
            position_value=self.portfolio.position_shares * self.portfolio.position_entry_price,
            pnl_gross=pnl_gross,
            pnl_net=pnl_net,
            slippage_cost=slippage_cost,
            commission_cost=commission + entry_commission,
            entry_signal_prob=self.portfolio.position_entry_prob,
            exit_reason=exit_reason,
            bars_held=bars_held,
        )
        self.trades.append(trade)

        # Reset position state
        self.portfolio.position_shares = 0.0
        self.portfolio.position_entry_price = 0.0
        self.portfolio.position_entry_time = None
        self.portfolio.position_direction = None
        self.portfolio.position_entry_atr = 0.0
        self.portfolio.stop_loss_price = 0.0
        self.portfolio.take_profit_price = 0.0
        self.portfolio.bar_idx_at_entry = 0

    def _compute_running_drawdown(self) -> float:
        """
        FIX: previously did
            peak = max(e["total_value"] for e in self.equity_curve)
        which re-scans the ENTIRE equity curve on every single bar —
        O(n) work per bar, O(n^2) total for an n-bar backtest. For a
        5-year daily backtest (~1250 bars) that's over 1.5M redundant
        comparisons. self._peak_equity is now maintained incrementally
        in run(), so this is O(1).
        """
        if self._peak_equity <= 0:
            return 0.0
        return (self.portfolio.total_value - self._peak_equity) / self._peak_equity

    def _compile_results(self, ohlcv_df: pd.DataFrame) -> dict:
        """
        Compile comprehensive performance metrics.
        These are the numbers that matter — not just return, but risk-adjusted return.
        """
        equity_series = pd.Series(
            [e["total_value"] for e in self.equity_curve],
            index=[e["timestamp"] for e in self.equity_curve],
        )

        # ---- Return metrics ----
        total_return = (equity_series.iloc[-1] - self.initial_capital) / self.initial_capital
        n_years = (equity_series.index[-1] - equity_series.index[0]).days / 365.25
        cagr = (1 + total_return) ** (1 / max(n_years, 0.001)) - 1 if n_years > 0 else 0.0

        # Benchmark: Buy and hold
        bh_return = (ohlcv_df["Close"].iloc[-1] - ohlcv_df["Close"].iloc[self.warmup_bars]) / \
                    ohlcv_df["Close"].iloc[self.warmup_bars]

        # ---- Risk metrics ----
        daily_returns = equity_series.pct_change().dropna()
        annual_factor = np.sqrt(252)

        sharpe = float(
            (daily_returns.mean() * 252) / (daily_returns.std() * annual_factor)
        ) if daily_returns.std() > 0 else 0.0

        downside = daily_returns[daily_returns < 0]
        sortino = float(
            (daily_returns.mean() * 252) / (downside.std() * annual_factor)
        ) if len(downside) > 0 and downside.std() > 0 else 0.0

        dd_result = self.risk_engine.compute_max_drawdown(equity_series)
        max_dd = dd_result["max_drawdown_pct"]

        calmar = cagr / abs(max_dd / 100) if max_dd != 0 else 0.0

        # ---- Trade metrics ----
        n_trades = len(self.trades)
        if n_trades == 0:
            win_rate = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            profit_factor = 0.0
            avg_hold_bars = 0.0
            total_commission = 0.0
            total_slippage = 0.0
        else:
            winning = [t for t in self.trades if t.pnl_net > 0]
            losing = [t for t in self.trades if t.pnl_net <= 0]
            win_rate = len(winning) / n_trades
            avg_win = np.mean([t.pnl_net for t in winning]) if winning else 0.0
            avg_loss = np.mean([t.pnl_net for t in losing]) if losing else 0.0
            gross_profit = sum(t.pnl_net for t in winning)
            gross_loss = abs(sum(t.pnl_net for t in losing))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
            avg_hold_bars = np.mean([t.bars_held for t in self.trades])
            total_commission = sum(t.commission_cost for t in self.trades)
            total_slippage = sum(t.slippage_cost for t in self.trades)

        # ---- Honest assessment ----
        is_viable = sharpe > 0.5 and win_rate > 0.45 and max_dd > -30

        results = {
            "summary": {
                "initial_capital": self.initial_capital,
                "final_capital": round(float(equity_series.iloc[-1]), 2),
                "total_return_pct": round(total_return * 100, 2),
                "cagr_pct": round(cagr * 100, 2),
                "benchmark_bh_return_pct": round(bh_return * 100, 2),
                "alpha_vs_bh_pct": round((total_return - bh_return) * 100, 2),
                "n_years": round(n_years, 2),
            },
            "risk": {
                "sharpe_ratio": round(sharpe, 3),
                "sortino_ratio": round(sortino, 3),
                "calmar_ratio": round(calmar, 3),
                "max_drawdown_pct": round(max_dd, 2),
                "max_drawdown_detail": dd_result,
                "annualised_volatility_pct": round(
                    daily_returns.std() * annual_factor * 100, 2
                ),
            },
            "trades": {
                "total_trades": n_trades,
                "win_rate_pct": round(win_rate * 100, 2),
                "avg_win_usd": round(avg_win, 2),
                "avg_loss_usd": round(avg_loss, 2),
                "profit_factor": round(profit_factor, 3),
                "avg_hold_bars": round(avg_hold_bars, 1),
                "total_commission_usd": round(total_commission, 2),
                "total_slippage_usd": round(total_slippage, 2),
                "cost_drag_pct": round(
                    (total_commission + total_slippage) / self.initial_capital * 100, 3
                ),
            },
            "equity_curve": [
                {"t": str(e["timestamp"]), "v": round(e["total_value"], 2),
                 "dd": round(e["drawdown"] * 100, 2)}
                for e in self.equity_curve
            ],
            "trade_log": [
                {
                    "entry": str(t.entry_time),
                    "exit": str(t.exit_time),
                    "entry_price": round(t.entry_price, 4),
                    "exit_price": round(t.exit_price, 4),
                    "pnl_net": round(t.pnl_net, 2),
                    "exit_reason": t.exit_reason,
                    "entry_prob": round(t.entry_signal_prob, 3),
                    "bars_held": t.bars_held,
                }
                for t in self.trades
            ],
            "assessment": {
                "is_viable": is_viable,
                "warnings": self._generate_warnings(
                    sharpe, win_rate, max_dd, n_trades, total_commission,
                    total_return, bh_return
                ),
            },
        }

        log.info(
            "Backtest complete",
            total_return_pct=results["summary"]["total_return_pct"],
            sharpe=results["risk"]["sharpe_ratio"],
            max_drawdown=results["risk"]["max_drawdown_pct"],
            n_trades=n_trades,
            win_rate=results["trades"]["win_rate_pct"],
        )

        return results

    def _generate_warnings(
        self,
        sharpe: float,
        win_rate: float,
        max_dd: float,
        n_trades: int,
        total_commission: float,
        total_return: float,
        bh_return: float,
    ) -> list[str]:
        """
        Generate honest warnings about backtest quality.
        These should be shown prominently in the UI.
        """
        warnings = []

        if sharpe < 0.3:
            warnings.append(
                "Sharpe ratio below 0.3: risk-adjusted return is poor. "
                "Not suitable for deployment."
            )
        if win_rate < 0.40:
            warnings.append(
                f"Win rate {win_rate:.0%} is low. Psychologically difficult "
                "to sustain — most traders abandon strategies during losing streaks."
            )
        if abs(max_dd) > 25:
            warnings.append(
                f"Max drawdown {max_dd:.1f}% is severe. "
                "Most investors would abandon the strategy before recovery."
            )
        if n_trades < 30:
            warnings.append(
                f"Only {n_trades} trades. Results not statistically meaningful "
                "— too few trades to distinguish skill from luck."
            )
        if total_commission / max(abs(total_return * self.initial_capital), 1) > 0.2:
            warnings.append(
                "Transaction costs represent >20% of gross profit. "
                "Strategy may be cost-inefficient."
            )
        if total_return < bh_return:
            warnings.append(
                f"Strategy underperformed buy-and-hold by "
                f"{(bh_return - total_return) * 100:.1f}%. "
                "The added complexity is not justified."
            )

        warnings.append(
            "IMPORTANT: Past backtest performance does not predict future results. "
            "Market regimes change. This is not financial advice."
        )

        return warnings