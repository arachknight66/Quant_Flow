"use client";
import { useRealtimePrice } from "@/hooks/useRealtimePrice";
import { fmtUsd, fmtPct, signColor } from "@/lib/utils";
import { useSymbolSearch, SearchResult } from "@/hooks/useSymbolSearch";
import { useAuthStore } from "@/store/auth";
import { api } from "@/lib/api-client";
import { useRouter } from "next/navigation";
import Link from "next/link";

interface Props {
  symbol: string;
  onSymbolChange: (s: string) => void;
}

export function Header({ symbol, onSymbolChange }: Props) {
  const { query, results, searching, handleInput, clearSearch } = useSymbolSearch();
  const { data: livePrice } = useRealtimePrice(symbol);
  const { isAuthenticated, user } = useAuthStore();
  const router = useRouter();

  const handleLogout = async () => {
    try {
      await api.auth.logout();
    } catch {
      // ignore
    }
    useAuthStore.getState().clearAuth();
    router.push("/");
  };

  const selectResult = (s: SearchResult) => {
    onSymbolChange(s.symbol);
    clearSearch();
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

      {/* Auth UI */}
      <div className="flex items-center gap-3">
        {isAuthenticated && user ? (
          <>
            <span className="text-xs" style={{ color: "var(--text-dim)" }}>
              {user.email}
            </span>
            <button
              onClick={handleLogout}
              className="text-xs px-3 py-1.5 rounded-md transition-colors"
              style={{
                background: "var(--surface-high)",
                border: "1px solid var(--border)",
                color: "var(--text-dim)",
              }}
            >
              Log out
            </button>
          </>
        ) : (
          <Link
            href="/login"
            className="text-xs px-3 py-1.5 rounded-md font-medium transition-colors"
            style={{
              background: "var(--accent)",
              color: "#000",
            }}
          >
            Log in
          </Link>
        )}
      </div>

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
                <div className="ml-auto flex items-center gap-2">
                  <span className="text-xs" style={{ color: "var(--accent)" }}>
                    {r.asset_type}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded uppercase font-semibold text-xs"
                        style={{ color: "var(--text-muted)", border: "1px solid var(--border)", fontSize: "10px" }}>
                    {r.currency}
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </header>
  );
}
