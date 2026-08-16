"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "@/components/ui/Sidebar";
import { Header } from "@/components/ui/Header";
import { useSymbolSearch, SearchResult } from "@/hooks/useSymbolSearch";
import { useAnalysis } from "@/hooks/useAnalysis";
import { FullAnalysisResponse } from "@/lib/api-client";
import { SignalCard } from "@/components/analysis/SignalCard";
import { fmtPct } from "@/lib/utils";

export default function ComparePage() {
  const [activeSymbol, setActiveSymbol] = useState<string>("AAPL");
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(["AAPL", "MSFT"]);
  const [comparisonData, setComparisonData] = useState<Record<string, FullAnalysisResponse>>({});

  const { query, results, searching, handleInput, clearSearch } = useSymbolSearch();

  const handleAddSymbol = (res: SearchResult) => {
    const sym = res.symbol.toUpperCase();
    if (selectedSymbols.includes(sym)) {
      clearSearch();
      return;
    }
    if (selectedSymbols.length >= 4) {
      alert("You can compare up to 4 assets at a time.");
      return;
    }
    setSelectedSymbols([...selectedSymbols, sym]);
    clearSearch();
  };

  const handleRemoveSymbol = (sym: string) => {
    setSelectedSymbols(selectedSymbols.filter((s) => s !== sym));
    setComparisonData((prev) => {
      const copy = { ...prev };
      delete copy[sym];
      return copy;
    });
  };

  const handleDataLoaded = (sym: string, data: FullAnalysisResponse) => {
    setComparisonData((prev) => ({ ...prev, [sym]: data }));
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--bg)" }}>
      <Sidebar activeSymbol={activeSymbol} onSelectSymbol={setActiveSymbol} />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header symbol={activeSymbol} onSymbolChange={setActiveSymbol} />
        <main className="flex-1 overflow-y-auto p-6 space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-[var(--text)]">Compare Assets</h1>
              <p className="text-xs text-[var(--text-dim)]">
                Compare walk-forward ML models, signal strength, and HMM/GARCH indicators side by side.
              </p>
            </div>

            {/* Add to compare search bar */}
            <div className="relative" style={{ width: 280 }}>
              <input
                type="text"
                placeholder="Search symbol to compare..."
                value={query}
                onChange={(e) => handleInput(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-lg outline-none"
                style={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  color: "var(--text)",
                }}
              />
              {searching && (
                <div className="absolute right-3 top-2.5 text-xs text-[var(--text-dim)]">…</div>
              )}
              {results.length > 0 && (
                <div className="absolute top-full mt-1 w-full rounded-lg overflow-hidden z-50 shadow-lg"
                     style={{ background: "var(--surface-high)", border: "1px solid var(--border)" }}>
                  {results.map((r) => (
                    <button
                      key={r.symbol}
                      onClick={() => handleAddSymbol(r)}
                      className="w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-opacity-50 transition-colors"
                      style={{ borderBottom: "1px solid var(--border)" }}
                    >
                      <div>
                        <div className="text-sm font-medium text-[var(--text)]">{r.symbol}</div>
                        <div className="text-[10px] text-[var(--text-dim)]">{r.name}</div>
                      </div>
                      <span className="text-[10px] uppercase font-semibold text-[var(--accent)]">{r.asset_type}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Active Compare Chips */}
          <div className="flex flex-wrap gap-2">
            {selectedSymbols.map((sym) => (
              <span
                key={sym}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold"
                style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)" }}
              >
                {sym}
                <button
                  onClick={() => handleRemoveSymbol(sym)}
                  className="hover:text-[var(--red)] outline-none text-[var(--text-dim)]"
                >
                  ✕
                </button>
              </span>
            ))}
          </div>

          {/* Parallel Signals Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
            {selectedSymbols.map((sym) => (
              <CompareCard
                key={sym}
                symbol={sym}
                onDataLoaded={handleDataLoaded}
                onRemove={() => handleRemoveSymbol(sym)}
              />
            ))}
          </div>

          {/* Comparison metrics table */}
          {selectedSymbols.length > 0 && (
            <div className="card p-5 space-y-4">
              <h2 className="text-lg font-semibold text-[var(--text)]">Metrics Matrix Comparison</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-[var(--text-dim)] text-xs font-semibold uppercase tracking-wider">
                      <th className="pb-3 w-1/5">Metric</th>
                      {selectedSymbols.map((sym) => (
                        <th key={sym} className="pb-3 text-center w-1/5">{sym}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)] text-[var(--text)]">
                    {[
                      {
                        label: "Signal Action",
                        val: (d: FullAnalysisResponse) => (
                          <span
                            className="text-xs px-2 py-0.5 rounded font-bold uppercase"
                            style={{
                              background: d.action === "BUY" ? "rgba(0,229,160,0.12)" : d.action === "SELL" ? "rgba(255,68,102,0.12)" : "rgba(255,176,32,0.12)",
                              color: d.action === "BUY" ? "var(--green)" : d.action === "SELL" ? "var(--red)" : "var(--amber)",
                            }}
                          >
                            {d.action}
                          </span>
                        )
                      },
                      {
                        label: "Model Confidence",
                        val: (d: FullAnalysisResponse) => <span className="mono font-semibold">{Math.round(d.confidence * 100)}%</span>
                      },
                      {
                        label: "Probability of Profit",
                        val: (d: FullAnalysisResponse) => <span className="mono font-semibold">{Math.round(d.prob_profit * 100)}%</span>
                      },
                      {
                        label: "RSI (14)",
                        val: (d: FullAnalysisResponse) => <span className="mono">{d.indicators?.rsi?.toFixed(1) ?? "—"}</span>
                      },
                      {
                        label: "Vol 20d",
                        val: (d: FullAnalysisResponse) => <span className="mono">{d.indicators?.vol_20d != null ? `${(d.indicators.vol_20d * 100).toFixed(1)}%` : "—"}</span>
                      },
                      {
                        label: "Walk-Forward AUC",
                        val: (d: FullAnalysisResponse) => <span className="mono font-medium">{d.walk_forward_auc?.toFixed(4) ?? "—"}</span>
                      },
                      {
                        label: "GARCH Vol Forecast",
                        val: (d: FullAnalysisResponse) => <span className="mono text-[var(--amber)]">{d.garch_vol_forecast != null ? `${(d.garch_vol_forecast * 100).toFixed(1)}%` : "—"}</span>
                      },
                      {
                        label: "HMM Market Regime",
                        val: (d: FullAnalysisResponse) => (
                          <span className="capitalize font-semibold" style={{ color: d.regime === "bull" ? "var(--green)" : d.regime === "bear" ? "var(--red)" : d.regime === "sideways" ? "var(--amber)" : "var(--text)" }}>
                            {d.regime ?? "—"}
                          </span>
                        )
                      }
                    ].map((row) => (
                      <tr key={row.label} className="hover:bg-[var(--surface-high)]/10 transition-colors">
                        <td className="py-3.5 font-medium text-[var(--text-dim)]">{row.label}</td>
                        {selectedSymbols.map((sym) => {
                          const data = comparisonData[sym];
                          return (
                            <td key={sym} className="py-3.5 text-center">
                              {data ? row.val(data) : <span className="text-[var(--text-dim)]">loading…</span>}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

interface CompareCardProps {
  symbol: string;
  onDataLoaded: (symbol: string, data: FullAnalysisResponse) => void;
  onRemove: () => void;
}

function CompareCard({ symbol, onDataLoaded, onRemove }: CompareCardProps) {
  const { data, isLoading, error } = useAnalysis({
    symbol,
    asset_type: "stock",
    timeframe: "1d",
    risk_tolerance: "moderate",
    capital: 10000,
  });

  useEffect(() => {
    if (data) {
      onDataLoaded(symbol, data);
    }
  }, [data, symbol, onDataLoaded]);

  if (isLoading) {
    return (
      <div className="card p-5 flex flex-col justify-center items-center h-48 text-xs text-[var(--text-dim)]">
        Evaluating {symbol}...
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="card p-5 flex flex-col justify-center items-center h-48 text-xs text-[var(--red)] border-[var(--red)]/30">
        <span>Failed to load {symbol}</span>
        <button onClick={onRemove} className="mt-2 text-[10px] underline hover:text-[var(--text)]">Remove</button>
      </div>
    );
  }

  return (
    <div className="relative">
      <button
        onClick={onRemove}
        className="absolute top-3 right-3 z-10 text-[var(--text-dim)] hover:text-[var(--red)] outline-none text-xs"
      >
        ✕
      </button>
      <SignalCard data={data} />
    </div>
  );
}
