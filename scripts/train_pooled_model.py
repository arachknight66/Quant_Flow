#!/usr/bin/env python3
import sys
import os
import argparse
import warnings
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "training-script-key-not-for-production")
os.environ.setdefault("POSTGRES_PASSWORD", "unused-for-training")
os.environ.setdefault("DEBUG", "true")

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.metrics import roc_auc_score, brier_score_loss
from ml.features.technical_indicators import build_feature_matrix
from ml.models.xgboost_model import XGBoostSignalModel
from ml.backtesting.engine import WalkForwardSplitter

SECTORS = {
    "AAPL": "Tech", "MSFT": "Tech", "NVDA": "Tech", "AMZN": "Tech", "GOOGL": "Tech", "META": "Tech", "ADBE": "Tech", "AMD": "Tech", "CRM": "Tech",
    "JPM": "Financials", "V": "Financials", "MA": "Financials", "BAC": "Financials",
    "XOM": "Energy", "CVX": "Energy",
    "TSLA": "Consumer", "WMT": "Consumer", "PG": "Consumer", "KO": "Consumer", "PEP": "Consumer", "COST": "Consumer",
    "UNH": "Healthcare", "JNJ": "Healthcare", "LLY": "Healthcare", "MRK": "Healthcare",
    "SPY": "Other", "BTC-USD": "Other", "RUN": "Other"
}

