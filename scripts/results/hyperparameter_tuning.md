# Hyperparameter Tuning Report (RUN)

Optimized on TUNE split (first 60% dates) via 150 trials of Optuna.

## Best Parameters Found:
- **profit_threshold**: 0.02
- **max_depth**: 7
- **learning_rate**: 0.012150912358180608
- **subsample**: 0.5145840876595323
- **n_estimators**: 77
- **min_child_weight**: 27
- **reg_alpha**: 0.068322224417481
- **reg_lambda**: 9.800061856495647
- **colsample_bytree**: 0.7621865745469932

## Out-of-Sample Performance Verification:

| Split | Default AUC | Tuned AUC | Improvement |
|---|---|---|---|
| VALIDATE | 0.5237 | 0.6085 | +0.0848 |
| HOLDOUT | 0.6430 | 0.5260 | -0.1171 |

Verdict: TUNING OVERFITTED
