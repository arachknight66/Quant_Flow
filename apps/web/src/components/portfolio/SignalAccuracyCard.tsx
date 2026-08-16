"use client";

import { useEffect, useState } from "react";
import { api, SignalAccuracyResponse } from "@/lib/api-client";
import { fmtPct } from "@/lib/utils";

export function SignalAccuracyCard() {
  const [data, setData] = useState<SignalAccuracyResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [days, setDays] = useState<number>(90);

  useEffect(() => {
    async function loadAccuracy() {
      try {
        setLoading(true);
        const res = await api.portfolio.signalsAccuracy(undefined, days);
        setData(res);
      } catch (err) {
        console.error("Failed to load signals accuracy", err);
      } finally {
        setLoading(false);
      }
    }
    loadAccuracy();
  }, [days]);

  if (loading && !data) {
    return (
      <div className="card p-5 text-center text-xs text-[var(--text-dim)]">
        Calculating historical prediction accuracy...
      </div>
    );
  }

  if (!data || data.total_signals_evaluated === 0) {
    return (
      <div className="card p-5 text-center text-xs text-[var(--text-dim)]">
        No evaluated signals in the last {days} days. Signal accuracy will display once signals reach their resolution horizon.
      </div>
    );
  }

  // Aggregate deciles to Low / Medium / High confidence:
  // Low = 40-50%, 50-60%
  // Med = 20-30%, 30-40%, 60-70%, 70-80%
  // High = 0-10%, 10-20%, 80-90%, 90-100%
  const lowBins = ["40-50%", "50-60%"];
  const medBins = ["20-30%", "30-40%", "60-70%", "70-80%"];
  const highBins = ["0-10%", "10-20%", "80-90%", "90-100%"];

  const getAggregated = (binsList: string[]) => {
    let count = 0;
    let correct = 0;
    data.confidence_buckets.forEach((b) => {
      if (binsList.includes(b.bin)) {
        count += b.count;
        correct += b.correct;
      }
    });
    return {
      count,
      correct,
      accuracy: count > 0 ? (correct / count) * 100 : 0,
    };
  };

  const confidenceStats = [
    { label: "Low Confidence", ...getAggregated(lowBins), color: "var(--red)" },
    { label: "Medium Confidence", ...getAggregated(medBins), color: "var(--amber)" },
    { label: "High Confidence", ...getAggregated(highBins), color: "var(--green)" },
  ];

  return (
    <div className="card p-5 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text)]">Model Signal Accuracy</h2>
          <p className="text-xs text-[var(--text-dim)]">
            Tracking historical out-of-sample directional prediction performance
          </p>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value))}
          className="text-xs px-2.5 py-1.5 rounded outline-none"
          style={{
            background: "var(--surface-high)",
            border: "1px solid var(--border)",
            color: "var(--text)",
          }}
        >
          <option value={30}>Last 30 Days</option>
          <option value={90}>Last 90 Days</option>
          <option value={180}>Last 180 Days</option>
        </select>
      </div>

      {/* Hero Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-lg flex flex-col justify-between" style={{ background: "var(--bg)" }}>
          <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--text-dim)]">
            Overall Accuracy
          </span>
          <div className="flex items-baseline gap-1.5 mt-2">
            <span className="text-2xl font-bold mono text-[var(--accent)]">{data.accuracy_pct.toFixed(1)}%</span>
            <span className="text-[10px] text-[var(--text-dim)]">({data.correct_count} / {data.total_signals_evaluated} signals)</span>
          </div>
        </div>
        <div className="p-4 rounded-lg flex flex-col justify-between" style={{ background: "var(--bg)" }}>
          <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--text-dim)]">
            BUY Signal Accuracy
          </span>
          <div className="flex items-baseline gap-1.5 mt-2">
            <span className="text-2xl font-bold mono text-[var(--green)]">{data.buy_accuracy_pct.toFixed(1)}%</span>
            <span className="text-[10px] text-[var(--text-dim)]">({data.buy_count} signals)</span>
          </div>
        </div>
        <div className="p-4 rounded-lg flex flex-col justify-between" style={{ background: "var(--bg)" }}>
          <span className="text-[10px] uppercase tracking-wider font-semibold text-[var(--text-dim)]">
            SELL Signal Accuracy
          </span>
          <div className="flex items-baseline gap-1.5 mt-2">
            <span className="text-2xl font-bold mono text-[var(--red)]">{data.sell_accuracy_pct.toFixed(1)}%</span>
            <span className="text-[10px] text-[var(--text-dim)]">({data.sell_count} signals)</span>
          </div>
        </div>
      </div>

      {/* Accuracy by Confidence Bucket */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold text-[var(--text-dim)] uppercase tracking-wider">
          Calibration: Accuracy by Confidence Level
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {confidenceStats.map((bucket) => (
            <div key={bucket.label} className="p-3.5 rounded-lg border border-[var(--border)] flex flex-col gap-2">
              <div className="flex justify-between items-center text-xs">
                <span className="font-medium text-[var(--text-dim)]">{bucket.label}</span>
                <span className="font-semibold mono" style={{ color: bucket.color }}>
                  {bucket.count > 0 ? `${bucket.accuracy.toFixed(1)}%` : "—"}
                </span>
              </div>
              <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: "var(--surface-high)" }}>
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${bucket.count > 0 ? bucket.accuracy : 0}%`,
                    backgroundColor: bucket.color,
                  }}
                />
              </div>
              <span className="text-[10px] text-[var(--text-dim)]">
                {bucket.count > 0 ? `${bucket.correct} of ${bucket.count} correct` : "No signals"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Most Recent 10 Evaluated Signals */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold text-[var(--text-dim)] uppercase tracking-wider">
          Recent Evaluated Outcomes
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-[var(--border)] text-[var(--text-dim)] font-semibold uppercase tracking-wider pb-2">
                <th className="pb-2">Date</th>
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Direction</th>
                <th className="pb-2 text-right">Model Prob</th>
                <th className="pb-2 text-right">Forward Return</th>
                <th className="pb-2 text-center">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {data.most_recent_10.map((sig) => (
                <tr key={sig.id} className="text-[var(--text)] hover:bg-[var(--surface-high)]/30 transition-colors">
                  <td className="py-2.5 text-[var(--text-dim)]">
                    {new Date(sig.created_at).toLocaleDateString()}
                  </td>
                  <td className="py-2.5 font-semibold text-[var(--accent)]">{sig.symbol}</td>
                  <td className="py-2.5">
                    <span
                      className="px-1.5 py-0.5 rounded font-bold text-[9px] uppercase tracking-wider"
                      style={{
                        background: sig.action === "BUY" ? "rgba(0,229,160,0.1)" : "rgba(255,68,102,0.1)",
                        color: sig.action === "BUY" ? "var(--green)" : "var(--red)",
                      }}
                    >
                      {sig.action}
                    </span>
                  </td>
                  <td className="py-2.5 text-right mono">
                    {sig.prob_profit != null ? fmtPct(sig.prob_profit * 100) : "—"}
                  </td>
                  <td
                    className="py-2.5 text-right mono font-semibold"
                    style={{
                      color:
                        sig.actual_return_pct != null
                          ? sig.actual_return_pct >= 0
                            ? "var(--green)"
                            : "var(--red)"
                          : "var(--text)",
                    }}
                  >
                    {sig.actual_return_pct != null
                      ? `${sig.actual_return_pct >= 0 ? "+" : ""}${sig.actual_return_pct.toFixed(2)}%`
                      : "—"}
                  </td>
                  <td className="py-2.5 text-center">
                    {sig.correct != null ? (
                      <span
                        className="px-1.5 py-0.5 rounded font-medium text-[9px] uppercase"
                        style={{
                          background: sig.correct ? "rgba(0,229,160,0.12)" : "rgba(255,68,102,0.12)",
                          color: sig.correct ? "var(--green)" : "var(--red)",
                        }}
                      >
                        {sig.correct ? "Correct" : "Incorrect"}
                      </span>
                    ) : (
                      <span className="text-[var(--text-dim)]">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
