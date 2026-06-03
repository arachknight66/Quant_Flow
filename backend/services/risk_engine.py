# backend/services/risk_engine.py
"""
Position sizing and risk calculations.

This module is more important than the ML model.
A bad ML model with good risk management loses slowly.
A good ML model with bad risk management can blow up fast.

Core principle: Never allocate more than you can afford to lose.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum
import structlog

log = structlog.get_logger()


class RiskTolerance(str, Enum):
    CONSERVATIVE = "conservative"   # 1-2% risk per trade
    MODERATE = "moderate"           # 2-3% risk per trade
    AGGRESSIVE = "aggressive"       # 3-5% risk per trade


@dataclass
class RiskParameters:
    risk_tolerance: RiskTolerance
    max_position_pct: float      # Max single position as % of portfolio
    max_portfolio_risk_pct: float # Max total portfolio at risk
    kelly_fraction: float         # Fraction of full Kelly to use (0.25 = quarter-Kelly)


RISK_PROFILES = {
    RiskTolerance.CONSERVATIVE: RiskParameters(
        risk_tolerance=RiskTolerance.CONSERVATIVE,
        max_position_pct=0.05,      # 5% max position
        max_portfolio_risk_pct=0.01, # 1% portfolio risk per trade
        kelly_fraction=0.25,
    ),
    RiskTolerance.MODERATE: RiskParameters(
        risk_tolerance=RiskTolerance.MODERATE,
        max_position_pct=0.10,
        max_portfolio_risk_pct=0.02,
        kelly_fraction=0.25,        # Still quarter-Kelly — be humble
    ),
    RiskTolerance.AGGRESSIVE: RiskParameters(
        risk_tolerance=RiskTolerance.AGGRESSIVE,
        max_position_pct=0.20,
        max_portfolio_risk_pct=0.03,
        kelly_fraction=0.30,
    ),
}


class RiskEngine:
    """
    Computes position sizes and risk metrics.

    Mathematical foundations:
    - Kelly Criterion for optimal sizing
    - ATR-based stop-loss placement
    - VaR for downside quantification
    - Portfolio-level risk controls
    """

    def compute_kelly_fraction(
        self,
        win_probability: float,
        avg_win_pct: float,
        avg_loss_pct: float,
    ) -> float:
        """
        Kelly Criterion: f* = (b×p - q) / b
        where:
            b = avg_win / avg_loss (payoff ratio)
            p = win probability
            q = 1 - p (loss probability)

        Returns fraction of capital to deploy.

        Critical limitations:
        1. Assumes p, avg_win, avg_loss are known exactly (they're not!)
        2. Maximises long-run geometric growth but assumes infinite time horizon
        3. Even small errors in p can cause severe drawdown
        4. Always use fractional Kelly (25-50%) to account for estimation error
        """
        if avg_loss_pct <= 0:
            log.warning("avg_loss_pct must be positive, returning 0")
            return 0.0

        b = avg_win_pct / avg_loss_pct  # Payoff ratio
        q = 1 - win_probability

        kelly = (b * win_probability - q) / b

        # Cap at reasonable maximum
        kelly = max(0.0, min(kelly, 1.0))

        return kelly

    def compute_position_size(
        self,
        capital: float,
        win_probability: float,
        current_price: float,
        atr: float,
        risk_tolerance: RiskTolerance,
        avg_win_pct: float = 0.03,   # Estimated from backtest
        avg_loss_pct: float = 0.015, # Estimated from backtest (with stop)
        confidence: float = 1.0,     # Model confidence score [0,1]
    ) -> dict:
        """
        Compute position size using multiple methods and take the minimum.

        Methods:
        1. Kelly Criterion (fractional)
        2. Fixed fractional (% of portfolio at risk)
        3. ATR-based volatility sizing
        4. Confidence scaling

        Taking the minimum of all methods provides a conservative floor.

        Args:
            capital: Total available capital in USD
            win_probability: Calibrated probability from ML model [0, 1]
            current_price: Current asset price
            atr: Average True Range of the asset
            risk_tolerance: User's risk profile
            avg_win_pct: Expected average winning trade return
            avg_loss_pct: Expected average losing trade return (absolute)
            confidence: Model confidence [0, 1]

        Returns:
            dict with position_value, n_shares, allocation_pct, stop_loss_price, reasoning
        """
        params = RISK_PROFILES[risk_tolerance]

        reasoning = {}

        # ---- Method 1: Kelly Criterion ----
        kelly_full = self.compute_kelly_fraction(win_probability, avg_win_pct, avg_loss_pct)
        kelly_fraction = kelly_full * params.kelly_fraction  # Apply fractional Kelly
        kelly_position = capital * kelly_fraction
        reasoning["kelly_fraction"] = kelly_fraction
        reasoning["kelly_position"] = kelly_position

        # ---- Method 2: Fixed fractional risk ----
        # Risk per trade = params.max_portfolio_risk_pct × capital
        # Position size = risk / (stop_loss_distance_as_pct_of_price)
        stop_distance_pct = (atr * 2) / current_price  # 2-ATR stop
        if stop_distance_pct > 0:
            fixed_frac_position = (capital * params.max_portfolio_risk_pct) / stop_distance_pct
        else:
            fixed_frac_position = capital * 0.01  # Fallback: 1% of capital
        reasoning["fixed_frac_position"] = fixed_frac_position
        reasoning["stop_distance_pct"] = stop_distance_pct

        # ---- Method 3: Max position constraint ----
        max_position = capital * params.max_position_pct
        reasoning["max_position_cap"] = max_position

        # ---- Take the minimum (most conservative) ----
        raw_position = min(kelly_position, fixed_frac_position, max_position)

        # ---- Scale by model confidence ----
        # If confidence is 0.5 (model barely above random), reduce position
        # If confidence is 1.0, use full computed size
        # Sigmoid scaling so low confidence positions become very small
        confidence_scale = (confidence ** 2)  # Quadratic penalty for low confidence
        position_value = raw_position * confidence_scale

        # Floor: never invest less than $10 (impractical)
        if position_value < 10:
            position_value = 0.0  # Don't bother

        # ---- Compute derived values ----
        n_shares = position_value / current_price if current_price > 0 else 0
        allocation_pct = position_value / capital if capital > 0 else 0

        # ---- Stop loss placement: 2-ATR below entry ----
        stop_loss_price = current_price - (2 * atr)
        take_profit_price = current_price + (3 * atr)  # 1.5:1 risk-reward minimum

        result = {
            "position_value_usd": round(position_value, 2),
            "allocation_pct": round(allocation_pct * 100, 2),
            "n_shares": round(n_shares, 4),
            "stop_loss_price": round(stop_loss_price, 4),
            "take_profit_price": round(take_profit_price, 4),
            "risk_amount_usd": round(capital * params.max_portfolio_risk_pct, 2),
            "risk_reward_ratio": round((take_profit_price - current_price) /
                                      (current_price - stop_loss_price), 2),
            "kelly_fraction_full": round(kelly_full, 4),
            "kelly_fraction_applied": round(kelly_fraction, 4),
            "confidence_scale_applied": round(confidence_scale, 4),
            "method_values": reasoning,
        }

        log.info(
            "Position size computed",
            allocation_pct=result["allocation_pct"],
            risk_reward=result["risk_reward_ratio"],
            win_prob=win_probability,
        )

        return result

    def compute_var(
        self,
        returns: pd.Series,
        confidence_level: float = 0.95,
        method: str = "historical",
    ) -> float:
        """
        Value at Risk — maximum expected loss over time horizon
        at the given confidence level.

        Methods:
        - historical: Non-parametric, uses actual return distribution
          Advantage: captures fat tails and non-normality
          Disadvantage: backward-looking, may miss new volatility regimes
        - parametric: Assumes normal distribution
          Advantage: simple, uses just mean and std
          Disadvantage: underestimates tail risk (real returns are fat-tailed)

        For financial risk: ALWAYS prefer historical VaR.
        Normal VaR is dangerously misleading for tail events.

        Returns the loss amount as a POSITIVE number.
        """
        if len(returns) < 30:
            log.warning("Insufficient data for reliable VaR", n=len(returns))
            return 0.0

        if method == "historical":
            var = float(np.percentile(returns, (1 - confidence_level) * 100))
            return abs(var)  # Return as positive loss amount
        elif method == "parametric":
            from scipy import stats
            z = stats.norm.ppf(1 - confidence_level)
            var = returns.mean() + z * returns.std()
            return abs(var)
        else:
            raise ValueError(f"Unknown VaR method: {method}")

    def compute_max_drawdown(self, equity_curve: pd.Series) -> dict:
        """
        Maximum Drawdown: largest peak-to-trough decline.

        MDD = (Peak Value - Trough Value) / Peak Value

        Also computes:
        - Duration: how long the drawdown lasted
        - Recovery: how long to recover (if recovered)
        """
        rolling_max = equity_curve.cummax()
        drawdown = (equity_curve - rolling_max) / rolling_max

        max_dd = float(drawdown.min())
        max_dd_date = drawdown.idxmin()

        # Find peak before max drawdown
        peak_date = equity_curve[:max_dd_date].idxmax()

        # Find recovery (if any)
        post_trough = equity_curve[max_dd_date:]
        recovered = post_trough[post_trough >= equity_curve[peak_date]]
        recovery_date = recovered.index[0] if len(recovered) > 0 else None

        duration_days = (max_dd_date - peak_date).days if peak_date else None
        recovery_days = (recovery_date - max_dd_date).days if recovery_date else None

        return {
            "max_drawdown_pct": round(max_dd * 100, 2),
            "peak_date": str(peak_date),
            "trough_date": str(max_dd_date),
            "recovery_date": str(recovery_date) if recovery_date else "Not recovered",
            "duration_days": duration_days,
            "recovery_days": recovery_days,
        }