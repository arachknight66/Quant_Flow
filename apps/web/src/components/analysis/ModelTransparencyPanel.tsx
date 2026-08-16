"use client";

import { useModelInfo } from "@/hooks/useModelInfo";
import { fmtPct } from "@/lib/utils";

interface Props {
  symbol: string;
  timeframe?: string;
}

export function ModelTransparencyPanel({ symbol, timeframe = "1d" }: Props) {
  const { data: info, isLoading, error } = useModelInfo(symbol, timeframe);

  if (isLoading) {
    return (
      <div className="card p-5 text-center text-xs text-[var(--text-dim)]">
        Loading model validation metrics & parameters...
      </div>
    );
  }

  if (error || !info) {
    return (
      <div className="card p-5 text-center text-xs text-[var(--text-dim)]">
        Model metadata not available for {symbol}. Run a model training loop or wait for the next scheduled retrain.
      </div>
    );
  }

  // Sort feature importances if present
  const sortedFeatures = info.feature_importances
    ? Object.entries(info.feature_importances).sort((a, b) => b[1] - a[1])
    : [];

  return (
    <div className="card p-5 space-y-6">
      <div className="flex items-center justify-between border-b pb-4 border-[var(--border)]">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text)]">Model Transparency & Validation</h2>
          <p className="text-xs text-[var(--text-dim)]">
            Inspecting {info.symbol} ({info.timeframe}) XGBoost classifier metadata
          </p>
        </div>
        <div className="text-right">
          <span className="text-xs px-2 py-1 rounded bg-[var(--surface-high)] border border-[var(--border)] text-[var(--text)] mono">
            {info.version}
          </span>
        </div>
      </div>

      {/* Staleness Warning Banner */}
      {info.staleness_warning && (
        <div className="p-4 rounded-lg bg-[var(--red)]/10 border border-[var(--red)]/35 text-[var(--red)] text-xs space-y-1">
          <div className="font-bold flex items-center gap-1.5">
            ⚠️ Model Drift Warning
          </div>
          <p className="text-[var(--text-dim)]">
            This model was trained {info.model_age_days} days ago (last trained: {new Date(info.trained_at).toLocaleDateString()}). 
            Models older than 30 days are subject to market regime changes and feature drift. We recommend initiating a manual model retrain.
          </p>
        </div>
      )}

      {/* Model Parameters & Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-3 rounded-lg" style={{ background: "var(--bg)" }}>
          <div className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider font-semibold">Trained At</div>
          <div className="text-sm font-semibold mt-1 text-[var(--text)]">
            {new Date(info.trained_at).toLocaleDateString()}
          </div>
        </div>
        <div className="p-3 rounded-lg" style={{ background: "var(--bg)" }}>
          <div className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider font-semibold">Prediction Horizon</div>
          <div className="text-sm font-semibold mt-1 text-[var(--text)]">
            {info.prediction_horizon} Bars ({info.timeframe})
          </div>
        </div>
        <div className="p-3 rounded-lg" style={{ background: "var(--bg)" }}>
          <div className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider font-semibold">Profit Target</div>
          <div className="text-sm font-semibold mt-1 text-[var(--text)]">
            {(info.profit_threshold * 100).toFixed(1)}%
          </div>
        </div>
        <div className="p-3 rounded-lg" style={{ background: "var(--bg)" }}>
          <div className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider font-semibold">Model Age</div>
          <div className="text-sm font-semibold mt-1 text-[var(--text)]">
            {info.model_age_days} Days
          </div>
        </div>
      </div>

      {/* Walk Forward Metrics */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold text-[var(--text-dim)] uppercase tracking-wider">
          Walk-Forward Validation Performance
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 rounded-lg border border-[var(--border)]" style={{ background: "var(--surface)" }}>
            <span className="text-[10px] text-[var(--text-dim)] font-medium">Mean Validation AUC</span>
            <div className="text-2xl font-bold mono text-[var(--accent)] mt-1">
              {info.mean_auc != null ? info.mean_auc.toFixed(4) : "—"}
            </div>
            <span className="text-[9px] text-[var(--text-dim)] block mt-1">
              SD: {info.std_auc != null ? info.std_auc.toFixed(4) : "—"} (across {info.n_folds ?? 0} folds)
            </span>
          </div>

          <div className="p-4 rounded-lg border border-[var(--border)]" style={{ background: "var(--surface)" }}>
            <span className="text-[10px] text-[var(--text-dim)] font-medium">Mean Brier Score</span>
            <div className="text-2xl font-bold mono text-[var(--text)] mt-1">
              {info.mean_brier != null ? info.mean_brier.toFixed(4) : "—"}
            </div>
            <span className="text-[9px] text-[var(--text-dim)] block mt-1">
              Indicates probability forecast accuracy (lower is better)
            </span>
          </div>

          <div className="p-4 rounded-lg border border-[var(--border)]" style={{ background: "var(--surface)" }}>
            <span className="text-[10px] text-[var(--text-dim)] font-medium">Feature Dimension</span>
            <div className="text-2xl font-bold mono text-[var(--text)] mt-1">
              {info.n_features}
            </div>
            <span className="text-[9px] text-[var(--text-dim)] block mt-1">
              Technical indicator features fed to booster
            </span>
          </div>
        </div>
      </div>

      {/* Feature Importances list */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold text-[var(--text-dim)] uppercase tracking-wider">
          Feature Importance Distribution
        </h3>
        
        {sortedFeatures.length > 0 ? (
          <div className="space-y-2.5 max-h-60 overflow-y-auto pr-1">
            {sortedFeatures.map(([name, weight]) => (
              <div key={name} className="space-y-1 text-xs">
                <div className="flex justify-between items-center">
                  <span className="font-semibold text-[var(--text)] mono">{name}</span>
                  <span className="text-[var(--text-dim)] mono">{(weight * 100).toFixed(2)}%</span>
                </div>
                <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: "var(--surface-high)" }}>
                  <div
                    className="h-full rounded-full bg-[var(--accent)] transition-all duration-500"
                    style={{ width: `${weight * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-[var(--text-dim)] bg-[var(--surface-high)]/30 rounded-lg border border-[var(--border)]">
            Feature importances are not available for this model version. Retrain the model to populate.
          </div>
        )}
      </div>
    </div>
  );
}
