#!/usr/bin/env python3
"""
Quick sanity check — run this after installing dependencies to confirm
the platform is working correctly before attempting model training.

Usage:
    python scripts/quick_verify.py

Takes ~10 seconds. Runs no network calls and needs no DB.
"""
import sys, os, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "verify-script-key-at-least-32-chars-xx")
os.environ.setdefault("POSTGRES_PASSWORD", "unused")
os.environ.setdefault("DEBUG", "true")

import numpy as np
import pandas as pd

PASSED = FAILED = 0

def check(name: str, ok: bool, detail: str = ""):
    global PASSED, FAILED
    PASSED += ok
    FAILED += not ok
    icon = "✅" if ok else "❌"
    line = f"  {icon}  {name}"
    if detail: line += f"  ({detail})"
    print(line)

print("=" * 58)
print("  QuantPlatform — quick verification")
print("=" * 58)

# 1. Imports
print("\n[1] Imports")
for module, symbol in [
    ("ml.features.technical_indicators", "build_feature_matrix"),
    ("ml.backtesting.engine",            "BacktestEngine"),
    ("ml.models.xgboost_model",          "XGBoostSignalModel"),
    ("backend.services.risk_engine",     "RiskEngine"),
    ("data_pipeline.collectors.base",    "OHLCVRecord"),
    ("shared.schemas.signal",            "SignalResponse"),
]:
    try:
        mod = __import__(module, fromlist=[symbol])
        assert hasattr(mod, symbol)
        check(module, True)
    except Exception as e:
        check(module, False, str(e))

# 2. Feature pipeline
print("\n[2] Feature pipeline")
from ml.features.technical_indicators import build_feature_matrix
rng = np.random.default_rng(0)
n = 400
dates = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
prices = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
df = pd.DataFrame({
    "Open": prices*0.999, "High": prices*1.01,
    "Low": prices*0.99, "Close": prices,
    "Volume": rng.uniform(1e7, 5e7, n)
}, index=dates)
features = build_feature_matrix(df, drop_na=True)
check("56+ features computed",       features.shape[1] >= 50, f"got {features.shape[1]}")
check("zero NaN rows",               features.isnull().any(axis=1).sum() == 0)
check("RSI in [0, 100]",             (features["rsi"].dropna().between(0,100)).all())
check("ATR > 0",                     (features["atr"].dropna() > 0).all())

# 3. No-lookahead
t = 200
ft = build_feature_matrix(df.iloc[:t+1], drop_na=False).iloc[-1]
ff = build_feature_matrix(df.iloc[:t+20], drop_na=False).iloc[t]
drift = [c for c in ft.index if c in ff.index
         and c not in ["Open","High","Low","Close","Volume"]
         and pd.notna(ft[c]) and pd.notna(ff[c])
         and abs(float(ft[c])-float(ff[c])) > 1e-7]
check("zero lookahead at bar 200",   len(drift) == 0, f"drift cols: {drift}")

# 4. Risk engine
print("\n[3] Risk engine")
from backend.services.risk_engine import RiskEngine, RiskTolerance
re = RiskEngine()
check("Kelly=0 for negative edge",   re.compute_kelly_fraction(0.30, 0.03, 0.015) == 0.0)
sz = re.compute_position_size(10000, 0.65, 150.0, 3.0, RiskTolerance.MODERATE)
check("position value > 0",          sz["position_value_usd"] > 0)
check("stop < price < take_profit",  sz["stop_loss_price"] < 150.0 < sz["take_profit_price"])
sz0= re.compute_position_size(10000, 0.30, 100.0, 2.0, RiskTolerance.MODERATE)
check("zero position for neg edge",  sz0["position_value_usd"] == 0.0)

# 5. Mini backtest
print("\n[4] Backtest engine")
from ml.backtesting.engine import BacktestEngine, SlippageModel, CommissionModel
class ConstBuy:
    def predict(self, f): return {"action":"BUY","prob_profit":0.65,"confidence":0.7,"model_version":"t"}
engine = BacktestEngine(5000, RiskTolerance.CONSERVATIVE,
                        SlippageModel(fixed_bps=5), CommissionModel(percentage=0.001))
res = engine.run(df, ConstBuy())
check("backtest runs without error",  res["summary"]["final_capital"] > 0)
check("trades generated",             res["trades"]["total_trades"] > 0)
check("bars_held in [1,20]",          all(0 < t["bars_held"] <= 20
                                         for t in res["trade_log"][:5]))
check("slippage > 0",                 res["trades"]["total_slippage_usd"] > 0)

# 6. OHLCVRecord validation
print("\n[5] Data validation")
from data_pipeline.collectors.base import OHLCVRecord
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
try: OHLCVRecord("X","1d",now,100,90,95,92,1e6); check("High<Low rejected", False)
except ValueError:                                check("High<Low rejected", True)
try: OHLCVRecord("X","1d",now,100,105,95,-1,1e6); check("neg close rejected", False)
except ValueError:                                 check("neg close rejected", True)

# 7. Auth
print("\n[6] Auth service")
from backend.services.auth_service import AuthService
from fastapi import HTTPException
auth = AuthService()
tok = auth.create_access_token("u1", "t@t.com")
pay = auth.decode_token(tok)
check("JWT create→decode",            pay["sub"] == "u1" and pay["type"] == "access")
try: auth.decode_token(tok + "x"); check("tampered token rejected", False)
except HTTPException as e:            check("tampered token rejected", e.status_code == 401)

# Summary
print()
print("=" * 58)
total = PASSED + FAILED
print(f"  {PASSED}/{total} checks passed  —  "
      f"{'✅ ALL GOOD — ready to train' if FAILED == 0 else f'❌ {FAILED} issue(s) found'}")
print("=" * 58)
if FAILED == 0:
    print()
    print("  Next step:")
    print("    python scripts/train_model.py --symbol AAPL --years 5")
sys.exit(0 if FAILED == 0 else 1)
