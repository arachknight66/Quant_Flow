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
    feature_groups = {
        "2a_market": {"enable_market_features": True},
        "2b_long_mem": {"enable_long_memory": True},
        "2c_vol_price": {"enable_vol_price": True},
        "2d_calendar": {"enable_calendar": True}
    }
    
    # Load baseline results
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
                        
    print("Baseline AUCs loaded:", baseline_aucs)
    
    # Download data for all symbols first to cache in memory
    dfs = {}
    for symbol in symbols:
        try:
            dfs[symbol] = fetch_data(symbol, 5)
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            
    ablation_results = []
    
    for symbol in symbols:
        if symbol not in dfs:
            continue
            
        df = dfs[symbol]
        base_auc = baseline_aucs.get(symbol, 0.50)
        
        row = {
            "Symbol": symbol,
            "Baseline AUC": f"{base_auc:.4f}"
        }
        
        for name, config_args in feature_groups.items():
            print(f"\n--- Symbol: {symbol} | Feature Group: {name} ---")
            config = IndicatorConfig(**config_args)
            try:
                wf_metrics, _, _ = run_walk_forward(df, symbol, n_splits=5, indicator_config=config)
                auc = wf_metrics["mean_auc"]
                diff = auc - base_auc
                row[f"{name} AUC"] = f"{auc:.4f}"
                row[f"{name} Diff"] = f"{diff:+.4f}"
            except Exception as e:
                print(f"Error evaluating {symbol} with {name}: {e}")
                row[f"{name} AUC"] = "ERR"
                row[f"{name} Diff"] = "N/A"
                
        ablation_results.append(row)

    # Compile results table
    df_ablation = pd.DataFrame(ablation_results)
    
    # Format and Save
    results_dir = Path("scripts/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    
    markdown_table = df_ablation.to_markdown(index=False)
    
    ablation_file_path = results_dir / "feature_ablation.md"
    
    # Determine which feature groups are keepers (> 0.005 mean improvement across baseline symbols)
    summary_text = "\n\n## Ablation Verdicts\n"
    for name in feature_groups.keys():
        diffs = []
        for r in ablation_results:
            diff_str = r.get(f"{name} Diff", "N/A")
            if diff_str != "N/A" and diff_str != "ERR":
                diffs.append(float(diff_str))
        mean_diff = np.mean(diffs) if diffs else 0.0
        keeper = mean_diff > 0.005
        verdict = "**KEEPER**" if keeper else "**DISCARD**"
        summary_text += f"- **{name}**: Mean AUC difference: {mean_diff:+.4f} -> {verdict}\n"
        
    full_content = "# Feature Ablation Study Results\n\n" + markdown_table + summary_text
    ablation_file_path.write_text(full_content)
    
    print("\n" + "="*80)
    print("ABLATION STUDY COMPLETE. RESULTS SAVED.")
    print("="*80)
    print(full_content)

if __name__ == "__main__":
    main()
