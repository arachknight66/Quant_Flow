#!/usr/bin/env python3
"""
Phase 2.4 — First honest model training script.

Usage (from repo root):
    python scripts/train_model.py --symbol AAPL --timeframe 1d --years 5

What this does:
  1. Fetches N years of daily OHLCV via yfinance
  2. Builds 56-feature matrix (no lookahead)
  3. Runs 5-fold walk-forward cross-validation
  4. Prints honest AUC / Brier / deployment verdict
  5. If AUC > 0.53: trains final model and saves to ml/artifacts/
  6. Prints the REAL numbers — no cherry-picking

HONEST EXPECTATIONS:
  AUC < 0.52  → pure noise, do not deploy (common result)
  AUC 0.52-0.55 → marginal edge, very sensitive to costs
  AUC 0.55-0.60 → modest edge, may survive realistic costs
  AUC > 0.60  → strong edge (rare, verify no data leakage)

If your first run gives AUC < 0.53, that is normal and expected.
The correct response is to improve features (add GARCH vol, HMM
regime, sentiment), not to lower the threshold.
"""
import argparse
import sys
import os
import json
import warnings
from pathlib import Path
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "training-script-key-not-for-production")
os.environ.setdefault("POSTGRES_PASSWORD", "unused-for-training")
os.environ.setdefault("DEBUG", "true")

import numpy as np
import pandas as pd
import yfinance as yf


