"use client";
import { useState, useRef, useEffect } from "react";
import { useRealtimePrice } from "@/hooks/useRealtimePrice";
import { fmtUsd, fmtPct, signColor } from "@/lib/utils";

interface SearchResult { symbol: string; name: string; asset_type: string; }

interface Props {
  symbol: string;
  onSymbolChange: (s: string) => void;
}

export function Header({ symbol, onSymbolChange }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const { data: livePrice } = useRealtimePrice(symbol);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const search = async (q: string) => {
    if (!q.trim() || q.length < 1) { setResults([]); return; }
    setSearching(true);
    try {
      const r = await fetch(
        `/api/v1/market/search?q=${encodeURIComponent(q.toUpperCase())}`
      );
      if (r.ok) setResults(await r.json());
    } catch { /* ignore */ }
    setSearching(false);
  };

  const handleInput = (v: string) => {
    setQuery(v);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => search(v), 300);
  };

  const selectResult = (s: SearchResult) => {
    onSymbolChange(s.symbol);
    setQuery("");
    setResults([]);
  };

  return (
    <header className="flex items-center gap-6 px-6 py-4 flex-shrink-0"
            style={{ borderBottom: "1px solid var(--border)",
                     background: "var(--surface)" }}>
      {/* Live price */}
      <div className="flex items-baseline gap-3">
        <span className="text-xl font-semibold mono"
              style={{ color: "var(--text)" }}>
          {symbol}
        </span>
        {livePrice ? (
          <>
            <span className="text-lg mono" style={{ color: "var(--text)" }}>
              {fmtUsd(livePrice.price)}
            </span>
            <span className="text-sm mono"
                  style={{ color: signColor(livePrice.change_pct) }}>
              {fmtPct(livePrice.change_pct)}
            </span>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>LIVE</span>
          </>
        ) : (
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>
            connecting…
          </span>
        )}
      </div>

      <div className="flex-1" />

      {/* Search box */}
      <div className="relative" style={{ width: 280 }}>
        <input
          type="text"
          placeholder="Search symbol…"
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          className="w-full px-3 py-2 text-sm rounded-lg outline-none"
          style={{
            background: "var(--bg)",
            border: "1px solid var(--border)",
            color: "var(--text)",
          }}
        />
        {searching && (
          <div className="absolute right-3 top-2.5 text-xs"
               style={{ color: "var(--text-dim)" }}>…</div>
        )}
        {results.length > 0 && (
          <div className="absolute top-full mt-1 w-full rounded-lg overflow-hidden z-50"
               style={{ background: "var(--surface-high)",
                        border: "1px solid var(--border)" }}>
            {results.map((r) => (
              <button key={r.symbol}
                onClick={() => selectResult(r)}
                className="w-full flex items-center gap-3 px-3 py-2.5 text-left
                           hover:bg-opacity-50 transition-colors"
                style={{ borderBottom: "1px solid var(--border)" }}>
                <div>
                  <div className="text-sm font-medium" style={{ color: "var(--text)" }}>
                    {r.symbol}
                  </div>
                  <div className="text-xs" style={{ color: "var(--text-dim)" }}>{r.name}</div>
                </div>
                <span className="ml-auto text-xs" style={{ color: "var(--accent)" }}>
                  {r.asset_type}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </header>
  );
}
