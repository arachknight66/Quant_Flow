"use client";
import { IndicatorValues } from "@/lib/api-client";
import { fmt } from "@/lib/utils";
import { explainIndicator } from "@/lib/plain-language";

interface Props { indicators: IndicatorValues; currentPrice: number; }

function Gauge({ value, min, max, label, fmt: fmtFn = (v: number) => v.toFixed(1) }: {
  value: number | null; min: number; max: number; label: string;
  fmt?: (v: number) => string;
}) {
  const explanation = value != null ? explainIndicator(label, value) : "";
  if (value == null) return (
    <div className="rounded-lg p-3" style={{ background: "var(--bg)" }}>
      <div className="text-xs mb-2" style={{ color: "var(--text-dim)" }}>{label}</div>
      <div className="text-sm" style={{ color: "var(--text-muted)" }}>—</div>
    </div>
  );
  const pct     = Math.min(Math.max((value - min) / (max - min), 0), 1);
  const color   = pct < 0.30 ? "var(--red)" : pct > 0.70 ? "var(--green)" : "var(--amber)";
  return (
    <div className="rounded-lg p-3" style={{ background: "var(--bg)" }}>
      <div className="flex justify-between text-xs mb-2"
           style={{ color: "var(--text-dim)" }}>
        <span>{label}</span>
        <span className="mono" style={{ color }}>{fmtFn(value)}</span>
      </div>
      <div className="rounded-full" style={{ height: 4, background: "var(--border)" }}>
        <div className="h-full rounded-full transition-all"
             style={{ width: `${pct * 100}%`, background: color }} />
      </div>
      <div className="flex justify-between text-xs mt-1"
           style={{ color: "var(--text-muted)" }}>
        <span>{min}</span><span>{max}</span>
      </div>
      {explanation && (
        <div className="text-xs mt-2 leading-relaxed" style={{ color: "var(--text-muted)" }}>
          {explanation}
        </div>
      )}
    </div>
  );
}

function StatCell({ label, value, color, rawValue, indicatorKey }: {
  label: string; value: string | null; color?: string;
  rawValue?: number | null; indicatorKey?: string;
}) {
  const explanation = rawValue != null && indicatorKey
    ? explainIndicator(indicatorKey, rawValue)
    : "";
  return (
    <div className="rounded-lg p-3" style={{ background: "var(--bg)" }}>
      <div className="text-xs mb-1" style={{ color: "var(--text-dim)" }}>{label}</div>
      <div className="text-sm font-semibold mono"
           style={{ color: color ?? "var(--text)" }}>
        {value ?? "—"}
      </div>
      {explanation && (
        <div className="text-xs mt-1.5 leading-relaxed" style={{ color: "var(--text-muted)" }}>
          {explanation}
        </div>
      )}
    </div>
  );
}

export function IndicatorGrid({ indicators: ind, currentPrice }: Props) {
  const bbPos = ind.bb_upper != null && ind.bb_lower != null
    ? ((currentPrice - ind.bb_lower) / (ind.bb_upper - ind.bb_lower)) * 100 : null;

  const macdColor = ind.macd_hist == null ? undefined
    : ind.macd_hist > 0 ? "var(--green)" : "var(--red)";
  const volColor  = ind.vol_20d == null ? undefined
    : ind.vol_20d > 0.35 ? "var(--red)" : ind.vol_20d > 0.20 ? "var(--amber)" : "var(--green)";

  return (
    <div className="card p-5 flex flex-col gap-4">
      <h2 className="text-sm font-medium" style={{ color: "var(--text-dim)" }}>
        Indicators
      </h2>

      <div className="grid grid-cols-2 gap-3">
        <Gauge value={ind.rsi} min={0} max={100} label="RSI (14)"
               fmt={(v) => v.toFixed(1)} />
        <Gauge value={bbPos} min={0} max={100} label="BB %B"
               fmt={(v) => `${v.toFixed(0)}%`} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <StatCell label="MACD Hist"
                  value={ind.macd_hist != null ? fmt(ind.macd_hist, 4) : null}
                  color={macdColor}
                  rawValue={ind.macd_hist}
                  indicatorKey="macd_hist" />
        <StatCell label="Ann. Vol 20d"
                  value={ind.vol_20d != null ? `${(ind.vol_20d * 100).toFixed(1)}%` : null}
                  color={volColor}
                  rawValue={ind.vol_20d}
                  indicatorKey="vol_20d" />
        <StatCell label="ATR"
                  value={ind.atr != null ? fmt(ind.atr, 3) : null}
                  rawValue={ind.atr_pct}
                  indicatorKey="atr" />
        <StatCell label="Momentum 10d"
                  value={ind.momentum_10 != null
                    ? `${ind.momentum_10 >= 0 ? "+" : ""}${(ind.momentum_10 * 100).toFixed(1)}%`
                    : null}
                  color={ind.momentum_10 != null
                    ? ind.momentum_10 > 0 ? "var(--green)" : "var(--red)" : undefined}
                  rawValue={ind.momentum_10}
                  indicatorKey="momentum" />
      </div>

      {ind.bb_upper != null && (
        <div className="rounded-lg p-3 text-xs" style={{ background: "var(--bg)" }}>
          <div className="flex justify-between mb-2"
               style={{ color: "var(--text-dim)" }}>
            <span>Bollinger Bands</span>
            <span className="mono" style={{ color: "var(--text)" }}>
              {fmt(currentPrice, 2)}
            </span>
          </div>
          <div className="flex justify-between mono" style={{ color: "var(--text-muted)" }}>
            <span style={{ color: "var(--red)" }}>↓ {fmt(ind.bb_lower!, 2)}</span>
            <span>{fmt(ind.bb_middle!, 2)}</span>
            <span style={{ color: "var(--green)" }}>↑ {fmt(ind.bb_upper, 2)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
