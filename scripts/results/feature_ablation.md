# Feature Ablation Study Results

| Symbol   |   Baseline AUC |   2a_market AUC |   2a_market Diff |   2b_long_mem AUC |   2b_long_mem Diff |   2c_vol_price AUC |   2c_vol_price Diff |   2d_calendar AUC |   2d_calendar Diff |
|:---------|---------------:|----------------:|-----------------:|------------------:|-------------------:|-------------------:|--------------------:|------------------:|-------------------:|
| AAPL     |         0.6486 |          0.623  |          -0.0256 |            0.6426 |            -0.006  |             0.6234 |             -0.0252 |            0.5758 |            -0.0728 |
| MSFT     |         0.5365 |          0.5395 |           0.003  |            0.5881 |             0.0516 |             0.5739 |              0.0374 |            0.5422 |             0.0057 |
| JPM      |         0.3968 |          0.356  |          -0.0408 |            0.364  |            -0.0328 |             0.3696 |             -0.0272 |            0.471  |             0.0742 |
| XOM      |         0.4709 |          0.4675 |          -0.0034 |            0.4764 |             0.0055 |             0.4695 |             -0.0014 |            0.4343 |            -0.0366 |
| TSLA     |         0.5794 |          0.583  |           0.0036 |            0.5679 |            -0.0115 |             0.5796 |              0.0002 |            0.5921 |             0.0127 |
| SPY      |         0.4149 |          0.4262 |           0.0113 |            0.4316 |             0.0167 |             0.537  |              0.1221 |            0.3946 |            -0.0203 |
| BTC-USD  |         0.4445 |          0.4504 |           0.0059 |            0.5308 |             0.0863 |             0.4421 |             -0.0024 |            0.4545 |             0.01   |
| RUN      |         0.5751 |          0.5943 |           0.0192 |            0.5816 |             0.0065 |             0.6016 |              0.0265 |            0.6237 |             0.0486 |

## Ablation Verdicts
- **2a_market**: Mean AUC difference: -0.0034 -> **DISCARD**
- **2b_long_mem**: Mean AUC difference: +0.0145 -> **KEEPER**
- **2c_vol_price**: Mean AUC difference: +0.0163 -> **KEEPER**
- **2d_calendar**: Mean AUC difference: +0.0027 -> **DISCARD**


## Feature Pruning Study Results (Step 3)

Tested on top of 2b_long_mem + 2c_vol_price features:

| Symbol   |   Best Feature AUC (No Pruning) |   Correlation Pruning AUC |   Corr Diff |   Importance Pruning AUC |   Imp Diff |   Combined Pruning AUC |   Comb Diff |
|:---------|--------------------------------:|--------------------------:|------------:|-------------------------:|-----------:|-----------------------:|------------:|
| AAPL     |                          0.5925 |                    0.6091 |      0.0166 |                   0.5996 |     0.0071 |                 0.6294 |      0.0368 |
| MSFT     |                          0.5869 |                    0.6104 |      0.0235 |                   0.5996 |     0.0127 |                 0.5696 |     -0.0173 |
| JPM      |                          0.3425 |                    0.3568 |      0.0142 |                   0.3548 |     0.0122 |                 0.3352 |     -0.0074 |
| XOM      |                          0.4544 |                    0.4351 |     -0.0193 |                   0.472  |     0.0176 |                 0.4392 |     -0.0151 |
| TSLA     |                          0.5802 |                    0.5347 |     -0.0455 |                   0.5433 |    -0.0368 |                 0.5258 |     -0.0544 |
| SPY      |                          0.5804 |                    0.5177 |     -0.0627 |                   0.539  |    -0.0414 |                 0.533  |     -0.0474 |
| BTC-USD  |                          0.5324 |                    0.5134 |     -0.019  |                   0.5167 |    -0.0157 |                 0.4893 |     -0.0431 |
| RUN      |                          0.6261 |                    0.5679 |     -0.0582 |                   0.6234 |    -0.0027 |                 0.568  |     -0.0581 |

### Pruning Verdicts:
- **Correlation Pruning (|r| > 0.85)**: Mean AUC difference: -0.0188 -> DISCARD
- **Importance Pruning (Bottom 30%)**: Mean AUC difference: -0.0059 -> DISCARD
- **Combined Pruning**: Mean AUC difference: -0.0258 -> DISCARD
