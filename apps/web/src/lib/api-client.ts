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
export interface OHLCVResponse { symbol: string; interval: string; bars: OHLCVBar[]; count: number; currency: string; }

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
  currency: string;
  regime?: "bull" | "bear" | "sideways" | null;
  regime_confidence?: number | null;
  garch_vol_forecast?: number | null;
}

export interface TokenResponse { access_token: string; token_type: string; expires_in: number; }
export interface UserResponse  { id: string; email: string; risk_tolerance: string; }

export interface BacktestSummary {
  initial_capital: number;
  final_capital: number;
  total_return_pct: number;
  cagr_pct: number;
  benchmark_bh_return_pct: number;
  alpha_vs_bh_pct: number;
  n_years: number;
}

export interface BacktestRisk {
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  max_drawdown_pct: number;
  max_drawdown_detail: Record<string, unknown>;
  annualised_volatility_pct: number;
}

export interface BacktestTrades {
  total_trades: number;
  win_rate_pct: number;
  avg_win_usd: number;
  avg_loss_usd: number;
  profit_factor: number;
  avg_hold_bars: number;
  total_commission_usd: number;
  total_slippage_usd: number;
  cost_drag_pct: number;
}

export interface EquityCurvePoint {
  t: string;
  v: number;
  dd: number;
}

export interface TradeLogEntry {
  entry: string;
  exit: string;
  entry_price: number;
  exit_price: number;
  pnl_net: number;
  exit_reason: string;
  entry_prob: number;
  bars_held: number;
}

export interface BacktestAssessment {
  is_viable: boolean;
  warnings: string[];
}

export interface BacktestResult {
  summary: BacktestSummary;
  risk: BacktestRisk;
  trades: BacktestTrades;
  equity_curve: EquityCurvePoint[];
  trade_log: TradeLogEntry[];
  assessment: BacktestAssessment;
}

export interface BacktestRequest {
  symbol: string; timeframe?: string;
  start_date: string; end_date: string;
  initial_capital?: number;
  risk_tolerance?: "conservative" | "moderate" | "aggressive";
  slippage_bps?: number; commission_pct?: number;
}

export interface ModelInfoResponse {
  symbol: string;
  timeframe: string;
  version: string;
  trained_at: string;
  prediction_horizon: number;
  profit_threshold: number;
  n_features: number;
  feature_names: string[];
  feature_importances: Record<string, number> | null;
  mean_auc: number | null;
  std_auc: number | null;
  mean_brier: number | null;
  n_folds: number | null;
  model_age_days: number;
  staleness_warning: boolean;
}

// ── API surface ───────────────────────────────────────────────────────────────
export const api = {
  analysis: {
    analyze: (data: AnalysisRequest) =>
      request<FullAnalysisResponse>("/analysis/analyze", {
        method: "POST", body: JSON.stringify(data),
      }),
    backtest: (data: BacktestRequest) =>
      request<BacktestResult>("/analysis/backtest", {
        method: "POST", body: JSON.stringify(data),
      }),
    modelInfo: (symbol: string, timeframe = "1d") =>
      request<ModelInfoResponse>(`/analysis/model-info?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`),
  },
  market: {
    ohlcv: (symbol: string, interval = "1d", days = 1825) =>
      request<OHLCVResponse>(`/market/ohlcv?symbol=${symbol}&interval=${interval}&days=${days}`),
    search: (q: string) =>
      request<{ symbol: string; name: string; asset_type: string; currency: string }[]>(
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
    signalsAccuracy: (symbol?: string, days = 90, minConfidence = 0.0) => {
      let url = `/portfolio/signals/accuracy?days=${days}&min_confidence=${minConfidence}`;
      if (symbol) {
        url += `&symbol=${encodeURIComponent(symbol)}`;
      }
      return request<SignalAccuracyResponse>(url);
    },
  },
  watchlist: {
    get: () => request<WatchlistItemResponse[]>("/watchlist"),
    add: (data: { symbol: string; notes?: string }) =>
      request<WatchlistItemResponse>("/watchlist", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    remove: (assetId: string) =>
      request<{ status: string }>(`/watchlist/${assetId}`, {
        method: "DELETE",
      }),
  },
  alerts: {
    get: () => request<AlertSubscriptionResponse[]>("/alerts"),
    subscribe: (symbol: string, isActive = true) =>
      request<AlertSubscriptionResponse>("/alerts", {
        method: "POST",
        body: JSON.stringify({ symbol, is_active: isActive }),
      }),
    unsubscribe: (symbol: string) =>
      request<{ status: string }>(`/alerts/${symbol}`, {
        method: "DELETE",
      }),
  },
};

export interface AlertSubscriptionResponse {
  id: string;
  symbol: string;
  name: string;
  is_active: boolean;
}

export interface WatchlistItemResponse {
  id: string;
  asset_id: string;
  symbol: string;
  name: string;
  asset_type: string;
  currency: string;
  current_price: number | null;
  added_at: string;
  notes: string | null;
}

export interface SignalAccuracyDetail {
  id: string;
  symbol: string;
  action: string;
  created_at: string;
  prob_profit: number | null;
  actual_return_pct: number | null;
  correct: boolean | null;
  resolved: boolean;
}

export interface ConfidenceBucket {
  bin: string;
  count: number;
  correct: number;
  accuracy_pct: number;
}

export interface SignalAccuracyResponse {
  total_signals_evaluated: number;
  correct_count: number;
  accuracy_pct: number;
  buy_accuracy_pct: number;
  buy_count: number;
  sell_accuracy_pct: number;
  sell_count: number;
  confidence_buckets: ConfidenceBucket[];
  most_recent_10: SignalAccuracyDetail[];
}

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