BASELINE_SYMBOLS = ["AAPL", "MSFT", "JPM", "XOM", "TSLA", "SPY", "BTC-USD", "RUN"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", default=5, type=int)
    parser.add_argument("--splits", default=5, type=int)
    args = parser.parse_args()
    
    symbols = list(SECTORS.keys())
    symbol_dfs = {}
    
    print(f"Fetching {args.years}yr data for {len(symbols)} symbols...")
    for sym in symbols:
        try:
            print(f"  Fetching {sym}...")
            df = yf.download(sym, period=f"{args.years}y", interval="1d", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if not df.empty and len(df) > 100:
                symbol_dfs[sym] = df
            else:
                print(f"  ⚠️ Warning: Insufficient data for {sym}")
        except Exception as e:
            print(f"  ❌ Error fetching {sym}: {e}")
            
    print(f"\nSuccessfully fetched data for {len(symbol_dfs)} symbols.")
    
    # 2. Build feature matrices per symbol independently (no leakage)
    print("\nBuilding features per symbol...")
    symbol_data = {}
    model_obj = XGBoostSignalModel() # to reuse _create_target and _select_ml_features
    
    for sym, df in symbol_dfs.items():
        try:
            features = build_feature_matrix(df, drop_na=False)
            target = model_obj._create_target(df["Close"])
            
            # Align features and target
            mask = target.notna()
            df_sym = features[mask].copy()
            df_sym["target"] = target[mask]
            df_sym["Close_target"] = df["Close"].reindex(df_sym.index)
            df_sym["symbol"] = sym
            df_sym["sector"] = SECTORS.get(sym, "Other")
            
            symbol_data[sym] = df_sym
        except Exception as e:
            print(f"  ❌ Error building features for {sym}: {e}")
            
    # Compile dummy categories
    all_symbols_list = sorted(list(symbol_data.keys()))
    all_sectors_list = sorted(list(set(SECTORS.values())))
    
    # 3. Concatenate and add one-hot variables
    processed_dfs = []
    for sym, df_sym in symbol_data.items():
        # One-hot encode symbol and sector
        for s in all_symbols_list:
            df_sym[f"symbol_{s}"] = 1.0 if s == sym else 0.0
        for sec in all_sectors_list:
            df_sym[f"sector_{sec}"] = 1.0 if sec == df_sym["sector"].iloc[0] else 0.0
        processed_dfs.append(df_sym)
        
    pooled_raw = pd.concat(processed_dfs, axis=0)
    # Sort by date
    pooled_raw = pooled_raw.sort_index()
    
    all_dates = sorted(list(set(pooled_raw.index)))
    n_dates = len(all_dates)
    
    # 60% TUNE, 20% VALIDATE, 20% HOLDOUT cutoffs
    tune_cutoff_idx = int(0.6 * n_dates)
    val_cutoff_idx = int(0.8 * n_dates)
    
    tune_dates = all_dates[:tune_cutoff_idx]
    val_dates = all_dates[tune_cutoff_idx:val_cutoff_idx]
    holdout_dates = all_dates[val_cutoff_idx:]
    
    print(f"\nDate splits:")
    print(f"  TUNE:     {tune_dates[0].strftime('%Y-%m-%d')} to {tune_dates[-1].strftime('%Y-%m-%d')} ({len(tune_dates)} dates)")
    print(f"  VALIDATE: {val_dates[0].strftime('%Y-%m-%d')} to {val_dates[-1].strftime('%Y-%m-%d')} ({len(val_dates)} dates)")
    print(f"  HOLDOUT:  {holdout_dates[0].strftime('%Y-%m-%d')} to {holdout_dates[-1].strftime('%Y-%m-%d')} ({len(holdout_dates)} dates)")
    
    # Create TUNE, VALIDATE, HOLDOUT datasets
    df_tune = pooled_raw.loc[pooled_raw.index.isin(tune_dates)]
    df_val = pooled_raw.loc[pooled_raw.index.isin(val_dates)]
    df_hold = pooled_raw.loc[pooled_raw.index.isin(holdout_dates)]
    
    # We will run Walk-Forward Evaluation on the TUNE split
    print(f"\nRunning {args.splits}-fold Walk-Forward Cross-Validation on TUNE split...")
    tune_splitter = WalkForwardSplitter(n_splits=args.splits)
    
    # Split the TUNE dates
    tune_dates_arr = np.array(tune_dates)
    fold_aucs = []
    
    # Features selection
    ml_feats_cols = model_obj._select_ml_features(pooled_raw).columns.tolist()
    # Ensure categorical features are selected
    cat_cols = [c for c in pooled_raw.columns if c.startswith("symbol_") or c.startswith("sector_")]
    for c in cat_cols:
        if c not in ml_feats_cols:
            ml_feats_cols.append(c)
    ml_feats_cols = [c for c in ml_feats_cols if c not in ["symbol", "sector"]]
            
    print(f"  Total feature count: {len(ml_feats_cols)}")
    
    for fold, (train_idx_dates, test_idx_dates) in enumerate(tune_splitter.split(pd.DataFrame(index=tune_dates))):
        train_d = tune_dates_arr[train_idx_dates]
        test_d = tune_dates_arr[test_idx_dates]
        
        train_df = df_tune[df_tune.index.isin(train_d)]
        test_df = df_tune[df_tune.index.isin(test_d)]
        
        X_train, y_train = train_df[ml_feats_cols], train_df["target"]
        X_test, y_test = test_df[ml_feats_cols], test_df["target"]
        
        # Calculate class weight on training fold
        class_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
        
        fold_model = model_obj._build_model(class_weight)
        fold_model.fit(X_train, y_train)
        
        proba = fold_model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, proba)
        fold_aucs.append(auc)
        print(f"    Fold {fold} AUC: {auc:.4f}")
        
    print(f"  Mean TUNE AUC: {np.mean(fold_aucs):.4f} ± {np.std(fold_aucs):.4f}")
    
    # 4. Evaluate walk-forward on VALIDATE split (training on all data prior to each validate fold)
    print(f"\nEvaluating walk-forward on VALIDATE split...")
    val_splitter = WalkForwardSplitter(n_splits=3)
    val_dates_arr = np.array(val_dates)
    val_preds = []
    val_targets = []
    
    for fold, (train_idx_dates, test_idx_dates) in enumerate(val_splitter.split(pd.DataFrame(index=val_dates))):
        test_d = val_dates_arr[test_idx_dates]
        
        # Train on all dates before test_d
        train_d = [d for d in all_dates if d < test_d[0]]
        
        train_df = pooled_raw[pooled_raw.index.isin(train_d)]
        test_df = df_val[df_val.index.isin(test_d)]
        
        X_train, y_train = train_df[ml_feats_cols], train_df["target"]
        X_test, y_test = test_df[ml_feats_cols], test_df["target"]
        
        class_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
        fold_model = model_obj._build_model(class_weight)
        fold_model.fit(X_train, y_train)
        
        proba = fold_model.predict_proba(X_test)[:, 1]
        val_preds.extend(proba)
        val_targets.extend(y_test.values)
        
    val_auc = roc_auc_score(val_targets, val_preds)
    print(f"  VALIDATE AUC (pooled): {val_auc:.4f}")
    
    # 5. Evaluate walk-forward on HOLDOUT split (training on all data prior to each holdout fold)
    # Collect predictions per symbol to evaluate symbol-level holdout performance
    print(f"\nEvaluating walk-forward on HOLDOUT split...")
    hold_splitter = WalkForwardSplitter(n_splits=5)
    hold_dates_arr = np.array(holdout_dates)
    
    symbol_hold_preds = {sym: [] for sym in BASELINE_SYMBOLS}
    symbol_hold_targets = {sym: [] for sym in BASELINE_SYMBOLS}
    
    for fold, (train_idx_dates, test_idx_dates) in enumerate(hold_splitter.split(pd.DataFrame(index=holdout_dates))):
        test_d = hold_dates_arr[test_idx_dates]
        train_d = [d for d in all_dates if d < test_d[0]]
        
        train_df = pooled_raw[pooled_raw.index.isin(train_d)]
        test_df = df_hold[df_hold.index.isin(test_d)]
        
        X_train, y_train = train_df[ml_feats_cols], train_df["target"]
        X_test, y_test = test_df[ml_feats_cols], test_df["target"]
        
        class_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
        fold_model = model_obj._build_model(class_weight)
        fold_model.fit(X_train, y_train)
        
        proba = fold_model.predict_proba(X_test)[:, 1]
        
        # Distribute predictions back to baseline symbols
        test_df = test_df.copy()
        test_df["pred"] = proba
        
        for sym in BASELINE_SYMBOLS:
            sym_test = test_df[test_df["symbol"] == sym]
            if not sym_test.empty:
                symbol_hold_preds[sym].extend(sym_test["pred"].values)
                symbol_hold_targets[sym].extend(sym_test["target"].values)
                
    # Report per-symbol HOLDOUT results
    print("\nHOLDOUT RESULTS PER BASELINE SYMBOL:")
    print(f"  {'Symbol':<10} {'Holdout AUC':>12}")
    print(f"  {'-'*10} {'-'*12}")
    
    comparison = []
    
    # Read baseline results to compare
    baseline_table_path = Path("scripts/results/baseline_results.md")
    baseline_aucs = {}
    if baseline_table_path.exists():
        lines = baseline_table_path.read_text().split("\n")
        for line in lines[2:]:
            if line.strip().startswith("|"):
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2:
                    try:
                        baseline_aucs[parts[0]] = float(parts[1])
                    except ValueError:
                        pass
                        
    for sym in BASELINE_SYMBOLS:
        y_true = symbol_hold_targets[sym]
        y_pred = symbol_hold_preds[sym]
        if len(y_true) > 0 and len(set(y_true)) > 1:
            auc = roc_auc_score(y_true, y_pred)
            brier = brier_score_loss(y_true, y_pred)
        else:
            auc = np.nan
            brier = np.nan
            
        base_auc = baseline_aucs.get(sym, np.nan)
        diff = auc - base_auc if not np.isnan(base_auc) and not np.isnan(auc) else np.nan
        
        print(f"  {sym:<10} {auc:>12.4f} (baseline: {base_auc:.4f}, diff: {diff:+.4f})")
        
        comparison.append({
            "Symbol": sym,
            "Baseline AUC": f"{base_auc:.4f}" if not np.isnan(base_auc) else "N/A",
            "Pooled Holdout AUC": f"{auc:.4f}" if not np.isnan(auc) else "N/A",
            "Difference": f"{diff:+.4f}" if not np.isnan(diff) else "N/A",
            "Verdict": "IMPROVED" if diff > 0 else "NO IMPROVEMENT" if not np.isnan(diff) else "N/A"
        })
        
    # Write pooled vs baseline results comparison
    comp_df = pd.DataFrame(comparison)
    comp_markdown = comp_df.to_markdown(index=False) if hasattr(comp_df, "to_markdown") else str(comp_df)
    
    results_dir = Path("scripts/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    
    # Save comparison to file
    (results_dir / "pooled_vs_baseline.md").write_text(comp_markdown)
    print(f"\nComparison saved to scripts/results/pooled_vs_baseline.md")
    
    # Train final pooled model on the entire TUNE + VALIDATE + HOLDOUT (full dataset)
    print(f"\nTraining final GENERAL pooled model on full pooled dataset...")
    X_full = pooled_raw[ml_feats_cols]
    y_full = pooled_raw["target"]
    class_weight = (y_full == 0).sum() / max((y_full == 1).sum(), 1)
    
    final_model = model_obj._build_model(class_weight)
    final_model.fit(X_full, y_full)
    
    # Save the final pooled model as the GENERAL model
    save_path = Path("./ml/artifacts/GENERAL/1d")
    save_path.mkdir(parents=True, exist_ok=True)
    
    # Create compatible XGBoostSignalModel
    final_sig_model = XGBoostSignalModel(prediction_horizon=5, profit_threshold=0.01, version="pooled_general_v1")
    final_sig_model.model = final_model
    final_sig_model.feature_names = ml_feats_cols
    
    # Add dummy fold metrics for save compatibility
    final_sig_model.walk_forward_metrics = [
        {
            "fold": 0, "train_size": len(X_full), "test_size": 0,
            "brier_score": float(np.mean([brier_score_loss(pooled_raw["target"], final_model.predict_proba(X_full)[:, 1])])),
            "roc_auc": float(val_auc), # use val_auc as representative AUC
            "log_loss": 0.0, "positive_rate": float(pooled_raw["target"].mean())
        }
    ]
    
    final_sig_model.save(str(save_path))
    print(f"Saved final GENERAL pooled model to {save_path}")

if __name__ == "__main__":
    main()