def fetch_data(symbol: str, years: int) -> pd.DataFrame:
    """Fetch OHLCV data directly via yfinance (no DB needed for training)."""
    print(f"\nFetching {years}yr {symbol} daily data...")
    df = yf.download(
        symbol,
        period=f"{years}y",
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        raise ValueError(f"No data returned for {symbol}")

    # yfinance returns MultiIndex columns for single ticker in some versions
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    print(f"  Fetched {len(df)} bars  "
          f"({df.index[0].strftime('%Y-%m-%d')} -> {df.index[-1].strftime('%Y-%m-%d')})")
    return df


def run_walk_forward(df: pd.DataFrame, symbol: str, n_splits: int = 5, tune: bool = False, indicator_config = None, prune_correlation=False, prune_importance_pct=0.0) -> dict:
    """Run walk-forward validation and return honest metrics."""
    from ml.features.technical_indicators import build_feature_matrix
    from ml.models.xgboost_model import XGBoostSignalModel

    print(f"\nBuilding feature matrix...")
    features = build_feature_matrix(df, config=indicator_config, drop_na=False, symbol=symbol)
    print(f"  Features: {features.shape[1]} columns, {features.shape[0]} rows")

    best_params = {}
    if tune:
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            
            def objective(trial):
                params = {
                    "max_depth": trial.suggest_int("max_depth", 3, 6),
                    "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
                    "subsample": trial.suggest_float("subsample", 0.6, 1.0),
                    "n_estimators": trial.suggest_int("n_estimators", 100, 500),
                    "min_child_weight": trial.suggest_int("min_child_weight", 5, 50),
                }
                m = XGBoostSignalModel(
                    prediction_horizon=5, profit_threshold=0.01, model_params=params,
                    prune_correlation=prune_correlation, prune_importance_pct=prune_importance_pct
                )
                res = m.walk_forward_evaluate(features, df["Close"], n_splits=3)
                return res["mean_auc"]

            print(f"\nRunning Optuna study to tune hyperparameters (50 trials)...")
            study = optuna.create_study(direction="maximize")
            study.optimize(objective, n_trials=50)
            best_params = study.best_params
            print(f"  Best params found: {best_params}")
            print(f"  Best AUC (3-split): {study.best_value:.4f}")
        except ImportError:
            print("  Optuna library not available. Skipping tuning. Run: pip install optuna")

    print(f"\nRunning {n_splits}-fold walk-forward cross-validation...")
    print(f"  (This is the ONLY valid metric — do not report in-sample AUC)")
    print()

    model = XGBoostSignalModel(
        prediction_horizon=5, profit_threshold=0.01, model_params=best_params,
        prune_correlation=prune_correlation, prune_importance_pct=prune_importance_pct
    )
    wf_metrics = model.walk_forward_evaluate(features, df["Close"], n_splits=n_splits)

    return wf_metrics, model, features


def print_evaluation_report(symbol: str, timeframe: str, wf_metrics: dict,
                             df: pd.DataFrame):
    """Print a structured, honest evaluation report."""
    auc   = wf_metrics["mean_auc"]
    std   = wf_metrics["std_auc"]
    brier = wf_metrics["mean_brier"]

    brier_baseline = 0.25  # Brier score of a model that always predicts 50%

    print("=" * 64)
    print(f"  WALK-FORWARD EVALUATION REPORT")
    print(f"  Symbol: {symbol}  |  Timeframe: {timeframe}")
    print(f"  Bars:   {len(df)}  |  Folds: {wf_metrics['n_folds']}")
    print("=" * 64)
    print()

    # Per-fold results
    print("  Per-fold results:")
    print(f"  {'Fold':<6} {'AUC':>8} {'Brier':>8} {'Pos%':>8} {'Train':>8} {'Test':>8}")
    print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for f in wf_metrics["folds"]:
        print(f"  {f['fold']:<6} {f['roc_auc']:>8.4f} "
              f"{f['brier_score']:>8.4f} "
              f"{f['positive_rate']*100:>7.1f}% "
              f"{f['train_size']:>8} {f['test_size']:>8}")

    print()
    print(f"  Mean AUC:    {auc:.4f}  ±  {std:.4f}")
    print(f"  Mean Brier:  {brier:.4f}  (baseline: {brier_baseline:.4f})")
    print(f"  AUC improvement vs random (0.50): {(auc - 0.50)*100:+.2f}pp")
    print(f"  Brier improvement vs baseline:    {(brier_baseline - brier)*100:+.2f}pp")
    print()

    # Honest deployment verdict
    print("  DEPLOYMENT VERDICT:")
    if auc < 0.50:
        verdict = "WORSE THAN RANDOM"
        colour  = "  [X]"
        reason  = "AUC below 0.50 means the model is actively wrong more often than right."
    elif auc < 0.52:
        verdict = "DO NOT DEPLOY — no detectable edge"
        colour  = "  [X]"
        reason  = (f"AUC {auc:.4f} is within noise of random. "
                   "Add more features (GARCH vol, regime, sentiment) before retraining.")
    elif auc < 0.55:
        verdict = "MARGINAL — do not deploy without backtest cost check"
        colour  = "  [!]"
        reason  = (f"AUC {auc:.4f} gives a small edge that may be erased by "
                   "slippage + commission. Run BacktestEngine with realistic costs first.")
    elif auc < 0.60:
        verdict = "PROCEED TO BACKTEST"
        colour  = "  [OK]"
        reason  = (f"AUC {auc:.4f} is a solid edge. Backtest with 10bps slippage "
                   "and 0.2% commission to confirm it survives costs.")
    else:
        verdict = "STRONG EDGE — verify no data leakage before celebrating"
        colour  = "  [!]"
        reason  = (f"AUC {auc:.4f} is unusually high. Double-check for lookahead "
                   "bias in feature construction before trusting this number.")

    print(f"{colour} {verdict}")
    print(f"     {reason}")
    print()
    print("  IMPORTANT: These are out-of-sample walk-forward metrics.")
    print("  Do NOT use in-sample AUC or standard k-fold CV on time-series.")
    print("=" * 64)

    return auc >= 0.53


def train_and_save(model, features: pd.DataFrame, df: pd.DataFrame,
                   symbol: str, timeframe: str, wf_metrics: dict,
                   artifacts_dir: str = "./ml/artifacts"):
    """Train final model on full dataset and save to disk."""
    print(f"\nTraining final model on full {len(df)}-bar dataset...")
    model.train_final(features, df["Close"])

    save_path = Path(artifacts_dir) / symbol.upper() / timeframe
    model.save(str(save_path))

    print(f"  Saved to: {save_path}")
    print(f"  Files:")
    for f in sorted(save_path.iterdir()):
        print(f"    {f.name}  ({f.stat().st_size / 1024:.1f} KB)")

    return save_path


def main():
    parser = argparse.ArgumentParser(
        description="Train and walk-forward validate an XGBoost signal model."
    )
    parser.add_argument("--symbol",    default="AAPL",  help="Ticker symbol")
    parser.add_argument("--timeframe", default="1d",    help="Bar interval")
    parser.add_argument("--years",     default=5, type=int, help="Years of history")
    parser.add_argument("--splits",    default=5, type=int, help="WF folds")
    parser.add_argument("--artifacts", default="./ml/artifacts", help="Model save path")
    parser.add_argument("--force",     action="store_true",
                        help="Train final model even if AUC < 0.53 (not recommended)")
    parser.add_argument("--tune",      action="store_true",
                        help="Enable Optuna hyperparameter tuning")
    
    # Feature ablation flags
    parser.add_argument("--market", action="store_true", help="Enable 2a market features")
    parser.add_argument("--long-memory", action="store_true", help="Enable 2b long memory features")
    parser.add_argument("--vol-price", action="store_true", help="Enable 2c volume-price features")
    parser.add_argument("--calendar", action="store_true", help="Enable 2d calendar features")
    
    # Pruning flags
    parser.add_argument("--prune-corr", action="store_true", help="Enable correlation-based pruning")
    parser.add_argument("--prune-imp", action="store_true", help="Enable XGBoost importance pruning (bottom 30%)")
    
    args = parser.parse_args()

    symbol    = args.symbol.upper()
    timeframe = args.timeframe

    # 1. Fetch
    df = fetch_data(symbol, args.years)

    # 2. Walk-forward evaluate
    from ml.features.technical_indicators import IndicatorConfig
    config = IndicatorConfig(
        enable_market_features=args.market,
        enable_long_memory=args.long_memory,
        enable_vol_price=args.vol_price,
        enable_calendar=args.calendar
    )
    prune_imp_val = 0.3 if args.prune_imp else 0.0
    wf_metrics, model, features = run_walk_forward(
        df, symbol, n_splits=args.splits, tune=args.tune, indicator_config=config,
        prune_correlation=args.prune_corr, prune_importance_pct=prune_imp_val
    )

    # 3. Report
    should_deploy = print_evaluation_report(symbol, timeframe, wf_metrics, df)

    # 4. Train final model if edge is confirmed (or --force)
    if should_deploy or args.force:
        if args.force and not should_deploy:
            print("\n[!] --force flag set: training despite AUC below threshold.")
            print("   This model should NOT be used for real decisions.")
        train_and_save(model, features, df, symbol, timeframe,
                       wf_metrics, artifacts_dir=args.artifacts)
        print(f"\n[OK] Model ready. Next step: run the backtest.")
        print(f"   curl -X POST http://localhost:8000/api/v1/analysis/backtest \\")
        print(f"     -H 'Content-Type: application/json' \\")
        print(f"     -d \'{{\"symbol\":\"{symbol}\",\"timeframe\":\"{timeframe}\",")
        print(f"           \"start_date\":\"2022-01-01\",\"end_date\":\"2024-01-01\",")
        print(f"           \"initial_capital\":10000,\"slippage_bps\":10}}\'")
    else:
        print("\n[X] Model NOT saved — AUC below deployment threshold.")
        print("   Suggested next steps:")
        print("   1. Add GARCH conditional volatility as a feature")
        print("   2. Add HMM regime labels as features")
        print("   3. Try a longer lookback (--years 7)")
        print("   4. Try different symbols (some are more predictable than others)")
        print("   5. Try different prediction horizons (1d, 10d, 20d)")
        print("   The AUC you got is honest. Most first attempts are below 0.53.")
        print("   That is the correct answer, not a bug.")
        sys.exit(1)


if __name__ == "__main__":
    main()
