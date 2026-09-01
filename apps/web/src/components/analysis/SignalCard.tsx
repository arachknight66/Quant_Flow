"use client";
import { useState } from "react";
import { FullAnalysisResponse } from "@/lib/api-client";
import { summarizeSignal, METRIC_GLOSSARY } from "@/lib/plain-language";

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

function GlossaryTip({ term }: { term: string }) {
  const tip = METRIC_GLOSSARY[term];
  const [show, setShow] = useState(false);
  if (!tip) return null;
  return (
    <span className="relative inline-block ml-1 cursor-help"
          onMouseEnter={() => setShow(true)}
          onMouseLeave={() => setShow(false)}>
      <span className="text-xs" style={{ color: "var(--text-muted)", fontSize: 10 }}>ⓘ</span>
      {show && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 rounded-lg text-xs z-50 whitespace-normal"
              style={{
                background: "var(--surface-high)",
                border: "1px solid var(--border-bright)",
                color: "var(--text)",
                width: 220,
                lineHeight: 1.5,
                boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
              }}>
          {tip}
        </span>
      )}
    </span>
  );
}

export function SignalCard({ data }: Props) {
  const style = ACTION_STYLE[data.action] ?? ACTION_STYLE.HOLD;
  const prob  = Math.round(data.prob_profit * 100);
  const [showNumbers, setShowNumbers] = useState(false);

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

      {/* Plain-language summary */}
      <p className="text-sm leading-relaxed" style={{ color: "var(--text)" }}>
        {summarizeSignal(data)}
      </p>

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

      {/* Collapsible technical details */}
      <button
        onClick={() => setShowNumbers(!showNumbers)}
        className="flex items-center gap-2 text-xs py-1.5 transition-colors"
        style={{ color: "var(--text-dim)" }}>
        <span style={{
          display: "inline-block",
          transform: showNumbers ? "rotate(90deg)" : "rotate(0deg)",
          transition: "transform 0.2s",
        }}>▸</span>
        {showNumbers ? "Hide the numbers" : "Show the numbers"}
      </button>

      {showNumbers && (
        <div className="flex flex-col gap-4">
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
                <div className="text-xs mb-1" style={{ color: "var(--text-dim)" }}>
                  {label}
                  <GlossaryTip term={label} />
                </div>
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

          {/* Market Context (HMM Regime + GARCH Volatility) */}
          {(data.regime || data.garch_vol_forecast != null) && (
            <div className="flex flex-col gap-2 pt-3 border-t text-xs" style={{ borderColor: "var(--border)" }}>
              <div style={{ color: "var(--text-dim)" }}>Market Context</div>
              <div className="flex items-center gap-3 flex-wrap">
                {data.regime && (
                  <span className="px-2.5 py-1 rounded-full font-semibold capitalize"
                        style={{
                          background: data.regime === "bull" ? "rgba(0,229,160,0.12)" : data.regime === "bear" ? "rgba(255,68,102,0.12)" : "rgba(255,176,32,0.12)",
                          color: data.regime === "bull" ? "var(--green)" : data.regime === "bear" ? "var(--red)" : "var(--amber)",
                          opacity: data.regime_confidence != null ? 0.3 + data.regime_confidence * 0.7 : 1
                        }}>
                    {data.regime} Regime {data.regime_confidence != null ? `(${Math.round(data.regime_confidence * 100)}% conf)` : ""}
                  </span>
                )}
                {data.garch_vol_forecast != null && (
                  <span style={{ color: "var(--text)" }}>
                    Vol Forecast: <span className="font-semibold mono" style={{ color: "var(--amber)" }}>{(data.garch_vol_forecast * 100).toFixed(1)}%</span>
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

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
