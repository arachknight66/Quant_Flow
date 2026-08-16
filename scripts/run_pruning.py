#!/usr/bin/env python3
import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "training-script-key-not-for-production")
os.environ.setdefault("POSTGRES_PASSWORD", "unused-for-training")
os.environ.setdefault("DEBUG", "true")

from scripts.train_model import fetch_data, run_walk_forward
from ml.features.technical_indicators import IndicatorConfig

def main():
    symbols = ["AAPL", "MSFT", "JPM", "XOM", "TSLA", "SPY", "BTC-USD", "RUN"]
    
    # Configure best indicators from Step 2
    best_config = IndicatorConfig(enable_long_memory=True, enable_vol_price=True)
    
    # Download data for all symbols
    dfs = {}
    for symbol in symbols:
        try:
            dfs[symbol] = fetch_data(symbol, 5)
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            
    pruning_results = []
    
    for symbol in symbols:
        if symbol not in dfs:
            continue
            
        df = dfs[symbol]
        
        print(f"\n================================================================================")
        print(f"RUNNING PRUNING EXPERIMENTS FOR: {symbol}")
        print(f"================================================================================")
        
        # 1. No Pruning (Reference)
        print("\n--- Running Reference (No Pruning) ---")
        try:
            wf_ref, _, _ = run_walk_forward(df, symbol, n_splits=5, indicator_config=best_config,
                                            prune_correlation=False, prune_importance_pct=0.0)
            ref_auc = wf_ref["mean_auc"]
        except Exception as e:
            print(f"Error running ref for {symbol}: {e}")
            ref_auc = np.nan
            
        # 2. Correlation Pruning Only
        print("\n--- Running Correlation Pruning ---")
        try:
            wf_corr, _, _ = run_walk_forward(df, symbol, n_splits=5, indicator_config=best_config,
                                             prune_correlation=True, prune_importance_pct=0.0)
            corr_auc = wf_corr["mean_auc"]
        except Exception as e:
            print(f"Error running corr for {symbol}: {e}")
            corr_auc = np.nan
            
        # 3. Importance Pruning Only
        print("\n--- Running Importance Pruning (bottom 30%) ---")
        try:
            wf_imp, _, _ = run_walk_forward(df, symbol, n_splits=5, indicator_config=best_config,
                                            prune_correlation=False, prune_importance_pct=0.3)
            imp_auc = wf_imp["mean_auc"]
        except Exception as e:
            print(f"Error running imp for {symbol}: {e}")
            imp_auc = np.nan
            
        # 4. Combined Pruning (Both)
        print("\n--- Running Combined Pruning ---")
        try:
            wf_comb, _, _ = run_walk_forward(df, symbol, n_splits=5, indicator_config=best_config,
                                             prune_correlation=True, prune_importance_pct=0.3)
            comb_auc = wf_comb["mean_auc"]
        except Exception as e:
            print(f"Error running comb for {symbol}: {e}")
            comb_auc = np.nan
            
        pruning_results.append({
            "Symbol": symbol,
            "Best Feature AUC (No Pruning)": f"{ref_auc:.4f}" if not np.isnan(ref_auc) else "ERR",
            "Correlation Pruning AUC": f"{corr_auc:.4f}" if not np.isnan(corr_auc) else "ERR",
            "Corr Diff": f"{(corr_auc - ref_auc):+.4f}" if not np.isnan(corr_auc) and not np.isnan(ref_auc) else "N/A",
            "Importance Pruning AUC": f"{imp_auc:.4f}" if not np.isnan(imp_auc) else "ERR",
            "Imp Diff": f"{(imp_auc - ref_auc):+.4f}" if not np.isnan(imp_auc) and not np.isnan(ref_auc) else "N/A",
            "Combined Pruning AUC": f"{comb_auc:.4f}" if not np.isnan(comb_auc) else "ERR",
            "Comb Diff": f"{(comb_auc - ref_auc):+.4f}" if not np.isnan(comb_auc) and not np.isnan(ref_auc) else "N/A"
        })

    df_pruning = pd.DataFrame(pruning_results)
    markdown_table = df_pruning.to_markdown(index=False)
    
    # Calculate average difference to see which pruning works best
    corr_diffs, imp_diffs, comb_diffs = [], [], []
    for r in pruning_results:
        c_d = r["Corr Diff"]
        i_d = r["Imp Diff"]
        cb_d = r["Comb Diff"]
        if c_d != "N/A" and c_d != "ERR": corr_diffs.append(float(c_d))
        if i_d != "N/A" and i_d != "ERR": imp_diffs.append(float(i_d))
        if cb_d != "N/A" and cb_d != "ERR": comb_diffs.append(float(cb_d))
        
    mean_corr_diff = np.mean(corr_diffs) if corr_diffs else 0.0
    mean_imp_diff = np.mean(imp_diffs) if imp_diffs else 0.0
    mean_comb_diff = np.mean(comb_diffs) if comb_diffs else 0.0
    
    verdict_text = (
        f"\n\n## Feature Pruning Study Results (Step 3)\n\n"
        f"Tested on top of 2b_long_mem + 2c_vol_price features:\n\n"
        f"{markdown_table}\n\n"
        f"### Pruning Verdicts:\n"
        f"- **Correlation Pruning (|r| > 0.85)**: Mean AUC difference: {mean_corr_diff:+.4f} -> "
        f"{'KEEP' if mean_corr_diff > 0.0 else 'DISCARD'}\n"
        f"- **Importance Pruning (Bottom 30%)**: Mean AUC difference: {mean_imp_diff:+.4f} -> "
        f"{'KEEP' if mean_imp_diff > 0.0 else 'DISCARD'}\n"
        f"- **Combined Pruning**: Mean AUC difference: {mean_comb_diff:+.4f} -> "
        f"{'KEEP' if mean_comb_diff > 0.0 else 'DISCARD'}\n"
    )
    
    ablation_file_path = Path("scripts/results/feature_ablation.md")
    existing_content = ablation_file_path.read_text()
    
    # Append to existing feature_ablation.md
    new_content = existing_content + verdict_text
    ablation_file_path.write_text(new_content)
    
    print("\n" + "="*80)
    print("PRUNING EXPERIMENT COMPLETE. RESULTS SAVED TO feature_ablation.md.")
    print("="*80)
    print(verdict_text)

if __name__ == "__main__":
    main()
