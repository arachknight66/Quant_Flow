import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum
import structlog

log = structlog.get_logger()

class RiskTolerance(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"

@dataclass
class RiskParameters:
    risk_tolerance: RiskTolerance
    max_position_pct: float
    max_portfolio_risk_pct: float
    kelly_fraction: float

RISK_PROFILES = {
    RiskTolerance.CONSERVATIVE: RiskParameters(RiskTolerance.CONSERVATIVE, 0.05, 0.01, 0.25),
    RiskTolerance.MODERATE:     RiskParameters(RiskTolerance.MODERATE,     0.10, 0.02, 0.25),
    RiskTolerance.AGGRESSIVE:   RiskParameters(RiskTolerance.AGGRESSIVE,   0.20, 0.03, 0.30),
}

class RiskEngine:
    def compute_kelly_fraction(self, win_probability: float, avg_win_pct: float, avg_loss_pct: float) -> float:
        if avg_loss_pct <= 0:
            return 0.0
        b = avg_win_pct / avg_loss_pct
        kelly = (b * win_probability - (1 - win_probability)) / b
        return max(0.0, min(kelly, 1.0))

    def compute_position_size(self, capital: float, win_probability: float,
                               current_price: float, atr: float,
                               risk_tolerance: RiskTolerance,
                               avg_win_pct: float = 0.03, avg_loss_pct: float = 0.015,
                               confidence: float = 1.0) -> dict:
        params = RISK_PROFILES[risk_tolerance]
        kelly_full     = self.compute_kelly_fraction(win_probability, avg_win_pct, avg_loss_pct)
        kelly_position = capital * kelly_full * params.kelly_fraction
        stop_distance_pct = (atr * 2) / current_price if current_price > 0 else 0.02
        fixed_frac_position = (capital * params.max_portfolio_risk_pct / stop_distance_pct
                               if stop_distance_pct > 0 else capital * 0.01)
        max_position   = capital * params.max_position_pct
        raw_position   = min(kelly_position, fixed_frac_position, max_position)
        position_value = raw_position * (confidence ** 2)
        if position_value < 10:
            position_value = 0.0
        n_shares        = position_value / current_price if current_price > 0 else 0
        allocation_pct  = position_value / capital if capital > 0 else 0
        stop_loss_price   = current_price - 2 * atr
        take_profit_price = current_price + 3 * atr
        rr = ((take_profit_price - current_price) / (current_price - stop_loss_price)
              if current_price != stop_loss_price else 0)
        return {
            "position_value_usd": round(position_value, 2),
            "allocation_pct":     round(allocation_pct * 100, 2),
            "n_shares":           round(n_shares, 4),
            "stop_loss_price":    round(stop_loss_price, 4),
            "take_profit_price":  round(take_profit_price, 4),
            "risk_amount_usd":    round(capital * params.max_portfolio_risk_pct, 2),
            "risk_reward_ratio":  round(rr, 2),
            "kelly_fraction_full":    round(kelly_full, 4),
            "kelly_fraction_applied": round(kelly_full * params.kelly_fraction, 4),
            "confidence_scale_applied": round(confidence ** 2, 4),
            "method_values": {"kelly_position": kelly_position,
                              "fixed_frac_position": fixed_frac_position,
                              "max_position_cap": max_position},
        }

    def compute_var(self, returns: pd.Series, confidence_level: float = 0.95,
                    method: str = "historical") -> float:
        if len(returns) < 30:
            return 0.0
        if method == "historical":
            return abs(float(np.percentile(returns, (1 - confidence_level) * 100)))
        elif method == "parametric":
            from scipy import stats
            z = stats.norm.ppf(1 - confidence_level)
            return abs(float(returns.mean() + z * returns.std()))
        raise ValueError(f"Unknown VaR method: {method}")

    def compute_max_drawdown(self, equity_curve: pd.Series) -> dict:
        rolling_max = equity_curve.cummax()
        drawdown    = (equity_curve - rolling_max) / rolling_max
        max_dd      = float(drawdown.min())
        max_dd_date = drawdown.idxmin()
        peak_date   = equity_curve[:max_dd_date].idxmax()
        post_trough = equity_curve[max_dd_date:]
        recovered   = post_trough[post_trough >= equity_curve[peak_date]]
        recovery_date = recovered.index[0] if len(recovered) > 0 else None
        return {
            "max_drawdown_pct": round(max_dd * 100, 2),
            "peak_date":        str(peak_date),
            "trough_date":      str(max_dd_date),
            "recovery_date":    str(recovery_date) if recovery_date else "Not recovered",
            "duration_days":    (max_dd_date - peak_date).days if peak_date else None,
            "recovery_days":    (recovery_date - max_dd_date).days if recovery_date else None,
        }
