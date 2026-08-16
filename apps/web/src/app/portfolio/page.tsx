"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/ui/Sidebar";
import { Header } from "@/components/ui/Header";
import { api, PortfolioSummary, Position, SignalHistoryItem } from "@/lib/api-client";
import { fmtUsd, fmtPct, signColor } from "@/lib/utils";
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from "recharts";
import { SignalAccuracyCard } from "@/components/portfolio/SignalAccuracyCard";

const CHART_COLORS = [
  "#00d4ff", // var(--accent)
  "#00e5a0", // var(--green)
  "#ffb020", // var(--amber)
  "#ff4466", // var(--red)
  "#8884d8",
  "#82ca9d",
  "#a4de6c",
  "#d0ed57",
  "#83a6ed",
];

export default function PortfolioPage() {
  const [symbol, setSymbol] = useState<string>("AAPL");
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [signals, setSignals] = useState<SignalHistoryItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [closingId, setClosingId] = useState<string | null>(null);
  const [exitPrice, setExitPrice] = useState<string>("");
  const [exitReason, setExitReason] = useState<string>("");

  const fetchData = async () => {
    try {
      setLoading(true);
      const [sumData, posData, sigData] = await Promise.all([
        api.portfolio.summary(),
        api.portfolio.positions(),
        api.portfolio.signalsHistory(15),
      ]);
      setSummary(sumData);
      setPositions(posData);
      setSignals(sigData);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Failed to load portfolio data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleClosePosition = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!closingId || !exitPrice) return;
    try {
      await api.portfolio.close(closingId, {
        exit_price: parseFloat(exitPrice),
        exit_reason: exitReason || undefined,
      });
      setClosingId(null);
      setExitPrice("");
      setExitReason("");
      await fetchData();
    } catch (err: any) {
      alert(err?.message || "Failed to close position");
    }
  };

  const openPositions = positions.filter((p) => p.is_open);
  const closedPositions = positions.filter((p) => !p.is_open);

  // Allocation Pie Chart Data
  const allocationData = [
    { name: "Cash", value: summary?.cash_usd || 0 },
    ...openPositions.map((pos) => ({
      name: pos.symbol,
      value: pos.quantity * pos.avg_entry_price,
    })),
  ].filter((item) => item.value > 0);

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--bg)" }}>
      <Sidebar activeSymbol={symbol} onSelectSymbol={setSymbol} />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header symbol={symbol} onSymbolChange={setSymbol} />
        <main className="flex-1 overflow-y-auto p-6 space-y-6">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold tracking-tight text-[var(--text)]">Portfolio & Positions</h1>
            <button
              onClick={fetchData}
              className="text-xs px-3 py-1.5 rounded-md transition-colors bg-[var(--surface-high)] border border-[var(--border)] text-[var(--text)] hover:bg-[var(--border)]"
            >
              Refresh
            </button>
          </div>

          {error && (
            <div className="p-4 rounded-lg bg-red-950/30 border border-red-500/50 text-[var(--red)] text-sm">
              {error}
            </div>
          )}

          {loading && !summary ? (
            <div className="flex items-center justify-center h-64 text-[var(--text-dim)]">
              Loading portfolio data...
            </div>
          ) : (
            <>
              {/* Summary Cards and Pie Chart */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 grid grid-cols-2 gap-4">
                  <div className="card p-5 flex flex-col justify-between">
                    <span className="text-xs font-semibold text-[var(--text-dim)] uppercase tracking-wider">
                      Net Asset Value
                    </span>
                    <span className="text-3xl font-bold text-[var(--text)] mt-2 mono">
                      {summary ? fmtUsd(summary.total_value_usd) : "$0.00"}
                    </span>
                  </div>
                  <div className="card p-5 flex flex-col justify-between">
                    <span className="text-xs font-semibold text-[var(--text-dim)] uppercase tracking-wider">
                      Cash Balance
                    </span>
                    <span className="text-3xl font-bold text-[var(--text)] mt-2 mono">
                      {summary ? fmtUsd(summary.cash_usd) : "$0.00"}
                    </span>
                  </div>
                  <div className="card p-5 flex flex-col justify-between">
                    <span className="text-xs font-semibold text-[var(--text-dim)] uppercase tracking-wider">
                      Invested Capital
                    </span>
                    <span className="text-3xl font-bold text-[var(--text)] mt-2 mono">
                      {summary ? fmtUsd(summary.invested_usd) : "$0.00"}
                    </span>
                  </div>
                  <div className="card p-5 flex flex-col justify-between">
                    <span className="text-xs font-semibold text-[var(--text-dim)] uppercase tracking-wider">
                      Total P&L
                    </span>
                    <div className="flex items-baseline gap-2 mt-2">
                      <span
                        className="text-3xl font-bold mono"
                        style={{ color: summary ? signColor(summary.total_pnl_usd) : "var(--text)" }}
                      >
                        {summary ? fmtUsd(summary.total_pnl_usd) : "$0.00"}
                      </span>
                      <span
                        className="text-sm font-medium mono"
                        style={{ color: summary ? signColor(summary.total_pnl_pct) : "var(--text)" }}
                      >
                        ({summary ? fmtPct(summary.total_pnl_pct) : "0.00%"})
                      </span>
                    </div>
                  </div>
                </div>

                <div className="card p-5 flex flex-col h-64 lg:h-auto justify-between">
                  <span className="text-xs font-semibold text-[var(--text-dim)] uppercase tracking-wider mb-2">
                    Asset Allocation
                  </span>
                  <div className="flex-1 w-full h-full min-h-[160px]">
                    {allocationData.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={allocationData}
                            cx="50%"
                            cy="50%"
                            innerRadius={45}
                            outerRadius={65}
                            paddingAngle={4}
                            dataKey="value"
                          >
                            {allocationData.map((entry, index) => (
                              <Cell
                                key={`cell-${index}`}
                                fill={entry.name === "Cash" ? "var(--border-bright)" : CHART_COLORS[index % CHART_COLORS.length]}
                              />
                            ))}
                          </Pie>
                          <Tooltip
                            contentStyle={{
                              background: "var(--surface-high)",
                              border: "1px solid var(--border)",
                              borderRadius: "6px",
                              color: "var(--text)",
                            }}
                            formatter={(value: number) => fmtUsd(value)}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex items-center justify-center h-full text-xs text-[var(--text-dim)]">
                        No active allocations
                      </div>
                    )}
                  </div>
                  {allocationData.length > 0 && (
                    <div className="flex flex-wrap gap-2 text-[10px] mt-2 justify-center">
                      {allocationData.map((item, index) => (
                        <div key={item.name} className="flex items-center gap-1">
                          <span
                            className="w-2 h-2 rounded-full"
                            style={{
                              backgroundColor:
                                item.name === "Cash" ? "var(--border-bright)" : CHART_COLORS[index % CHART_COLORS.length],
                            }}
                          />
                          <span className="text-[var(--text-dim)]">{item.name}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Signal Accuracy Tracker Card */}
              <SignalAccuracyCard />

              {/* Active Positions Table */}
              <div className="card p-5 space-y-4">
                <h2 className="text-lg font-semibold text-[var(--text)]">Active Positions</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm border-collapse">
                    <thead>
                      <tr className="border-b border-[var(--border)] text-[var(--text-dim)] text-xs font-semibold uppercase tracking-wider">
                        <th className="pb-3">Symbol</th>
                        <th className="pb-3 text-right">Quantity</th>
                        <th className="pb-3 text-right">Avg Entry</th>
                        <th className="pb-3 text-right">Total Cost</th>
                        <th className="pb-3 text-right">Unrealised P&L</th>
                        <th className="pb-3 text-center">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border)]">
                      {openPositions.length > 0 ? (
                        openPositions.map((pos) => {
                          const cost = pos.quantity * pos.avg_entry_price;
                          return (
                            <tr key={pos.id} className="text-[var(--text)] hover:bg-[var(--surface-high)]/30 transition-colors">
                              <td className="py-3 font-semibold text-[var(--accent)]">{pos.symbol}</td>
                              <td className="py-3 text-right mono">{pos.quantity}</td>
                              <td className="py-3 text-right mono">{fmtUsd(pos.avg_entry_price)}</td>
                              <td className="py-3 text-right mono">{fmtUsd(cost)}</td>
                              <td className="py-3 text-right mono" style={{ color: "var(--green)" }}>
                                --
                              </td>
                              <td className="py-3 text-center">
                                <button
                                  onClick={() => {
                                    setClosingId(pos.id);
                                    setExitPrice(pos.avg_entry_price.toString());
                                  }}
                                  className="text-xs px-2.5 py-1 rounded bg-[var(--red)]/15 border border-[var(--red)]/30 text-[var(--red)] hover:bg-[var(--red)]/35 transition-colors"
                                >
                                  Close
                                </button>
                              </td>
                            </tr>
                          );
                        })
                      ) : (
                        <tr>
                          <td colSpan={6} className="py-6 text-center text-xs text-[var(--text-dim)]">
                            No active positions. Open a position from the Analysis Dashboard.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Close Position Modal Dialog Overlay */}
              {closingId && (
                <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                  <div className="card p-6 w-full max-w-sm space-y-4 shadow-xl" style={{ backgroundColor: "var(--surface)" }}>
                    <h3 className="text-lg font-semibold text-[var(--text)]">Close Paper Position</h3>
                    <form onSubmit={handleClosePosition} className="space-y-4">
                      <div className="space-y-1">
                        <label className="text-xs text-[var(--text-dim)] block">Exit Price (USD)</label>
                        <input
                          type="number"
                          step="any"
                          required
                          value={exitPrice}
                          onChange={(e) => setExitPrice(e.target.value)}
                          className="w-full px-3 py-2 text-sm rounded outline-none"
                          style={{
                            background: "var(--bg)",
                            border: "1px solid var(--border)",
                            color: "var(--text)",
                          }}
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-xs text-[var(--text-dim)] block">Exit Reason / Notes</label>
                        <textarea
                          rows={2}
                          value={exitReason}
                          onChange={(e) => setExitReason(e.target.value)}
                          className="w-full px-3 py-2 text-sm rounded outline-none resize-none"
                          style={{
                            background: "var(--bg)",
                            border: "1px solid var(--border)",
                            color: "var(--text)",
                          }}
                          placeholder="e.g. Stop hit, profit target achieved"
                        />
                      </div>
                      <div className="flex gap-3 justify-end pt-2">
                        <button
                          type="button"
                          onClick={() => setClosingId(null)}
                          className="text-xs px-3 py-2 rounded transition-colors text-[var(--text)] bg-[var(--surface-high)] border border-[var(--border)] hover:bg-[var(--border)]"
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          className="text-xs px-3 py-2 rounded transition-colors text-white bg-[var(--red)] hover:bg-[var(--red)]/80"
                        >
                          Confirm Close
                        </button>
                      </div>
                    </form>
                  </div>
                </div>
              )}

              {/* Realised Trade History Table */}
              <div className="card p-5 space-y-4">
                <h2 className="text-lg font-semibold text-[var(--text)]">Realised Trade History</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm border-collapse">
                    <thead>
                      <tr className="border-b border-[var(--border)] text-[var(--text-dim)] text-xs font-semibold uppercase tracking-wider">
                        <th className="pb-3">Symbol</th>
                        <th className="pb-3 text-right">Quantity</th>
                        <th className="pb-3 text-right">Avg Entry</th>
                        <th className="pb-3 text-right">Exit Price</th>
                        <th className="pb-3 text-right">Realised P&L</th>
                        <th className="pb-3 pl-4">Close Date</th>
                        <th className="pb-3">Notes</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border)]">
                      {closedPositions.length > 0 ? (
                        closedPositions.map((pos) => {
                          const cost = pos.quantity * pos.avg_entry_price;
                          const proceeds = pos.quantity * (pos.stop_loss || pos.avg_entry_price); // exit price fallback
                          const pnl = proceeds - cost;
                          return (
                            <tr key={pos.id} className="text-[var(--text)] hover:bg-[var(--surface-high)]/30 transition-colors">
                              <td className="py-3 font-semibold text-[var(--text-dim)]">{pos.symbol}</td>
                              <td className="py-3 text-right mono">{pos.quantity}</td>
                              <td className="py-3 text-right mono">{fmtUsd(pos.avg_entry_price)}</td>
                              <td className="py-3 text-right mono">--</td>
                              <td className="py-3 text-right mono">--</td>
                              <td className="py-3 pl-4 text-xs text-[var(--text-dim)]">
                                {pos.close_date ? new Date(pos.close_date).toLocaleDateString() : "--"}
                              </td>
                              <td className="py-3 text-xs text-[var(--text-dim)] truncate max-w-xs">{pos.notes || "--"}</td>
                            </tr>
                          );
                        })
                      ) : (
                        <tr>
                          <td colSpan={7} className="py-6 text-center text-xs text-[var(--text-dim)]">
                            No closed positions.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Signals History & Log */}
              <div className="card p-5 space-y-4">
                <h2 className="text-lg font-semibold text-[var(--text)]">Signals History & Log</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm border-collapse">
                    <thead>
                      <tr className="border-b border-[var(--border)] text-[var(--text-dim)] text-xs font-semibold uppercase tracking-wider">
                        <th className="pb-3">Timestamp</th>
                        <th className="pb-3">Action</th>
                        <th className="pb-3 text-right">Confidence</th>
                        <th className="pb-3 text-right">Prob Profit</th>
                        <th className="pb-3 pl-4">Model Version</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border)]">
                      {signals.length > 0 ? (
                        signals.map((sig) => (
                          <tr key={sig.id} className="text-[var(--text)] hover:bg-[var(--surface-high)]/30 transition-colors">
                            <td className="py-3 text-xs text-[var(--text-dim)]">
                              {new Date(sig.created_at).toLocaleString()}
                            </td>
                            <td className="py-3">
                              <span
                                className="text-xs px-2 py-0.5 rounded font-semibold uppercase tracking-wider"
                                style={{
                                  background:
                                    sig.action === "BUY"
                                      ? "rgba(0,229,160,0.1)"
                                      : sig.action === "SELL"
                                      ? "rgba(255,68,102,0.1)"
                                      : "rgba(106,130,168,0.1)",
                                  color:
                                    sig.action === "BUY"
                                      ? "var(--green)"
                                      : sig.action === "SELL"
                                      ? "var(--red)"
                                      : "var(--text-dim)",
                                }}
                              >
                                {sig.action}
                              </span>
                            </td>
                            <td className="py-3 text-right mono">{fmtPct(sig.confidence * 100)}</td>
                            <td className="py-3 text-right mono">{fmtPct(sig.prob_profit * 100)}</td>
                            <td className="py-3 pl-4 text-xs text-[var(--text-dim)]">{sig.model_version}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={5} className="py-6 text-center text-xs text-[var(--text-dim)]">
                            No signal history available.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
