/**
 * Type-safe API client — all backend calls go through here.
 * Never fetch() directly from components.
 */
import { useAuthStore } from "@/store/auth";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${BASE_URL}${endpoint}`, { ...options, headers });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail ?? `HTTP ${response.status}`, body);
  }
  return response.json();
}

// ── Types ──────────────────────────────────────────────────────────────────────
export interface OHLCVBar { t: string; o: number; h: number; l: number; c: number; v: number; }
export interface OHLCVResponse { symbol: string; interval: string; bars: OHLCVBar[]; count: number; }

export interface AnalysisRequest {
  symbol: string;
  asset_type?: string;
  timeframe?: string;
  risk_tolerance?: "conservative" | "moderate" | "aggressive";
  capital?: number;
  lookback_days?: number;
}

export interface IndicatorValues {
  rsi: number | null;
  macd: number | null;
  macd_hist: number | null;
  bb_pct_b: number | null;
  bb_upper: number | null;
  bb_middle: number | null;
  bb_lower: number | null;
  atr: number | null;
  atr_pct: number | null;
  vol_20d: number | null;
  momentum_10: number | null;
}

export interface PositionSizing {
  position_value_usd: number;
  allocation_pct: number;
  n_shares: number;
  stop_loss_price: number;
  take_profit_price: number;
  risk_amount_usd: number;
  risk_reward_ratio: number;
  kelly_fraction_full: number;
  kelly_fraction_applied: number;
}

export interface FullAnalysisResponse {
  symbol: string;
  asset_type: string;
  timeframe: string;
  current_price: number;
  price_change_24h_pct: number;
  action: "BUY" | "HOLD" | "SELL";
  confidence: number;
  prob_profit: number;
  expected_return_lo: number;
  expected_return_hi: number;
  var_95: number;
  indicators: IndicatorValues;
  position_sizing: PositionSizing | null;
  model_version: string;
  walk_forward_auc: number | null;
  backtest_sharpe: number | null;
  analysis_timestamp: string;
  warnings: string[];
}

export interface TokenResponse { access_token: string; token_type: string; expires_in: number; }
export interface UserResponse  { id: string; email: string; risk_tolerance: string; }

export interface BacktestRequest {
  symbol: string; timeframe?: string;
  start_date: string; end_date: string;
  initial_capital?: number;
  risk_tolerance?: "conservative" | "moderate" | "aggressive";
  slippage_bps?: number; commission_pct?: number;
}

// ── API surface ───────────────────────────────────────────────────────────────
export const api = {
  analysis: {
    analyze: (data: AnalysisRequest) =>
      request<FullAnalysisResponse>("/analysis/analyze", {
        method: "POST", body: JSON.stringify(data),
      }),
    backtest: (data: BacktestRequest) =>
      request<unknown>("/analysis/backtest", {
        method: "POST", body: JSON.stringify(data),
      }),
  },
  market: {
    ohlcv: (symbol: string, interval = "1d", days = 365) =>
      request<OHLCVResponse>(`/market/ohlcv?symbol=${symbol}&interval=${interval}&days=${days}`),
    search: (q: string) =>
      request<{ symbol: string; name: string; asset_type: string }[]>(
        `/market/search?q=${encodeURIComponent(q)}`
      ),
    health: () => request<{ status: string; ohlcv_bars_in_db: number }>("/market/health/data"),
  },
  auth: {
    login: (email: string, password: string) =>
      request<TokenResponse>("/auth/login", {
        method: "POST", body: JSON.stringify({ email, password }),
      }),
    register: (email: string, password: string) =>
      request<UserResponse>("/auth/register", {
        method: "POST", body: JSON.stringify({ email, password }),
      }),
    me: () => request<UserResponse>("/auth/me"),
    logout: () => request<void>("/auth/logout", { method: "DELETE" }),
  },
  portfolio: {
    summary: () => request<PortfolioSummary>("/portfolio/summary"),
    positions: () => request<Position[]>("/portfolio/positions"),
    open: (data: { signal_id: string; quantity: number; entry_price: number; stop_loss?: number; take_profit?: number; notes?: string }) =>
      request<{ status: string; position_id: string; new_cash_balance: number }>("/portfolio/positions/open", {
        method: "POST", body: JSON.stringify(data),
      }),
    close: (id: string, data: { exit_price: number; exit_reason?: string }) =>
      request<{ status: string; position_id: string; pnl_usd: number; new_cash_balance: number }>(`/portfolio/positions/${id}/close`, {
        method: "POST", body: JSON.stringify(data),
      }),
    signalsHistory: (limit = 50) => request<SignalHistoryItem[]>(`/portfolio/signals/history?limit=${limit}`),
  },
};

export interface PortfolioSummary {
  total_value_usd: number;
  cash_usd: number;
  invested_usd: number;
  total_pnl_usd: number;
  total_pnl_pct: number;
  n_positions: number;
}

export interface Position {
  id: string;
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  is_open: boolean;
  open_date: string;
  close_date: string | null;
  stop_loss: number | null;
  take_profit: number | null;
  notes: string | null;
}

export interface SignalHistoryItem {
  id: string;
  action: string;
  confidence: number;
  prob_profit: number;
  model_version: string;
  created_at: string;
}
