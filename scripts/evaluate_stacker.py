#!/usr/bin/env python3
import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import roc_auc_score

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SECRET_KEY", "evaluation-script-key")
os.environ.setdefault("POSTGRES_PASSWORD", "unused")
os.environ.setdefault("DEBUG", "true")

import yfinance as yf
from ml.features.technical_indicators import build_feature_matrix, IndicatorConfig
from ml.models.xgboost_model import XGBoostSignalModel
from ml.models.volatility.garch_model import GARCHVolatilityModel
from ml.models.regime.hmm_regime_detector import HMMRegimeDetector
from ml.models.ensemble.signal_stacker import SignalStacker
from ml.backtesting.engine import BacktestEngine, SlippageModel, CommissionModel
from backend.services.risk_engine import RiskTolerance

def main():
    symbols = ["AAPL", "MSFT", "JPM", "XOM", "TSLA", "SPY", "BTC-USD", "RUN"]
    best_config = IndicatorConfig(enable_long_memory=True, enable_vol_price=True)
    
    results = []
    
    for symbol in symbols:
        print("\n" + "="*80)
        print(f"EVALUATING STACKER VS RAW FOR: {symbol}")
        print("="*80)
        
        try:
            df = yf.download(symbol, period="5y", interval="1d", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            n = len(df)
            idx_split = int(n * 0.8) # 80% train, 20% holdout
            
            df_train = df.iloc[:idx_split]
            df_hold = df.iloc[idx_split:]
            
            # Compute features for combined to avoid boundaries
            features = build_feature_matrix(df, config=best_config, drop_na=False, symbol=symbol)
            
            # Base XGBoost Model
            xgb_model = XGBoostSignalModel(prediction_horizon=5, profit_threshold=0.01)
            target = xgb_model._create_target(df["Close"])
            ml_feats = xgb_model._select_ml_features(features)
            
            # Masks
            mask = target.notna()
            train_mask = df.index.isin(df_train.index) & mask
            hold_mask = df.index.isin(df_hold.index) & mask
            
            X_train, y_train = ml_feats[train_mask], target[train_mask]
            X_hold, y_hold = ml_feats[hold_mask], target[hold_mask]
            
            # Train Base XGBoost
            class_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
            xgb_model.model = xgb_model._build_model(class_weight)
            xgb_model.model.fit(X_train, y_train)
            xgb_model.feature_names = list(ml_feats.columns)
            
            # Base model holdout AUC
            raw_proba = xgb_model.model.predict_proba(X_hold)[:, 1]
            raw_auc = roc_auc_score(y_hold, raw_proba)
            
            # Volatility and Regime models
            lr_train = np.log(df_train["Close"] / df_train["Close"].shift(1)).dropna()
            
            garch = GARCHVolatilityModel()
            garch.fit(lr_train)
            
            hmm = HMMRegimeDetector(n_regimes=3)
            hmm.fit(lr_train)
            
            # Stacker
            stacker = SignalStacker(xgb_model, garch, hmm)
            
            # Stacker holdout probabilities
            stacked_probs = []
            for i in range(len(df_hold)):
                sub_feats = features.iloc[:idx_split + i + 1]
                pred = stacker.predict(sub_feats)
                stacked_probs.append(pred["prob_profit"])
                
            stacked_auc = roc_auc_score(y_hold, stacked_probs[:len(y_hold)])
            
            # Backtests - setting warmup_bars to idx_split to start trading on Holdout
            engine_raw = BacktestEngine(
                initial_capital=10000.0,
                risk_tolerance=RiskTolerance.MODERATE,
                slippage_model=SlippageModel(fixed_bps=10.0),
                commission_model=CommissionModel(percentage=0.001),
                warmup_bars=idx_split
            )
            
            engine_stacked = BacktestEngine(
                initial_capital=10000.0,
                risk_tolerance=RiskTolerance.MODERATE,
                slippage_model=SlippageModel(fixed_bps=10.0),
                commission_model=CommissionModel(percentage=0.001),
                warmup_bars=idx_split
            )
            
            # Run backtest on full data (it will start trading from idx_split)
            res_raw = engine_raw.run(df, xgb_model, best_config)
            res_stacked = engine_stacked.run(df, stacker, best_config)
            
            sum_raw = res_raw["summary"]
            risk_raw = res_raw["risk"]
            t_raw = res_raw["trades"]
            
            sum_stacked = res_stacked["summary"]
            risk_stacked = res_stacked["risk"]
            t_stacked = res_stacked["trades"]
            
            results.append({
                "Symbol": symbol,
                "Raw AUC": f"{raw_auc:.4f}",
                "Stacked AUC": f"{stacked_auc:.4f}",
                "Raw Return": f"{sum_raw['total_return_pct']:.2f}%",
                "Stacked Return": f"{sum_stacked['total_return_pct']:.2f}%",
                "Raw Sharpe": f"{risk_raw['sharpe_ratio']:.3f}",
                "Stacked Sharpe": f"{risk_stacked['sharpe_ratio']:.3f}",
                "Raw Trades": str(t_raw['total_trades']),
                "Stacked Trades": str(t_stacked['total_trades'])
            })
            
        except Exception as e:
            print(f"Error evaluating {symbol}: {e}")
            results.append({
                "Symbol": symbol,
                "Raw AUC": "ERR", "Stacked AUC": "ERR",
                "Raw Return": "ERR", "Stacked Return": "ERR",
                "Raw Sharpe": "ERR", "Stacked Sharpe": "ERR",
                "Raw Trades": "0", "Stacked Trades": "0"
            })
            
    df_res = pd.DataFrame(results)
    markdown_table = df_res.to_markdown(index=False)
    
    results_dir = Path("scripts/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    
    report_content = (
        f"# Ensemble Stacking Evaluation (Step 5)\n\n"
        f"Blended XGBoost directional predictions with GARCH volatility scaling "
        f"and HMM regime multipliers. Backtested on identical out-of-sample HOLDOUT periods "
        f"with 10bps slippage and 0.1% commission:\n\n"
        f"{markdown_table}\n"
    )
    
    (results_dir / "stacked_vs_raw.md").write_text(report_content)
    print("\n" + "="*80)
    print("STACKER EVALUATION COMPLETE. RESULTS SAVED.")
    print("="*80)
    print(report_content)

if __name__ == "__main__":
    main()
