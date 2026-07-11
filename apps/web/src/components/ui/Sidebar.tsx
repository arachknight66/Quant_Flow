"use client";
import { useState } from "react";
import { cn } from "@/lib/utils";

const PRESET_SYMBOLS = [
  { symbol: "AAPL",   name: "Apple Inc.",        type: "stock"  },
  { symbol: "MSFT",   name: "Microsoft",          type: "stock"  },
  { symbol: "NVDA",   name: "NVIDIA",             type: "stock"  },
  { symbol: "TSLA",   name: "Tesla",              type: "stock"  },
  { symbol: "AMZN",   name: "Amazon",             type: "stock"  },
  { symbol: "BTC-USD",name: "Bitcoin",            type: "crypto" },
  { symbol: "ETH-USD",name: "Ethereum",           type: "crypto" },
  { symbol: "SOL-USD",name: "Solana",             type: "crypto" },
];

interface Props {
  activeSymbol: string;
  onSelectSymbol: (s: string) => void;
}

export function Sidebar({ activeSymbol, onSelectSymbol }: Props) {
  const [filter, setFilter] = useState<"all"|"stock"|"crypto">("all");

  const filtered = PRESET_SYMBOLS.filter(
    (s) => filter === "all" || s.type === filter
  );

  return (
    <aside style={{ width: 220, background: "var(--surface)", borderRight: "1px solid var(--border)" }}
           className="flex flex-col h-screen flex-shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-2 px-4 py-5"
           style={{ borderBottom: "1px solid var(--border)" }}>
        <div style={{ width: 28, height: 28, background: "var(--accent)",
                      borderRadius: 6, flexShrink: 0 }} />
        <span className="font-semibold text-sm tracking-wide"
              style={{ color: "var(--text)" }}>QuantPlatform</span>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 px-3 pt-4 pb-2">
        {(["all","stock","crypto"] as const).map((f) => (
          <button key={f}
            onClick={() => setFilter(f)}
            className="text-xs px-2 py-1 rounded-md flex-1 transition-colors"
            style={{
              background: filter === f ? "var(--border-bright)" : "transparent",
              color: filter === f ? "var(--text)" : "var(--text-dim)",
              border: "1px solid " + (filter === f ? "var(--border-bright)" : "transparent"),
            }}>
            {f === "all" ? "All" : f === "stock" ? "Stocks" : "Crypto"}
          </button>
        ))}
      </div>

      {/* Symbol list */}
      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {filtered.map(({ symbol, name, type }) => (
          <button key={symbol}
            onClick={() => onSelectSymbol(symbol)}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left
                       transition-colors mb-0.5"
            style={{
              background: activeSymbol === symbol ? "var(--border)" : "transparent",
              borderLeft: activeSymbol === symbol
                ? "2px solid var(--accent)" : "2px solid transparent",
            }}>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium truncate"
                   style={{ color: activeSymbol === symbol ? "var(--accent)" : "var(--text)" }}>
                {symbol}
              </div>
              <div className="text-xs truncate" style={{ color: "var(--text-dim)" }}>
                {name}
              </div>
            </div>
            <span className="text-xs px-1.5 py-0.5 rounded"
                  style={{
                    background: type === "crypto" ? "rgba(0,229,160,0.1)" : "rgba(0,212,255,0.1)",
                    color: type === "crypto" ? "var(--green)" : "var(--accent)",
                    fontSize: 9, letterSpacing: "0.05em",
                  }}>
              {type === "crypto" ? "DEFI" : "EQ"}
            </span>
          </button>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3" style={{ borderTop: "1px solid var(--border)" }}>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Not financial advice.
        </p>
      </div>
    </aside>
  );
}
