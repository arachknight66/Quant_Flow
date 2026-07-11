"use client";
import {
  ResponsiveContainer, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from "recharts";
import { fmtUsd } from "@/lib/utils";

interface EquityPoint { t: string; v: number; dd: number; }

interface Props {
  data: EquityPoint[];
  initialCapital: number;
  height?: number;
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const { v, dd } = payload[0].payload as EquityPoint;
  return (
    <div className="rounded-lg px-3 py-2 text-xs"
         style={{ background: "var(--surface-high)",
                  border: "1px solid var(--border)" }}>
      <div style={{ color: "var(--text-dim)" }}>{label?.slice(0, 10)}</div>
      <div className="mono mt-1" style={{ color: "var(--text)" }}>
        {fmtUsd(v)}
      </div>
      <div className="mono" style={{ color: dd < 0 ? "var(--red)" : "var(--green)" }}>
        DD: {dd.toFixed(1)}%
      </div>
    </div>
  );
}

export function EquityCurveChart({ data, initialCapital, height = 200 }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-xl"
           style={{ height, background: "var(--bg)", color: "var(--text-muted)", fontSize: 13 }}>
        Run a backtest to see the equity curve
      </div>
    );
  }

  const finalValue = data[data.length - 1]?.v ?? initialCapital;
  const isProfit   = finalValue >= initialCapital;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"
                  stopColor={isProfit ? "#00e5a0" : "#ff4466"}
                  stopOpacity={0.25} />
            <stop offset="95%"
                  stopColor={isProfit ? "#00e5a0" : "#ff4466"}
                  stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2d4f" />
        <XAxis
          dataKey="t"
          tick={{ fill: "#6a82a8", fontSize: 10 }}
          tickFormatter={(v: string) => v?.slice(0, 7) ?? ""}
          interval="preserveStartEnd"
          stroke="#1e2d4f"
        />
        <YAxis
          tick={{ fill: "#6a82a8", fontSize: 10 }}
          tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
          width={56}
          stroke="#1e2d4f"
        />
        <Tooltip content={<CustomTooltip />} />
        <ReferenceLine
          y={initialCapital}
          stroke="#2a3f6f"
          strokeDasharray="4 4"
          label={{ value: "Capital", fill: "#3a4f78", fontSize: 10 }}
        />
        <Area
          type="monotone"
          dataKey="v"
          stroke={isProfit ? "#00e5a0" : "#ff4466"}
          strokeWidth={2}
          fill="url(#equityGrad)"
          dot={false}
          activeDot={{ r: 4, fill: isProfit ? "#00e5a0" : "#ff4466" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
