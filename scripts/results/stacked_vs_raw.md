# Ensemble Stacking Evaluation (Step 5)

Blended XGBoost directional predictions with GARCH volatility scaling and HMM regime multipliers. Backtested on identical out-of-sample HOLDOUT periods with 10bps slippage and 0.1% commission:

| Symbol   |   Raw AUC |   Stacked AUC | Raw Return   | Stacked Return   |   Raw Sharpe |   Stacked Sharpe |   Raw Trades |   Stacked Trades |
|:---------|----------:|--------------:|:-------------|:-----------------|-------------:|-----------------:|-------------:|-----------------:|
| AAPL     |    0.595  |        0.4772 | 0.00%        | 0.00%            |            0 |                0 |            0 |                0 |
| MSFT     |    0.4785 |        0.4745 | 0.00%        | 0.00%            |            0 |                0 |            0 |                0 |
| JPM      |    0.4765 |        0.5044 | 0.00%        | 0.00%            |            0 |                0 |            0 |                0 |
| XOM      |    0.5052 |        0.5203 | 0.00%        | 0.00%            |            0 |                0 |            0 |                0 |
| TSLA     |    0.6212 |        0.5174 | 0.00%        | 0.00%            |            0 |                0 |            0 |                0 |
| SPY      |    0.4529 |        0.4689 | 0.00%        | 0.00%            |            0 |                0 |            0 |                0 |
| BTC-USD  |    0.4615 |        0.4667 | 0.00%        | 0.00%            |            0 |                0 |            0 |                0 |
| RUN      |    0.643  |        0.4756 | 0.00%        | 0.00%            |            0 |                0 |            0 |                0 |
