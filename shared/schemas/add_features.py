#!/usr/bin/env python3
"""
Feature engineering diagnostic — shows what each feature contributes.

Run AFTER train_model.py to understand what the model learned.
Prints XGBoost feature importance and basic stationarity checks.

Usage:
    python scripts/add_features.py --symbol AAPL --years 5
"""
import argparse, sys, os, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "diag-script-key")
os.environ.setdefault("POSTGRES_PASSWORD", "unused")
os.environ.setdefault("DEBUG", "true")

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",  default="AAPL")
    parser.add_argument("--years",   default=5, type=int)
    parser.add_argument("--top",     default=20, type=int, help="Show top N features")
    args = parser.parse_args()

    import yfinance as yf
    from ml.features.technical_indicators import build_feature_matrix
    from ml.models.xgboost_model import XGBoostSignalModel

    symbol = args.symbol.upper()
    print(f"\nFetching {args.years}yr {symbol} data...")
    df = yf.download(symbol, period=f"{args.years}y", interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    print(f"Building feature matrix ({len(df)} bars)...")
    features = build_feature_matrix(df, drop_na=True)
    n_feat   = features.shape[1]
    print(f"  {n_feat} features computed")

    # Stationarity summary (ADF test)
    print(f"\nStationarity check (ADF p-value < 0.05 = stationary):")
    try:
        from statsmodels.tsa.stattools import adfuller
        non_stationary = []
        for col in features.columns:
            if col in ["Open","High","Low","Close","Volume"]: continue
            try:
                p = adfuller(features[col].dropna(), autolag="AIC")[1]
                if p > 0.05:
                    non_stationary.append((col, p))
            except Exception:
                pass
        if non_stationary:
            print(f"  ⚠️  {len(non_stationary)} non-stationary features (p > 0.05):")
            for col, p in sorted(non_stationary, key=lambda x: -x[1])[:10]:
                print(f"     {col:<40s} p={p:.4f}")
        else:
            print(f"  ✅ All features appear stationary")
    except ImportError:
        print("  statsmodels not installed — skip ADF test")
        print("  pip install statsmodels")

    # Feature importance via a quick XGBoost fit
    print(f"\nTop {args.top} feature importances (quick fit, not walk-forward):")
    model = XGBoostSignalModel()
    ml_feats = model._select_ml_features(features)
    close    = df["Close"].reindex(features.index)
    target   = model._create_target(close)
    mask     = target.notna() & ml_feats.notna().all(axis=1)
    X        = ml_feats[mask]
    y        = target[mask]

    import xgboost as xgb
    xgb_model = xgb.XGBClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.1,
        eval_metric="logloss", random_state=42, n_jobs=-1)
    xgb_model.fit(X, y)

    importance = pd.Series(xgb_model.feature_importances_,
                           index=X.columns).sort_values(ascending=False)

    print(f"  {'Feature':<45s} {'Importance':>10}")
    print(f"  {'-'*45} {'-'*10}")
    for feat, imp in importance.head(args.top).items():
        bar = "█" * int(imp * 200)
        print(f"  {feat:<45s} {imp:>10.4f}  {bar}")

    # Correlation matrix of top features
    top_feats = importance.head(10).index.tolist()
    corr = X[top_feats].corr()
    high_corr = [(c1, c2, corr.loc[c1, c2])
                 for i, c1 in enumerate(top_feats)
                 for c2 in top_feats[i+1:]
                 if abs(corr.loc[c1, c2]) > 0.85]
    if high_corr:
        print(f"\n  ⚠️  Highly correlated feature pairs (|r| > 0.85) — consider removing one:")
        for c1, c2, r in high_corr:
            print(f"     {c1} & {c2}: r={r:.3f}")

    print(f"\n  Positive rate (% of days price up > 1% in 5 days): "
          f"{y.mean()*100:.1f}%")
    print(f"  (A model always predicting the majority class achieves "
          f"{max(y.mean(), 1-y.mean())*100:.1f}% accuracy — your baseline)")


if __name__ == "__main__":
    main()
