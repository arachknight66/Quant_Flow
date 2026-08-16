#!/usr/bin/env python3
import sys
import os
import argparse
import warnings
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "tuning-script-key-not-for-production")
os.environ.setdefault("POSTGRES_PASSWORD", "unused-for-training")
os.environ.setdefault("DEBUG", "true")

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import optuna
import yfinance as yf
from ml.features.technical_indicators import build_feature_matrix, IndicatorConfig
from ml.models.xgboost_model import XGBoostSignalModel
from ml.backtesting.engine import WalkForwardSplitter
from sklearn.metrics import roc_auc_score

def evaluate_on_period(df_train, df_test, symbol, params, thresh, best_config):
    # Train on df_train and predict on df_test
    # This evaluates out-of-sample on a single split
    from ml.models.xgboost_model import XGBoostSignalModel
    
    # Build features for train and test combined to avoid boundary issues, then split
    df_combined = pd.concat([df_train, df_test], axis=0)
    features = build_feature_matrix(df_combined, config=best_config, drop_na=False, symbol=symbol)
    
    m = XGBoostSignalModel(prediction_horizon=5, profit_threshold=thresh, model_params=params)
    target = m._create_target(df_combined["Close"])
    ml_feats = m._select_ml_features(features)
    
    # Align and mask
    mask = target.notna()
    X = ml_feats[mask]
    y = target[mask]
    
    # Split back
    train_idx = df_combined.index.isin(df_train.index)
    test_idx = df_combined.index.isin(df_test.index)
    
    X_train, y_train = X[train_idx & mask], y[train_idx & mask]
    X_test, y_test = X[test_idx & mask], y[test_idx & mask]
    
    if len(y_test) == 0 or len(set(y_test)) < 2:
        return 0.50
        
    class_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    model = m._build_model(class_weight)
    model.fit(X_train, y_train)
    
    proba = model.predict_proba(X_test)[:, 1]
    return roc_auc_score(y_test, proba)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="RUN")
    parser.add_argument("--years", default=5, type=int)
    parser.add_argument("--trials", default=150, type=int)
    args = parser.parse_args()
    
    symbol = args.symbol.upper()
    
    print(f"Fetching {args.years}yr data for {symbol}...")
    df = yf.download(symbol, period=f"{args.years}y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    print(f"Loaded {len(df)} bars.")
    
    # Best features config from Step 2/3
    best_config = IndicatorConfig(enable_long_memory=True, enable_vol_price=True)
    
    # Split data chronologically (60% TUNE, 20% VALIDATE, 20% HOLDOUT)
    n = len(df)
    idx_tune = int(n * 0.6)
    idx_val = int(n * 0.8)
    
    df_tune = df.iloc[:idx_tune]
    df_val = df.iloc[idx_tune:idx_val]
    df_hold = df.iloc[idx_val:]
    
    print(f"Splits: TUNE={len(df_tune)} bars, VALIDATE={len(df_val)} bars, HOLDOUT={len(df_hold)} bars")
    
    # Build feature matrix only on TUNE to optimize on it
    features_tune = build_feature_matrix(df_tune, config=best_config, drop_na=False, symbol=symbol)
    
    # Objective function
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    
    def objective(trial):
        params = {
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.20, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "n_estimators": trial.suggest_int("n_estimators", 50, 600),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 100),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0)
        }
        thresh = trial.suggest_categorical("profit_threshold", [0.005, 0.01, 0.015, 0.02])
        
        m = XGBoostSignalModel(prediction_horizon=5, profit_threshold=thresh, model_params=params)
        
        # 3-fold Walk Forward on TUNE features
        try:
            res = m.walk_forward_evaluate(features_tune, df_tune["Close"], n_splits=3)
            return res["mean_auc"]
        except Exception:
            return 0.50

    print(f"\nRunning Optuna study ({args.trials} trials) on TUNE split...")
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=args.trials)
    
    best_params = study.best_params
    best_thresh = best_params.pop("profit_threshold")
    
    print("\n" + "="*80)
    print("OPTUNA STUDY COMPLETE")
    print("="*80)
    print(f"Best TUNE walk-forward AUC: {study.best_value:.4f}")
    print(f"Best Profit Threshold target: {best_thresh*100:.1f}%")
    print("Best parameters:")
    for k, v in best_params.items():
        print(f"  {k}: {v}")
    print("="*80)
    
    # Define default model params
    default_params = {}
    default_thresh = 0.01
    
    # 5. Evaluate on VALIDATE split (Train on TUNE -> Predict on VALIDATE)
    print("\nEvaluating on VALIDATE split (out-of-sample)...")
    val_auc_default = evaluate_on_period(df_tune, df_val, symbol, default_params, default_thresh, best_config)
    val_auc_tuned = evaluate_on_period(df_tune, df_val, symbol, best_params, best_thresh, best_config)
    val_improvement = val_auc_tuned - val_auc_default
    print(f"  Default parameters VALIDATE AUC: {val_auc_default:.4f}")
    print(f"  Tuned parameters VALIDATE AUC:   {val_auc_tuned:.4f}")
    print(f"  VALIDATE Improvement:            {val_improvement:+.4f}")
    
    # 6. Evaluate on HOLDOUT split (Train on TUNE+VALIDATE -> Predict on HOLDOUT)
    print("\nEvaluating on HOLDOUT split (out-of-sample)...")
    df_train_comb = pd.concat([df_tune, df_val], axis=0)
    hold_auc_default = evaluate_on_period(df_train_comb, df_hold, symbol, default_params, default_thresh, best_config)
    hold_auc_tuned = evaluate_on_period(df_train_comb, df_hold, symbol, best_params, best_thresh, best_config)
    hold_improvement = hold_auc_tuned - hold_auc_default
    print(f"  Default parameters HOLDOUT AUC: {hold_auc_default:.4f}")
    print(f"  Tuned parameters HOLDOUT AUC:   {hold_auc_tuned:.4f}")
    print(f"  HOLDOUT Improvement:            {hold_improvement:+.4f}")
    
    # Save parameters to metadata or results folder
    results_dir = Path("scripts/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    
    tuning_report = (
        f"# Hyperparameter Tuning Report ({symbol})\n\n"
        f"Optimized on TUNE split (first 60% dates) via 150 trials of Optuna.\n\n"
        f"## Best Parameters Found:\n"
        f"- **profit_threshold**: {best_thresh}\n"
    )
    for k, v in best_params.items():
        tuning_report += f"- **{k}**: {v}\n"
        
    tuning_report += (
        f"\n## Out-of-Sample Performance Verification:\n\n"
        f"| Split | Default AUC | Tuned AUC | Improvement |\n"
        f"|---|---|---|---|\n"
        f"| VALIDATE | {val_auc_default:.4f} | {val_auc_tuned:.4f} | {val_improvement:+.4f} |\n"
        f"| HOLDOUT | {hold_auc_default:.4f} | {hold_auc_tuned:.4f} | {hold_improvement:+.4f} |\n\n"
        f"Verdict: {'TUNING SUCCESSFUL' if hold_improvement > 0 else 'TUNING OVERFITTED'}\n"
    )
    
    (results_dir / "hyperparameter_tuning.md").write_text(tuning_report)
    print(f"\nTuning report saved to scripts/results/hyperparameter_tuning.md")

if __name__ == "__main__":
    main()
