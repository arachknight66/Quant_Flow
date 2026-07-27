import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger()

class SignalStacker:
    """
    Ensemble stacker combining XGBoost directional signals with GARCH volatility scaling
    and HMM regime multipliers.
    """
    def __init__(self, xgb_model, garch_model, hmm_detector):
        self.xgb   = xgb_model
        self.garch = garch_model
        self.hmm   = hmm_detector

    def predict(self, features: pd.DataFrame, close: pd.Series) -> dict:
        base = self.xgb.predict(features)
        lr   = np.log(close / close.shift(1)).dropna()

        regime_mult = 1.0
        try:
            regime = self.hmm.predict_current_regime(lr)
            regime_mult = regime.get("position_size_multiplier", 1.0)  # 1.0/0.6/0.3
        except Exception as e:
            log.warning("Regime multiplier evaluation failed", error=str(e))

        vol_scale = 1.0
        try:
            daily_vol = self.garch.forecast_1day_vol(lr) / np.sqrt(252)
            vol_scale = min(1.0, 0.015 / max(daily_vol, 0.001))
        except Exception as e:
            log.warning("Vol scale evaluation failed", error=str(e))

        blended = base["prob_profit"] * regime_mult * vol_scale
        blended = float(max(0.0, min(1.0, blended)))
        action  = "BUY" if blended > 0.60 else "SELL" if blended < 0.40 else "HOLD"

        return {
            **base,
            "prob_profit": blended,
            "action": action,
            "regime_mult": float(regime_mult),
            "vol_scale": float(vol_scale),
            "model_version": f"ensemble_{base.get('model_version', 'v1.0')}"
        }
