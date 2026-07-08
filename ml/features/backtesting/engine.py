import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
import structlog
from ml.features.technical_indicators import build_feature_matrix, IndicatorConfig
from backend.services.risk_engine import RiskEngine, RiskTolerance

log = structlog.get_logger()

class WalkForwardSplitter:
    def __init__(self, n_splits=5, test_size=63, gap=5, min_train_size=252):
        self.n_splits = n_splits
        self.test_size = test_size
        self.gap = gap
        self.min_train_size = min_train_size

    def split(self, X: pd.DataFrame):
        n = len(X)
        splits = []
        for i in range(self.n_splits):
            test_end   = n - i * self.test_size
            test_start = test_end - self.test_size
            train_end  = test_start - self.gap
            if train_end < self.min_train_size:
                continue
            splits.append((np.arange(0, train_end), np.arange(test_start, test_end)))
        return reversed(splits)

@dataclass
class SlippageModel:
    fixed_bps: float = 5.0
    vol_multiplier: float = 0.1
    volume_impact: float = 0.0

    def compute(self, price: float, atr: float, direction: int) -> float:
        return price + direction * (price * self.fixed_bps / 10_000 + atr * self.vol_multiplier)

    def cost(self, price: float, atr: float) -> float:
        return price * self.fixed_bps / 10_000 + atr * self.vol_multiplier

@dataclass
class CommissionModel:
    per_trade_flat: float = 0.0
    percentage: float = 0.001
    min_commission: float = 0.01

    def compute(self, trade_value: float) -> float:
        return max(self.per_trade_flat + trade_value * self.percentage, self.min_commission)

@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: str
    entry_price: float
    exit_price: float
    shares: float
    position_value: float
    pnl_gross: float
    pnl_net: float
    slippage_cost: float
    commission_cost: float
    entry_signal_prob: float
    exit_reason: str
    bars_held: int

@dataclass
class PortfolioState:
    cash: float
    equity: float = 0.0
    total_value: float = 0.0
    position_shares: float = 0.0
    position_entry_price: float = 0.0
    position_entry_time: Optional[pd.Timestamp] = None
    position_direction: Optional[str] = None
    position_entry_prob: float = 0.0
    position_entry_atr: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    bar_idx_at_entry: int = 0

    def has_position(self) -> bool:
        return self.position_shares != 0.0

    def update_equity(self, current_price: float):
        self.equity      = self.position_shares * current_price
        self.total_value = self.cash + self.equity

