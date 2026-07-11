"use client";
import { PositionSizing } from "@/lib/api-client";
import { fmtUsd, fmtPct, fmt } from "@/lib/utils";

interface Props {
  sizing: PositionSizing | null;
  action: "BUY" | "HOLD" | "SELL";
  currentPrice: number;
}

export function PositionSizingCard({ sizing, action, currentPrice }: Props) {
  if (action !== "BUY" || !sizing) {
    return (
      <div className="card p-5">
        <h2 className="text-sm font-medium mb-3" style={{ color: "var(--text-dim)" }}>
          Position Sizing
        </h2>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          {action === "HOLD" ? "No position recommended — model is neutral."
           : action === "SELL" ? "Signal is SELL — no new position."
           : "Set capital in the analysis request to see sizing."}
        </p>
      </div>
    );
  }

  const rrColor = sizing.risk_reward_ratio >= 2.0 ? "var(--green)"
    : sizing.risk_reward_ratio >= 1.5 ? "var(--amber)" : "var(--red)";

  const rows = [
    { label: "Position value",    value: fmtUsd(sizing.position_value_usd)               },
    { label: "Portfolio %",       value: `${fmt(sizing.allocation_pct, 1)}%`              },
    { label: "Shares / units",    value: fmt(sizing.n_shares, 4)                          },
    { label: "Risk amount",       value: fmtUsd(sizing.risk_amount_usd)                   },
    { label: "Stop loss",         value: fmtUsd(sizing.stop_loss_price),   color: "var(--red)"   },
    { label: "Take profit",       value: fmtUsd(sizing.take_profit_price), color: "var(--green)" },
    { label: "Risk / Reward",     value: `1 : ${fmt(sizing.risk_reward_ratio, 2)}`, color: rrColor },
    { label: "Kelly (full)",      value: fmtPct(sizing.kelly_fraction_full * 100, 2)      },
    { label: "Kelly (applied ¼)", value: fmtPct(sizing.kelly_fraction_applied * 100, 2)  },
  ];

  return (
    <div className="card p-5 flex flex-col gap-4">
      <h2 className="text-sm font-medium" style={{ color: "var(--text-dim)" }}>
        Position Sizing
      </h2>

      {/* Visual size bar */}
      <div>
        <div className="flex justify-between text-xs mb-1"
             style={{ color: "var(--text-dim)" }}>
          <span>Allocation</span>
          <span className="mono" style={{ color: "var(--green)" }}>
            {fmt(sizing.allocation_pct, 1)}%
          </span>
        </div>
        <div className="rounded-full" style={{ height: 8, background: "var(--border)" }}>
          <div className="h-full rounded-full"
               style={{ width: `${Math.min(sizing.allocation_pct, 100)}%`,
                        background: "var(--green)" }} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {rows.map(({ label, value, color }) => (
          <div key={label} className="rounded-lg px-3 py-2"
               style={{ background: "var(--bg)" }}>
            <div className="text-xs mb-0.5" style={{ color: "var(--text-dim)" }}>
              {label}
            </div>
            <div className="text-xs font-semibold mono"
                 style={{ color: color ?? "var(--text)" }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        ¼-Kelly applied. Stop loss at 2×ATR below entry. This is not financial advice.
      </p>
    </div>
  );
}
