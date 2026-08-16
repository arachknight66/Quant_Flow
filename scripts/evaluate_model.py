#!/usr/bin/env python3
"""
Load a saved model and run a fresh out-of-sample backtest.

Usage:
    python scripts/evaluate_model.py --symbol AAPL --start 2022-01-01 --end 2024-01-01
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


def print_probability_calibration(df, model, signal_log):
    """Compute and print reliability/calibration table in deciles."""
    print("\n" + "="*64)
    print("  PROBABILITY CALIBRATION REPORT (RELIABILITY TABLE)")
    print("="*64)
    
    if not signal_log:
        print("  No model predictions logged during the backtest.")
        print("="*64)
        return
        
    horizon = getattr(model, "prediction_horizon", 5)
    threshold = getattr(model, "profit_threshold", 0.01)
    
    # Compute actual realized target over the horizon
    close = df["Close"]
    future_return = close.shift(-horizon) / close - 1
    realized_target = (future_return > threshold).astype(int)
    realized_target.iloc[-horizon:] = -1  # mask out recent bars with unknown future
    
    # Align predictions with realized targets
    records = []
    for log_entry in signal_log:
        ts = log_entry["timestamp"]
        prob = log_entry["prob_profit"]
        
        # Find matching target by timestamp
        if ts in realized_target.index:
            target_val = realized_target.loc[ts]
            if target_val != -1:
                records.append({"prob": prob, "target": target_val})
                
    if not records:
        print("  No aligned predictions and targets found.")
        print("="*64)
        return
        
    df_cal = pd.DataFrame(records)
    
    bins = np.linspace(0.0, 1.0, 11)
    df_cal["bin"] = pd.cut(df_cal["prob"], bins=bins, labels=[f"{int(bins[i]*100)}-{int(bins[i+1]*100)}%" for i in range(10)])
    
    grouped = df_cal.groupby("bin")
    
    print(f"  Target: Return > {threshold*100:.1f}% in {horizon} bars")
    print()
    print(f"  {'Probability Bin':<17} {'N Samples':>10} {'Expected Win%':>15} {'Actual Win%':>15} {'Deviation':>12}")
    print(f"  {'-'*17} {'-'*10} {'-'*15} {'-'*15} {'-'*12}")
    
    miscalibrated = False
    for bin_name, group in grouped:
        n_samples = len(group)
        if n_samples == 0:
            continue
            
        actual_win_rate = group["target"].mean()
        # Expected probability is the mean of predicted probabilities in this bin
        expected_prob = group["prob"].mean()
        deviation = actual_win_rate - expected_prob
        
        if abs(deviation) > 0.15:
            miscalibrated = True
            dev_str = f"[!] {deviation*100:>+7.1f}%"
        else:
            dev_str = f"    {deviation*100:>+8.1f}%"
            
        print(f"  {bin_name:<17} {n_samples:>10} {expected_prob*100:>14.1f}% {actual_win_rate*100:>14.1f}% {dev_str}")
        
    print()
    if miscalibrated:
        print("  [!] WARNING: Miscalibration detected (>15% deviation in some bins).")
        print("     Model probabilities are not fully aligned with realized outcomes.")
        print("     Lower downstream Kelly position sizing multiplier to manage risk.")
    else:
        print("  [OK] Probability calibration is stable (<15% deviation across bins).")
    print("="*64)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",    default="AAPL")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--start",     default="2022-01-01")
    parser.add_argument("--end",       default="2024-01-01")
    parser.add_argument("--capital",   default=10000.0, type=float)
    parser.add_argument("--slippage",  default=10.0, type=float,
                        help="Slippage in basis points (10bps = 0.10%)")
    parser.add_argument("--commission",default=0.1, type=float,
                        help="Commission % per trade (0.1 = 0.10%)")
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
    print(f"\nFetching {symbol} data {args.start} -> {args.end}...")
    df = yf.download(symbol, start=args.start, end=args.end,
                     interval=args.timeframe, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    print(f"  {len(df)} bars")

    if len(df) < 100:
        print("❌ Need at least 100 bars for a backtest")
        sys.exit(1)

    # Run backtest
    from ml.backtesting.engine import BacktestEngine, SlippageModel, CommissionModel
    from backend.services.risk_engine import RiskTolerance

    # Set warmup bars dynamically if data size is small
    warmup = min(252, len(df) // 4)
    engine = BacktestEngine(
        initial_capital=args.capital,
        risk_tolerance=RiskTolerance.MODERATE,
        slippage_model=SlippageModel(fixed_bps=args.slippage),
        commission_model=CommissionModel(percentage=args.commission / 100),
        warmup_bars=warmup
    )

    print(f"\nRunning backtest (slippage={args.slippage}bps, "
          f"commission={args.commission}%)...")
    
    # Enable Step 2/3 features for evaluation
    from ml.features.technical_indicators import IndicatorConfig
    best_config = IndicatorConfig(enable_long_memory=True, enable_vol_price=True)
    results = engine.run(df, model, best_config)

    # Print report
    s = results["summary"]
    r = results["risk"]
    t = results["trades"]

    print()
    print("=" * 64)
    print("  BACKTEST RESULTS")
    print("=" * 64)
    print(f"  Period:           {args.start} -> {args.end}")
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
            rows[row] += "#"
        print("  Equity curve:")
        print(f"  ${mx:>8,.0f} |", end="")
        for row_idx, row in enumerate(rows):
            prefix = "  " + " " * 10 + "|" if row_idx > 0 else ""
            print(prefix + row)
        print(f"  ${mn:>8,.0f} |")
        print()

    # Warnings
    for w in results["assessment"]["warnings"]:
        print(f"  [!] {w}")

    # Calibration check
    print_probability_calibration(df, model, engine.signal_log)

    print()
    verdict = results["assessment"]["is_viable"]
    print(f"  OVERALL VERDICT: {'[OK] VIABLE - proceed to paper trading' if verdict else '[X] NOT VIABLE - review warnings'}")
    print("=" * 64)


if __name__ == "__main__":
    main()
