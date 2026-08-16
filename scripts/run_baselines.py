#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "training-script-key-not-for-production")
os.environ.setdefault("POSTGRES_PASSWORD", "unused-for-training")
os.environ.setdefault("DEBUG", "true")

import pandas as pd
from scripts.train_model import fetch_data, run_walk_forward

def main():
    symbols = ["AAPL", "MSFT", "JPM", "XOM", "TSLA", "SPY", "BTC-USD", "RUN"]
    results = []
    
    results_dir = Path("scripts/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    
    for symbol in symbols:
        print("\n" + "="*80)
        print(f"RUNNING BASELINE FOR: {symbol}")
        print("="*80)
        try:
            df = fetch_data(symbol, 5)
            wf_metrics, model, features = run_walk_forward(df, symbol, n_splits=5)
            
            auc = wf_metrics["mean_auc"]
            std = wf_metrics["std_auc"]
            brier = wf_metrics["mean_brier"]
            n_folds = wf_metrics["n_folds"]
            
            if auc < 0.50:
                verdict = "WORSE THAN RANDOM"
            elif auc < 0.52:
                verdict = "DO NOT DEPLOY"
            elif auc < 0.55:
                verdict = "MARGINAL"
            elif auc < 0.60:
                verdict = "PROCEED TO BACKTEST"
            else:
                verdict = "STRONG EDGE"
                
            results.append({
                "Symbol": symbol,
                "Mean AUC": f"{auc:.4f}",
                "Std AUC": f"{std:.4f}",
                "Mean Brier": f"{brier:.4f}",
                "N Folds": str(n_folds),
                "Verdict": verdict
            })
            
            # Save the baseline model to artifacts
            save_path = Path("./ml/artifacts") / symbol.upper() / "1d"
            model.train_final(features, df["Close"])
            model.save(str(save_path))
            print(f"Saved baseline model for {symbol} to {save_path}")
            
        except Exception as e:
            print(f"Error training {symbol}: {e}")
            results.append({
                "Symbol": symbol,
                "Mean AUC": "ERR",
                "Std AUC": "ERR",
                "Mean Brier": "ERR",
                "N Folds": "0",
                "Verdict": f"Error: {str(e)[:30]}"
            })

    # Generate Markdown Table
    df_results = pd.DataFrame(results)
    markdown_table = df_results.to_markdown(index=False)
    
    file_path = results_dir / "baseline_results.md"
    file_path.write_text(markdown_table)
    
    print("\n" + "="*80)
    print("BASELINE RUN COMPLETE. RESULTS SAVED.")
    print("="*80)
    print(markdown_table)

if __name__ == "__main__":
    main()
