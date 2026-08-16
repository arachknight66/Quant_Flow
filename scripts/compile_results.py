#!/usr/bin/env python3
import json
from pathlib import Path
import numpy as np

def main():
    symbols = ["AAPL", "MSFT", "JPM", "XOM", "TSLA", "SPY", "BTC-USD", "RUN"]
    lines = []
    lines.append("| Symbol | Mean AUC | Std AUC | Mean Brier | N Folds | Verdict |")
    lines.append("|--------|----------|---------|------------|---------|---------|")
    
    for symbol in symbols:
        meta_path = Path(f"./ml/artifacts/{symbol}/1d/metadata.json")
        if not meta_path.exists():
            print(f"Metadata not found for {symbol}")
            continue
            
        metadata = json.loads(meta_path.read_text())
        wf = metadata.get("walk_forward_metrics", [])
        
        if not wf:
            print(f"No walk-forward metrics found in metadata for {symbol}")
            continue
            
        aucs = [f["roc_auc"] for f in wf]
        briers = [f["brier_score"] for f in wf]
        
        mean_auc = np.mean(aucs)
        std_auc = np.std(aucs)
        mean_brier = np.mean(briers)
        n_folds = len(wf)
        
        if mean_auc < 0.50:
            verdict = "WORSE THAN RANDOM"
        elif mean_auc < 0.52:
            verdict = "DO NOT DEPLOY"
        elif mean_auc < 0.55:
            verdict = "MARGINAL"
        elif mean_auc < 0.60:
            verdict = "PROCEED TO BACKTEST"
        else:
            verdict = "STRONG EDGE"
            
        lines.append(f"| {symbol} | {mean_auc:.4f} | {std_auc:.4f} | {mean_brier:.4f} | {n_folds} | {verdict} |")
        
    results_dir = Path("scripts/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    
    markdown_content = "\n".join(lines) + "\n"
    (results_dir / "baseline_results.md").write_text(markdown_content)
    print("baseline_results.md successfully generated:")
    print(markdown_content)

if __name__ == "__main__":
    main()
