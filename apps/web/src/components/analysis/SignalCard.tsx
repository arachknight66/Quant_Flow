// apps/web/src/components/analysis/SignalCard.tsx
"use client";
import { FullAnalysisResponse } from "@/lib/api-client";
import { cn } from "@/lib/utils";

interface Props {
  analysis: FullAnalysisResponse;
}

const ACTION_STYLES = {
  BUY: "bg-green-50 border-green-200 text-green-900",
  SELL: "bg-red-50 border-red-200 text-red-900",
  HOLD: "bg-amber-50 border-amber-200 text-amber-900",
} as const;

const CONFIDENCE_BAR_COLOR = (confidence: number) => {
  if (confidence > 0.7) return "bg-green-500";
  if (confidence > 0.4) return "bg-amber-500";
  return "bg-red-400";
};

export function SignalCard({ analysis }: Props) {
  const { action, confidence, prob_profit, position_sizing, warnings } = analysis;

  return (
    <div className="rounded-xl border bg-white shadow-sm p-6 space-y-5">
      {/* Signal badge */}
      <div className="flex items-center justify-between">
        <div
          className={cn(
            "inline-flex items-center gap-2 px-4 py-2 rounded-lg border font-semibold text-lg",
            ACTION_STYLES[action]
          )}
        >
          {action === "BUY" && <span>↑</span>}
          {action === "SELL" && <span>↓</span>}
          {action === "HOLD" && <span>~</span>}
          {action}
        </div>
        <div className="text-right">
          <p className="text-sm text-gray-500">Model version</p>
          <p className="text-xs font-mono text-gray-700">{analysis.model_version}</p>
        </div>
      </div>

      {/* Confidence meter */}
      <div>
        <div className="flex justify-between text-sm mb-1">
          <span className="text-gray-600">Confidence</span>
          <span className="font-medium">{(confidence * 100).toFixed(1)}%</span>
        </div>
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all", CONFIDENCE_BAR_COLOR(confidence))}
            style={{ width: `${confidence * 100}%` }}
          />
        </div>
      </div>

      {/* Probability */}
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div className="bg-gray-50 rounded-lg p-3">
          <p className="text-gray-500 text-xs mb-1">Prob. of profit</p>
          <p className="font-semibold text-gray-900 text-base">
            {(prob_profit * 100).toFixed(1)}%
          </p>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <p className="text-gray-500 text-xs mb-1">95% VaR (1d)</p>
          <p className="font-semibold text-red-600 text-base">
            -{analysis.var_95.toFixed(2)}%
          </p>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <p className="text-gray-500 text-xs mb-1">Expected (low)</p>
          <p className={cn("font-semibold text-base",
            analysis.expected_return_lo >= 0 ? "text-green-700" : "text-red-600"
          )}>
            {analysis.expected_return_lo >= 0 ? "+" : ""}{analysis.expected_return_lo.toFixed(1)}%
          </p>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <p className="text-gray-500 text-xs mb-1">Expected (high)</p>
          <p className={cn("font-semibold text-base",
            analysis.expected_return_hi >= 0 ? "text-green-700" : "text-red-600"
          )}>
            {analysis.expected_return_hi >= 0 ? "+" : ""}{analysis.expected_return_hi.toFixed(1)}%
          </p>
        </div>
      </div>

      {/* Position sizing */}
      {position_sizing && (
        <div className="border border-blue-100 bg-blue-50 rounded-lg p-4 space-y-2">
          <p className="text-sm font-medium text-blue-900">Suggested position</p>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-blue-600 text-xs">Allocation</span>
              <p className="font-semibold text-blue-900">
                ${position_sizing.position_value_usd.toLocaleString()} ({position_sizing.allocation_pct.toFixed(1)}%)
              </p>
            </div>
            <div>
              <span className="text-blue-600 text-xs">Shares</span>
              <p className="font-semibold text-blue-900">{position_sizing.n_shares.toFixed(2)}</p>
            </div>
            <div>
              <span className="text-blue-600 text-xs">Stop loss</span>
              <p className="font-semibold text-red-600">${position_sizing.stop_loss_price.toFixed(2)}</p>
            </div>
            <div>
              <span className="text-blue-600 text-xs">Take profit</span>
              <p className="font-semibold text-green-600">${position_sizing.take_profit_price.toFixed(2)}</p>
            </div>
          </div>
          <p className="text-xs text-blue-700 mt-1">
            Risk/reward: {position_sizing.risk_reward_ratio.toFixed(2)}:1 ·
            Kelly (applied): {(position_sizing.kelly_fraction_applied * 100).toFixed(1)}%
          </p>
        </div>
      )}

      {/* Warnings — always visible */}
      <div className="space-y-1">
        {warnings.map((w, i) => (
          <div key={i} className="flex gap-2 text-xs text-amber-700 bg-amber-50 rounded p-2">
            <span>⚠</span>
            <span>{w}</span>
          </div>
        ))}
      </div>
    </div>
  );
}