class BacktestEngine:
    def __init__(self, initial_capital=100_000.0,
                 risk_tolerance=RiskTolerance.MODERATE,
                 slippage_model=None, commission_model=None,
                 prediction_horizon=5, warmup_bars=252, max_hold_bars=20,
                 benchmark_col="Close"):
        self.initial_capital   = initial_capital
        self.risk_tolerance    = risk_tolerance
        self.slippage          = slippage_model or SlippageModel()
        self.commission        = commission_model or CommissionModel()
        self.prediction_horizon = prediction_horizon
        self.warmup_bars       = warmup_bars
        self.max_hold_bars     = max_hold_bars
        self.risk_engine       = RiskEngine()
        self._reset()

    def _reset(self):
        self.portfolio   = PortfolioState(cash=self.initial_capital)
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []
        self.signal_log: list[dict]   = []
        self._peak_equity: float = self.initial_capital

    def run(self, ohlcv_df: pd.DataFrame, model, indicator_config=None) -> dict:
        self._reset()
        if len(ohlcv_df) < self.warmup_bars + self.prediction_horizon + 10:
            raise ValueError(f"Insufficient data: need at least "
                             f"{self.warmup_bars + self.prediction_horizon + 10} bars, "
                             f"got {len(ohlcv_df)}")
        log.info("Starting backtest", bars=len(ohlcv_df), capital=self.initial_capital)
        features = build_feature_matrix(ohlcv_df, indicator_config, drop_na=False)

        for i in range(self.warmup_bars, len(ohlcv_df) - 1):
            bar_time      = ohlcv_df.index[i]
            next_bar_open = ohlcv_df["Open"].iloc[i + 1]
            current_close = ohlcv_df["Close"].iloc[i]
            current_atr   = features["atr"].iloc[i] if "atr" in features else current_close * 0.02

            self.portfolio.update_equity(current_close)
            if self.portfolio.total_value > self._peak_equity:
                self._peak_equity = self.portfolio.total_value

            self.equity_curve.append({
                "timestamp": bar_time, "total_value": self.portfolio.total_value,
                "cash": self.portfolio.cash, "equity": self.portfolio.equity,
                "drawdown": self._compute_running_drawdown(),
            })

            if self.portfolio.has_position():
                exit_reason = self._check_exit_conditions(current_close, i)
                if exit_reason:
                    self._execute_exit(next_bar_open, ohlcv_df.index[i + 1],
                                       exit_reason, current_atr, i)
                    continue

            current_features = features.iloc[[i]]
            if current_features.isnull().any().any():
                continue
            try:
                signal = model.predict(features.iloc[:i+1])
            except Exception as e:
                log.warning("Model prediction failed", bar=str(bar_time), error=str(e))
                continue

            self.signal_log.append({"timestamp": bar_time, **signal})

            if not self.portfolio.has_position() and signal["action"] == "BUY":
                sizing = self.risk_engine.compute_position_size(
                    capital=self.portfolio.total_value,
                    win_probability=signal["prob_profit"],
                    current_price=current_close, atr=current_atr,
                    risk_tolerance=self.risk_tolerance, confidence=signal["confidence"],
                )
                if sizing["position_value_usd"] > 10:
                    self._execute_entry(next_bar_open, ohlcv_df.index[i + 1],
                                        sizing["position_value_usd"],
                                        sizing["stop_loss_price"], sizing["take_profit_price"],
                                        current_atr, signal["prob_profit"], i)

        if self.portfolio.has_position():
            final_close = ohlcv_df["Close"].iloc[-1]
            final_atr   = features["atr"].iloc[-1] if "atr" in features else final_close * 0.02
            self._execute_exit(final_close, ohlcv_df.index[-1], "end_of_data",
                               final_atr, len(ohlcv_df) - 1)

        return self._compile_results(ohlcv_df)

    def _check_exit_conditions(self, current_close: float, current_bar_idx: int) -> Optional[str]:
        if self.portfolio.position_direction == "long":
            if current_close <= self.portfolio.stop_loss_price:   return "stop_loss"
            if current_close >= self.portfolio.take_profit_price: return "take_profit"
        if current_bar_idx - self.portfolio.bar_idx_at_entry >= self.max_hold_bars:
            return "max_hold_expired"
        return None

    def _execute_entry(self, entry_price_raw, entry_time, position_value,
                       stop_loss, take_profit, atr, signal_prob, bar_idx):
        entry_price = self.slippage.compute(entry_price_raw, atr, direction=+1)
        commission  = self.commission.compute(position_value)
        shares = (position_value - commission) / entry_price
        if shares * entry_price > self.portfolio.cash:
            shares = (self.portfolio.cash * 0.99 - commission) / entry_price
        if shares <= 0: return
        self.portfolio.cash -= shares * entry_price + commission
        self.portfolio.position_shares       = shares
        self.portfolio.position_entry_price  = entry_price
        self.portfolio.position_entry_time   = entry_time
        self.portfolio.position_direction    = "long"
        self.portfolio.position_entry_prob   = signal_prob
        self.portfolio.position_entry_atr    = atr
        self.portfolio.stop_loss_price       = stop_loss
        self.portfolio.take_profit_price     = take_profit
        self.portfolio.bar_idx_at_entry      = bar_idx

    def _execute_exit(self, exit_price_raw, exit_time, exit_reason, atr, current_bar_idx):
        if not self.portfolio.has_position(): return
        exit_price   = self.slippage.compute(exit_price_raw, atr, direction=-1)
        commission   = self.commission.compute(self.portfolio.position_shares * exit_price)
        entry_commission = self.commission.compute(
            self.portfolio.position_shares * self.portfolio.position_entry_price)
        self.portfolio.cash += self.portfolio.position_shares * exit_price - commission
        pnl_gross    = ((exit_price - self.portfolio.position_entry_price)
                        * self.portfolio.position_shares)
        pnl_net      = pnl_gross - commission - entry_commission
        # FIX: both entry and exit slippage legs captured
        slippage_cost = ((self.slippage.cost(self.portfolio.position_entry_price,
                                              self.portfolio.position_entry_atr)
                         + self.slippage.cost(exit_price_raw, atr))
                        * self.portfolio.position_shares)
        # FIX: bars_held = difference, not entry index
        bars_held = current_bar_idx - self.portfolio.bar_idx_at_entry

        self.trades.append(Trade(
            entry_time=self.portfolio.position_entry_time, exit_time=exit_time,
            direction="long", entry_price=self.portfolio.position_entry_price,
            exit_price=exit_price, shares=self.portfolio.position_shares,
            position_value=self.portfolio.position_shares * self.portfolio.position_entry_price,
            pnl_gross=pnl_gross, pnl_net=pnl_net, slippage_cost=slippage_cost,
            commission_cost=commission + entry_commission,
            entry_signal_prob=self.portfolio.position_entry_prob,
            exit_reason=exit_reason, bars_held=bars_held,
        ))
        self.portfolio.position_shares = 0.0
        self.portfolio.position_entry_price = 0.0
        self.portfolio.position_entry_time  = None
        self.portfolio.position_direction   = None
        self.portfolio.position_entry_atr   = 0.0
        self.portfolio.stop_loss_price      = 0.0
        self.portfolio.take_profit_price    = 0.0
        self.portfolio.bar_idx_at_entry     = 0

    def _compute_running_drawdown(self) -> float:
        # FIX: O(1) using running peak, not max() over equity_curve list
        if self._peak_equity <= 0: return 0.0
        return (self.portfolio.total_value - self._peak_equity) / self._peak_equity

    def _compile_results(self, ohlcv_df: pd.DataFrame) -> dict:
        equity_series = pd.Series(
            [e["total_value"] for e in self.equity_curve],
            index=[e["timestamp"] for e in self.equity_curve],
        )
        total_return = (equity_series.iloc[-1] - self.initial_capital) / self.initial_capital
        n_years = (equity_series.index[-1] - equity_series.index[0]).days / 365.25
        cagr    = (1 + total_return) ** (1 / max(n_years, 0.001)) - 1 if n_years > 0 else 0.0
        bh_return = ((ohlcv_df["Close"].iloc[-1] - ohlcv_df["Close"].iloc[self.warmup_bars])
                     / ohlcv_df["Close"].iloc[self.warmup_bars])
        daily_returns = equity_series.pct_change().dropna()
        annual_factor = np.sqrt(252)
        sharpe = float((daily_returns.mean() * 252) / (daily_returns.std() * annual_factor)
                       ) if daily_returns.std() > 0 else 0.0
        downside = daily_returns[daily_returns < 0]
        sortino  = float((daily_returns.mean() * 252) / (downside.std() * annual_factor)
                         ) if len(downside) > 0 and downside.std() > 0 else 0.0
        dd_result = self.risk_engine.compute_max_drawdown(equity_series)
        max_dd    = dd_result["max_drawdown_pct"]
        calmar    = cagr / abs(max_dd / 100) if max_dd != 0 else 0.0
        n_trades  = len(self.trades)
        if n_trades == 0:
            win_rate = avg_win = avg_loss = profit_factor = avg_hold_bars = 0.0
            total_commission = total_slippage = 0.0
        else:
            winning = [t for t in self.trades if t.pnl_net > 0]
            losing  = [t for t in self.trades if t.pnl_net <= 0]
            win_rate = len(winning) / n_trades
            avg_win  = float(np.mean([t.pnl_net for t in winning])) if winning else 0.0
            avg_loss = float(np.mean([t.pnl_net for t in losing]))  if losing  else 0.0
            gross_profit = sum(t.pnl_net for t in winning)
            gross_loss   = abs(sum(t.pnl_net for t in losing))
            profit_factor   = gross_profit / gross_loss if gross_loss > 0 else float("inf")
            avg_hold_bars   = float(np.mean([t.bars_held for t in self.trades]))
            total_commission = sum(t.commission_cost for t in self.trades)
            total_slippage   = sum(t.slippage_cost   for t in self.trades)

        is_viable = sharpe > 0.5 and win_rate > 0.45 and max_dd > -30

        return {
            "summary": {
                "initial_capital": self.initial_capital,
                "final_capital":   round(float(equity_series.iloc[-1]), 2),
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
                "annualised_volatility_pct": round(daily_returns.std() * annual_factor * 100, 2),
            },
            "trades": {
                "total_trades": n_trades,
                "win_rate_pct": round(win_rate * 100, 2),
                "avg_win_usd":  round(avg_win, 2),
                "avg_loss_usd": round(avg_loss, 2),
                "profit_factor": round(profit_factor, 3),
                "avg_hold_bars": round(avg_hold_bars, 1),
                "total_commission_usd": round(total_commission, 2),
                "total_slippage_usd":   round(total_slippage, 2),
                "cost_drag_pct": round(
                    (total_commission + total_slippage) / self.initial_capital * 100, 3),
            },
            "equity_curve": [
                {"t": str(e["timestamp"]), "v": round(e["total_value"], 2),
                 "dd": round(e["drawdown"] * 100, 2)}
                for e in self.equity_curve
            ],
            "trade_log": [
                {"entry": str(t.entry_time), "exit": str(t.exit_time),
                 "entry_price": round(t.entry_price, 4), "exit_price": round(t.exit_price, 4),
                 "pnl_net": round(t.pnl_net, 2), "exit_reason": t.exit_reason,
                 "entry_prob": round(t.entry_signal_prob, 3), "bars_held": t.bars_held}
                for t in self.trades
            ],
            "assessment": {
                "is_viable": is_viable,
                "warnings": self._generate_warnings(
                    sharpe, win_rate, max_dd, n_trades, total_commission, total_return, bh_return),
            },
        }

    def _generate_warnings(self, sharpe, win_rate, max_dd, n_trades,
                           total_commission, total_return, bh_return) -> list[str]:
        warnings = []
        if sharpe < 0.3:
            warnings.append("Sharpe ratio below 0.3: risk-adjusted return is poor.")
        if win_rate < 0.40:
            warnings.append(f"Win rate {win_rate:.0%} is low.")
        if abs(max_dd) > 25:
            warnings.append(f"Max drawdown {max_dd:.1f}% is severe.")
        if n_trades < 30:
            warnings.append(f"Only {n_trades} trades — results not statistically meaningful.")
        if total_return < bh_return:
            warnings.append(f"Strategy underperformed buy-and-hold.")
        warnings.append("IMPORTANT: Past backtest performance does not predict future results. "
                        "Market regimes change. This is not financial advice.")
        return warnings
