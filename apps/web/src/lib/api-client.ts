// apps/web/src/lib/api-client.ts
/**
 * Type-safe API client.
 * All backend calls go through this — never fetch() directly from components.
 *
 * Design decisions:
 * - Centralized error handling
 * - Automatic token injection
 * - Request/response type safety
 * - Easy to mock in tests
 */
import { useAuthStore } from "@/store/auth";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = useAuthStore.getState().accessToken;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      body.detail ?? `HTTP ${response.status}`,
      body
    );
  }

  return response.json();
}

export const api = {
  analysis: {
    analyze: (data: AnalysisRequest) =>
      request<FullAnalysisResponse>("/analysis/analyze", {
        method: "POST",
        body: JSON.stringify(data),
      }),

    backtest: (data: BacktestRequest) =>
      request<BacktestResults>("/analysis/backtest", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  },

  market: {
    ohlcv: (symbol: string, interval: string, days: number) =>
      request<OHLCVResponse>(`/market/ohlcv?symbol=${symbol}&interval=${interval}&days=${days}`),

    search: (query: string) =>
      request<AssetSearchResult[]>(`/market/search?q=${encodeURIComponent(query)}`),
  },

  auth: {
    login: (email: string, password: string) =>
      request<TokenResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),

    register: (email: string, password: string) =>
      request<UserResponse>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),

    refresh: () => request<TokenResponse>("/auth/refresh", { method: "POST" }),
  },
};

// Types (shared with backend via OpenAPI code generation in production)
export interface AnalysisRequest {
  symbol: string;
  asset_type: "stock" | "crypto";
  timeframe: string;
  risk_tolerance: "conservative" | "moderate" | "aggressive";
  capital?: number;
  lookback_days?: number;
}

export interface FullAnalysisResponse {
  symbol: string;
  current_price: number;
  price_change_24h_pct: number;
  action: "BUY" | "HOLD" | "SELL";
  confidence: number;
  prob_profit: number;
  expected_return_lo: number;
  expected_return_hi: number;
  var_95: number;
  indicators: {
    rsi: number | null;
    macd: number | null;
    macd_hist: number | null;
    bb_pct_b: number | null;
    atr_pct: number | null;
    vol_20d: number | null;
  };
  position_sizing: PositionSizing | null;
  model_version: string;
  warnings: string[];
  analysis_timestamp: string;
}

export interface PositionSizing {
  position_value_usd: number;
  allocation_pct: number;
  n_shares: number;
  stop_loss_price: number;
  take_profit_price: number;
  risk_reward_ratio: number;
  kelly_fraction_applied: number;
}