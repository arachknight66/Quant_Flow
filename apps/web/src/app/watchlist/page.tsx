"use client";

import { useState } from "react";
import { useRequireAuth } from "@/hooks/useRequireAuth";
import { Sidebar } from "@/components/ui/Sidebar";
import { Header } from "@/components/ui/Header";
import { useSymbolSearch, SearchResult } from "@/hooks/useSymbolSearch";
import { useWatchlist, useAddWatchlistItem, useRemoveWatchlistItem } from "@/hooks/useWatchlist";
import { useAlertSubscriptions, useToggleAlertSubscription } from "@/hooks/useAlertSubscriptions";
import { useRealtimePrice } from "@/hooks/useRealtimePrice";
import { fmtUsd, fmtPct, signColor } from "@/lib/utils";

export default function WatchlistPage() {
  useRequireAuth();
  const [activeSymbol, setActiveSymbol] = useState<string>("AAPL");
  const { data: items = [], isLoading, error } = useWatchlist();
  const addMutation = useAddWatchlistItem();
  const removeMutation = useRemoveWatchlistItem();
  const { query, results, searching, handleInput, clearSearch } = useSymbolSearch();

  const { data: alertSubs = [] } = useAlertSubscriptions();
  const toggleAlertMutation = useToggleAlertSubscription();

  const handleSelectToAdd = async (result: SearchResult) => {
    try {
      await addMutation.mutateAsync({ symbol: result.symbol });
      clearSearch();
    } catch (err: any) {
      alert(err?.message || "Failed to add symbol");
    }
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--bg)" }}>
      <Sidebar activeSymbol={activeSymbol} onSelectSymbol={setActiveSymbol} />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header symbol={activeSymbol} onSymbolChange={setActiveSymbol} />
        <main className="flex-1 overflow-y-auto p-6 space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-[var(--text)]">Watchlist</h1>
              <p className="text-xs text-[var(--text-dim)]">
                Track real-time prices and receive indicators for your favorite assets.
              </p>
            </div>

            {/* Add symbol to watchlist search bar */}
            <div className="relative" style={{ width: 280 }}>
              <input
                type="text"
                placeholder="Type ticker to add (e.g. MSFT)..."
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
                      onClick={() => handleSelectToAdd(r)}
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

          {error && (
            <div className="p-4 rounded-lg bg-red-950/30 border border-red-500/50 text-[var(--red)] text-sm">
              {error.message}
            </div>
          )}

          {isLoading ? (
            <div className="flex items-center justify-center h-64 text-[var(--text-dim)] text-xs">
              Loading watchlist...
            </div>
          ) : items.length === 0 ? (
            <div className="card p-8 flex flex-col items-center gap-4 text-center">
              <div className="text-3xl">📋</div>
              <div>
                <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--text)" }}>
                  Your watchlist is empty
                </h3>
                <p className="text-xs leading-relaxed" style={{ color: "var(--text-dim)" }}>
                  Your watchlist tracks prices and alerts for assets you care about.
                  Search for a stock or crypto above to get started — try typing a ticker
                  like AAPL or BTC-USD.
                </p>
              </div>
            </div>
          ) : (
            <div className="card p-5">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-[var(--text-dim)] text-xs font-semibold uppercase tracking-wider">
                      <th className="pb-3">Symbol</th>
                      <th className="pb-3">Name</th>
                      <th className="pb-3">Asset Type</th>
                      <th className="pb-3 text-right">Price</th>
                      <th className="pb-3 text-right">Change</th>
                      <th className="pb-3 text-center">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {items.map((item) => {
                      const isAlertActive = alertSubs.some((sub) => sub.symbol === item.symbol && sub.is_active);
                      return (
                        <WatchlistItemRow
                          key={item.id}
                          item={item}
                          isAlertActive={isAlertActive}
                          onToggleAlert={() =>
                            toggleAlertMutation.mutate({ symbol: item.symbol, isActive: !isAlertActive })
                          }
                          onRemove={() => removeMutation.mutate(item.asset_id)}
                          onSelect={() => setActiveSymbol(item.symbol)}
                        />
                      );
                    })}
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

interface RowProps {
  item: any;
  isAlertActive: boolean;
  onToggleAlert: () => void;
  onRemove: () => void;
  onSelect: () => void;
}

function WatchlistItemRow({ item, isAlertActive, onToggleAlert, onRemove, onSelect }: RowProps) {
  const { data: livePrice } = useRealtimePrice(item.symbol);
  
  const displayPrice = livePrice ? livePrice.price : item.current_price;
  const displayChange = livePrice ? livePrice.change_pct : null;

  return (
    <tr className="text-[var(--text)] hover:bg-[var(--surface-high)]/30 transition-colors">
      <td className="py-4">
        <button
          onClick={onSelect}
          className="font-bold text-[var(--accent)] hover:underline outline-none text-left"
        >
          {item.symbol}
        </button>
      </td>
      <td className="py-4 text-xs text-[var(--text-dim)]">{item.name}</td>
      <td className="py-4">
        <span className="text-[10px] uppercase font-semibold text-[var(--text-dim)] border border-[var(--border)] px-1.5 py-0.5 rounded">
          {item.asset_type}
        </span>
      </td>
      <td className="py-4 text-right mono font-semibold">
        {displayPrice != null ? fmtUsd(displayPrice) : "connecting…"}
      </td>
      <td
        className="py-4 text-right mono font-medium"
        style={{ color: displayChange != null ? signColor(displayChange) : "var(--text-dim)" }}
      >
        {displayChange != null ? fmtPct(displayChange) : "—"}
      </td>
      <td className="py-4 text-center">
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={onToggleAlert}
            title={isAlertActive ? "Unsubscribe from signal email alerts" : "Subscribe to signal email alerts"}
            className={`text-xs px-2.5 py-1 rounded transition-colors ${
              isAlertActive
                ? "bg-[var(--green)]/15 border border-[var(--green)]/35 text-[var(--green)] hover:bg-[var(--green)]/30"
                : "bg-[var(--surface-high)] border border-[var(--border)] text-[var(--text-dim)] hover:bg-[var(--border)] hover:text-[var(--text)]"
            }`}
          >
            {isAlertActive ? "🔔 Active" : "🔕 Muted"}
          </button>
          <button
            onClick={onRemove}
            className="text-xs px-2.5 py-1 rounded bg-[var(--red)]/15 border border-[var(--red)]/30 text-[var(--red)] hover:bg-[var(--red)]/35 transition-colors"
          >
            Remove
          </button>
        </div>
      </td>
    </tr>
  );
}
