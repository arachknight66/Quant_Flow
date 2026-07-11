#!/usr/bin/env python3
"""
Load a saved model and run a fresh out-of-sample backtest.

Usage:
    python scripts/evaluate_model.py --symbol AAPL --start 2022-01-01 --end 2024-01-01

Prints:
  - Full backtest performance report
  - Equity curve summary
  - Comparison vs buy-and-hold
  - Honest warnings

This is step 2 after train_model.py confirms AUC > 0.53.
"""
import argparse, sys, os, warnings, json
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "eval-script-key")
os.environ.setdefault("POSTGRES_PASSWORD", "unused")
os.environ.setdefault("DEBUG", "true")

import numpy as np
import pandas as pd
import yfinance as yf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",    default="AAPL")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--start",     default="2022-01-01")
    parser.add_argument("--end",       default="2024-01-01")
    parser.add_argument("--capital",   default=10000.0, type=float)
    parser.add_argument("--slippage",  default=10.0, type=float,
                        help="Slippage in basis points (10bps = 0.10%%)")
    parser.add_argument("--commission",default=0.1, type=float,
                        help="Commission %% per trade (0.1 = 0.10%%)")
    parser.add_argument("--artifacts", default="./ml/artifacts")
    args = parser.parse_args()

    symbol = args.symbol.upper()

    # Load model
    from ml.models.xgboost_model import XGBoostSignalModel
    model_path = Path(args.artifacts) / symbol / args.timeframe
    if not (model_path / "metadata.json").exists():
        print(f"❌ No model found at {model_path}")
        print(f"   Run: python scripts/train_model.py --symbol {symbol} first")
        sys.exit(1)

    model = XGBoostSignalModel.load(str(model_path))
    meta  = json.loads((model_path / "metadata.json").read_text())
    print(f"\nLoaded: {meta['version']}")
    print(f"  Trained at:  {meta['trained_at']}")
    print(f"  Features:    {len(meta['feature_names'])}")
    wf_folds = meta.get("walk_forward_metrics", [])
    if wf_folds:
        mean_auc = sum(f["roc_auc"] for f in wf_folds) / len(wf_folds)
        print(f"  WF AUC:      {mean_auc:.4f}")

    # Fetch evaluation data
    print(f"\nFetching {symbol} data {args.start} → {args.end}...")
    df = yf.download(symbol, start=args.start, end=args.end,
                     interval=args.timeframe, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    print(f"  {len(df)} bars")

    if len(df) < 300:
        print("❌ Need at least 300 bars for a meaningful backtest")
        sys.exit(1)

    # Run backtest
    from ml.backtesting.engine import BacktestEngine, SlippageModel, CommissionModel
    from backend.services.risk_engine import RiskTolerance

    engine = BacktestEngine(
        initial_capital=args.capital,
        risk_tolerance=RiskTolerance.MODERATE,
        slippage_model=SlippageModel(fixed_bps=args.slippage),
        commission_model=CommissionModel(percentage=args.commission / 100),
    )

    print(f"\nRunning backtest (slippage={args.slippage}bps, "
          f"commission={args.commission}%)...")
    results = engine.run(df, model)

    # Print report
    s = results["summary"]
    r = results["risk"]
    t = results["trades"]

    print()
    print("=" * 64)
    print("  BACKTEST RESULTS")
    print("=" * 64)
    print(f"  Period:           {args.start} → {args.end}")
    print(f"  Initial capital:  ${s['initial_capital']:>10,.2f}")
    print(f"  Final capital:    ${s['final_capital']:>10,.2f}")
    print()
    print(f"  Total return:     {s['total_return_pct']:>+8.2f}%")
    print(f"  Buy-and-hold:     {s['benchmark_bh_return_pct']:>+8.2f}%")
    print(f"  Alpha vs B&H:     {s['alpha_vs_bh_pct']:>+8.2f}pp")
    print(f"  CAGR:             {s['cagr_pct']:>+8.2f}%")
    print()
    print(f"  Sharpe ratio:     {r['sharpe_ratio']:>8.3f}  (>1.0 = good)")
    print(f"  Sortino ratio:    {r['sortino_ratio']:>8.3f}")
    print(f"  Calmar ratio:     {r['calmar_ratio']:>8.3f}")
    print(f"  Max drawdown:     {r['max_drawdown_pct']:>8.2f}%")
    print(f"  Ann. volatility:  {r['annualised_volatility_pct']:>8.2f}%")
    print()
    print(f"  Total trades:     {t['total_trades']:>8}")
    print(f"  Win rate:         {t['win_rate_pct']:>8.2f}%")
    print(f"  Avg win:          ${t['avg_win_usd']:>9,.2f}")
    print(f"  Avg loss:         ${t['avg_loss_usd']:>9,.2f}")
    print(f"  Profit factor:    {t['profit_factor']:>8.3f}  (>1.5 = good)")
    print(f"  Avg hold (bars):  {t['avg_hold_bars']:>8.1f}")
    print(f"  Commission cost:  ${t['total_commission_usd']:>9,.2f}")
    print(f"  Slippage cost:    ${t['total_slippage_usd']:>9,.2f}")
    print(f"  Cost drag:        {t['cost_drag_pct']:>8.3f}%  of initial capital")
    print()

    # Equity curve mini-chart (ASCII)
    eq = [e["v"] for e in results["equity_curve"]]
    if eq:
        mn, mx = min(eq), max(eq)
        rng = mx - mn if mx != mn else 1
        WIDTH, HEIGHT = 60, 8
        rows = [""] * HEIGHT
        for i, v in enumerate(eq):
            col = int((i / len(eq)) * WIDTH)
            row = int(((v - mn) / rng) * (HEIGHT - 1))
            row = HEIGHT - 1 - row
            while len(rows[row]) < col:
                rows[row] += " "
            rows[row] += "█"
        print("  Equity curve:")
        print(f"  ${mx:>8,.0f} ┤", end="")
        for row_idx, row in enumerate(rows):
            prefix = "  " + " " * 10 + "│" if row_idx > 0 else ""
            print(prefix + row)
        print(f"  ${mn:>8,.0f} ┤")
        print()

    # Warnings
    for w in results["assessment"]["warnings"]:
        print(f"  ⚠️  {w}")

    print()
    verdict = results["assessment"]["is_viable"]
    print(f"  OVERALL VERDICT: {'✅ VIABLE — proceed to paper trading' if verdict else '❌ NOT VIABLE — review warnings'}")
    print("=" * 64)


if __name__ == "__main__":
    main()
