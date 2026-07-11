"use client";
import { FullAnalysisResponse } from "@/lib/api-client";

interface Props { data: FullAnalysisResponse; }

const ACTION_STYLE: Record<string, { bg: string; color: string; label: string }> = {
  BUY:  { bg: "rgba(0,229,160,0.12)", color: "var(--green)", label: "BUY"  },
  HOLD: { bg: "rgba(255,176,32,0.12)", color: "var(--amber)", label: "HOLD" },
  SELL: { bg: "rgba(255,68,102,0.12)", color: "var(--red)",   label: "SELL" },
};

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct > 60 ? "var(--green)" : pct > 35 ? "var(--amber)" : "var(--red)";
  return (
    <div>
      <div className="flex justify-between text-xs mb-1"
           style={{ color: "var(--text-dim)" }}>
        <span>Confidence</span>
        <span style={{ color }}>{pct}%</span>
      </div>
      <div className="rounded-full overflow-hidden"
           style={{ height: 6, background: "var(--border)" }}>
        <div className="h-full rounded-full transition-all duration-700"
             style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

export function SignalCard({ data }: Props) {
  const style = ACTION_STYLE[data.action] ?? ACTION_STYLE.HOLD;
  const prob  = Math.round(data.prob_profit * 100);

  return (
    <div className="card p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium" style={{ color: "var(--text-dim)" }}>
          Signal
        </h2>
        <span className="text-xs mono" style={{ color: "var(--text-muted)" }}>
          {data.model_version}
        </span>
      </div>

      {/* Action badge */}
      <div className="flex items-center gap-4">
        <div className="px-6 py-3 rounded-xl font-bold text-2xl tracking-widest"
             style={{ background: style.bg, color: style.color }}>
          {style.label}
        </div>
        <div className="flex flex-col gap-1">
          <div className="text-xs" style={{ color: "var(--text-dim)" }}>
            Prob(profit)
          </div>
          <div className="text-3xl font-bold mono" style={{ color: style.color }}>
            {prob}%
          </div>
        </div>
      </div>

      <ConfidenceBar value={data.confidence} />

      {/* Expected return range */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: "Expected lo",  value: data.expected_return_lo, isReturn: true  },
          { label: "Expected hi",  value: data.expected_return_hi, isReturn: true  },
          { label: "VaR 95%",      value: -data.var_95,            isReturn: true  },
          { label: "WF AUC",       value: data.walk_forward_auc,   isReturn: false },
        ].map(({ label, value, isReturn }) => (
          <div key={label} className="rounded-lg px-3 py-2"
               style={{ background: "var(--bg)" }}>
            <div className="text-xs mb-1" style={{ color: "var(--text-dim)" }}>{label}</div>
            <div className="text-sm font-semibold mono"
                 style={{ color: isReturn && value != null
                   ? (value >= 0 ? "var(--green)" : "var(--red)") : "var(--text)" }}>
              {value == null ? "—"
               : isReturn   ? `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`
               :               value.toFixed(4)}
            </div>
          </div>
        ))}
      </div>

      {/* Warnings (show only the first, not the boilerplate last one) */}
      {data.warnings.slice(0, -1).map((w, i) => (
        <div key={i} className="flex gap-2 text-xs rounded-lg px-3 py-2"
             style={{ background: "rgba(255,176,32,0.08)", color: "var(--amber)" }}>
          <span>⚠</span><span>{w}</span>
        </div>
      ))}
    </div>
  );
}
