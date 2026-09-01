"use client";
import { useState } from "react";

export type RiskTolerance = "conservative" | "moderate" | "aggressive";

const RISK_LABELS: Record<RiskTolerance, string> = {
  conservative: "Play it safe",
  moderate: "Balanced",
  aggressive: "Go big",
};

interface Props {
  value: RiskTolerance;
  onChange: (v: RiskTolerance) => void;
  showDescription?: boolean;
}

export function RiskSelector({ value, onChange, showDescription = true }: Props) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex rounded-lg overflow-hidden"
           style={{ border: "1px solid var(--border)" }}>
        {(["conservative", "moderate", "aggressive"] as RiskTolerance[]).map((r) => (
          <button key={r}
            onClick={() => onChange(r)}
            className="px-4 py-1.5 text-xs transition-colors"
            style={{
              background: value === r ? "var(--border-bright)" : "var(--surface)",
              color: value === r ? "var(--text)" : "var(--text-dim)",
              minWidth: 80,
            }}>
            {RISK_LABELS[r]}
          </button>
        ))}
      </div>
      {showDescription && (
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          Changes how much of your capital the model suggests risking per trade.
        </span>
      )}
    </div>
  );
}
