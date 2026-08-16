"use client";
import { useState } from "react";
import { useAnalysis, useOHLCV } from "@/hooks/useAnalysis";
import { useBacktest }        from "@/hooks/useBacktest";
import { SignalCard }         from "@/components/analysis/SignalCard";
import { ModelTransparencyPanel } from "@/components/analysis/ModelTransparencyPanel";
import { IndicatorGrid }      from "@/components/analysis/IndicatorGrid";
import { PositionSizingCard } from "@/components/analysis/PositionSizingCard";
import { CandlestickChart }   from "@/components/charts/CandlestickChart";
import { EquityCurveChart }   from "@/components/charts/EquityCurveChart";
import { fmtUsd, fmtPct, signColor } from "@/lib/utils";

interface Props { symbol: string; }

type RiskTolerance = "conservative" | "moderate" | "aggressive";

export function AnalysisPanel({ symbol }: Props) {
  const [risk, setRisk] = useState<RiskTolerance>("moderate");
  const [capital, setCapital]   = useState<string>("10000");
  const [submitted, setSubmitted] = useState(true);

  const [showBacktestParams, setShowBacktestParams] = useState(false);
  const [backtestStart, setBacktestStart] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 2);
    return d.toISOString().split("T")[0];
  });
  const [backtestEnd, setBacktestEnd] = useState(() => {
    return new Date().toISOString().split("T")[0];
  });
  const [slippage, setSlippage] = useState("5.0");
  const [commission, setCommission] = useState("0.1");

  const backtestMutation = useBacktest();

  const request = submitted ? {
    symbol,
    asset_type:     "stock",
    timeframe:      "1d",
    risk_tolerance: risk,
    capital:        capital ? parseFloat(capital) : undefined,
    lookback_days:  1825,
  } : null;

  const { data: analysis, isLoading, error, refetch } = useAnalysis(request);
  const { data: ohlcv, isLoading: ohlcvLoading } = useOHLCV(symbol, "1d", 180);

  const priceColor = analysis
    ? signColor(analysis.price_change_24h_pct) : "var(--text)";

  return (
    <div className="flex flex-col gap-6 max-w-6xl mx-auto">

      {/* Top controls */}
      <div className="flex items-center gap-4 flex-wrap">
        {/* Risk tolerance selector */}
        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: "var(--text-dim)" }}>Risk</span>
          <div className="flex rounded-lg overflow-hidden"
               style={{ border: "1px solid var(--border)" }}>
            {(["conservative","moderate","aggressive"] as RiskTolerance[]).map((r) => (
              <button key={r}
                onClick={() => setRisk(r)}
                className="px-3 py-1.5 text-xs capitalize transition-colors"
                style={{
                  background: risk === r ? "var(--border-bright)" : "var(--surface)",
                  color: risk === r ? "var(--text)" : "var(--text-dim)",
                }}>
                {r.slice(0, 4).toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {/* Capital input */}
        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: "var(--text-dim)" }}>Capital</span>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
            placeholder="10000"
            className="px-3 py-1.5 text-xs rounded-lg mono outline-none w-28"
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              color: "var(--text)",
            }}
          />
        </div>

        <button
          onClick={() => { setSubmitted(true); refetch(); }}
          disabled={isLoading}
          className="px-4 py-1.5 text-xs rounded-lg font-medium transition-opacity"
          style={{
            background: "var(--accent)",
            color: "#000",
            opacity: isLoading ? 0.6 : 1,
          }}>
          {isLoading ? "Analysing…" : "Analyse"}
        </button>

        {/* Quick price summary */}
        {analysis && (
          <div className="flex items-baseline gap-3 ml-auto">
            <span className="text-lg font-semibold mono"
                  style={{ color: "var(--text)" }}>
              {fmtUsd(analysis.current_price)}
            </span>
            <span className="text-sm mono" style={{ color: priceColor }}>
              {fmtPct(analysis.price_change_24h_pct)}
            </span>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="card p-4 flex items-center justify-between"
             style={{ borderColor: "var(--red)" }}>
          <span className="text-sm" style={{ color: "var(--red)" }}>
            {(error as Error).message}
          </span>
          <button onClick={() => refetch()}
                  className="text-xs px-3 py-1 rounded"
                  style={{ background: "var(--border)", color: "var(--text)" }}>
            Retry
          </button>
        </div>
      )}

      {/* Loading skeleton */}
      {isLoading && (
        <div className="grid grid-cols-3 gap-5">
          {[0,1,2].map((i) => (
            <div key={i} className="card animate-pulse"
                 style={{ height: 280, opacity: 0.4 }} />
          ))}
        </div>
      )}

      {/* Main grid */}
      {analysis && !isLoading && (
        <>
          {/* Candlestick chart — full width */}
          <div className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium" style={{ color: "var(--text-dim)" }}>
                {symbol} — Daily Chart (180d)
              </h2>
              <span className="text-xs mono" style={{ color: "var(--text-muted)" }}>
                {ohlcv?.count ?? 0} bars
              </span>
            </div>
            {ohlcvLoading ? (
              <div className="animate-pulse rounded-xl"
                   style={{ height: 320, background: "var(--bg)" }} />
            ) : (
              <CandlestickChart bars={ohlcv?.bars ?? []} height={320} />
            )}
          </div>

          {/* Signal + Indicators + Sizing — 3-column */}
          <div className="grid gap-5"
               style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
            <SignalCard data={analysis} />
            <IndicatorGrid
              indicators={analysis.indicators}
              currentPrice={analysis.current_price}
            />
            <PositionSizingCard
              sizing={analysis.position_sizing}
              action={analysis.action}
              currentPrice={analysis.current_price}
            />
          </div>

          {/* Model Transparency Panel */}
          <ModelTransparencyPanel symbol={symbol} timeframe="1d" />

          {/* Equity curve */}
          <div className="card p-5 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-medium" style={{ color: "var(--text-dim)" }}>
                  Backtest Equity Curve
                </h2>
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                  Evaluate historical strategy performance using walk-forward model signals
                </p>
              </div>
              <button
                onClick={() => setShowBacktestParams(!showBacktestParams)}
                className="px-3 py-1 text-xs rounded transition-colors"
                style={{
                  background: "var(--border)",
                  color: "var(--text)",
                  border: "1px solid var(--border-bright)"
                }}
              >
                {showBacktestParams ? "Hide Settings" : "Configure Backtest"}
              </button>
            </div>

            {/* Backtest Configuration Form */}
            {showBacktestParams && (
              <div className="p-4 rounded-lg flex flex-col gap-4 text-xs border"
                   style={{ background: "var(--bg)", borderColor: "var(--border)" }}>
                <div className="grid grid-cols-4 gap-4">
                  <div className="flex flex-col gap-1.5">
                    <span style={{ color: "var(--text-dim)" }}>Start Date</span>
                    <input
                      type="date"
                      value={backtestStart}
                      onChange={(e) => setBacktestStart(e.target.value)}
                      className="px-2 py-1.5 rounded outline-none"
                      style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)" }}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <span style={{ color: "var(--text-dim)" }}>End Date</span>
                    <input
                      type="date"
                      value={backtestEnd}
                      onChange={(e) => setBacktestEnd(e.target.value)}
                      className="px-2 py-1.5 rounded outline-none"
                      style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)" }}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <span style={{ color: "var(--text-dim)" }}>Slippage (bps)</span>
                    <input
                      type="number"
                      step="0.1"
                      value={slippage}
                      onChange={(e) => setSlippage(e.target.value)}
                      className="px-2 py-1.5 rounded outline-none"
                      style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)" }}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <span style={{ color: "var(--text-dim)" }}>Commission (%)</span>
                    <input
                      type="number"
                      step="0.01"
                      value={commission}
                      onChange={(e) => setCommission(e.target.value)}
                      className="px-2 py-1.5 rounded outline-none"
                      style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text)" }}
                    />
                  </div>
                </div>

                <div className="flex justify-end">
                  <button
                    disabled={backtestMutation.isPending}
                    onClick={() => {
                      backtestMutation.mutate({
                        symbol,
                        timeframe: "1d",
                        start_date: backtestStart,
                        end_date: backtestEnd,
                        initial_capital: parseFloat(capital) || 10000,
                        risk_tolerance: risk,
                        slippage_bps: parseFloat(slippage) || 5.0,
                        commission_pct: parseFloat(commission) || 0.1,
                      });
                    }}
                    className="px-4 py-1.5 rounded font-medium transition-opacity"
                    style={{
                      background: "var(--accent)",
                      color: "#000",
                      opacity: backtestMutation.isPending ? 0.6 : 1
                    }}
                  >
                    {backtestMutation.isPending ? "Running simulation..." : "Run Backtest"}
                  </button>
                </div>
              </div>
            )}

            {/* Error notifications */}
            {backtestMutation.isError && (() => {
              const err = backtestMutation.error as any;
              const is422 = err?.status === 422 || err?.detail?.status === 422 || (err?.message && err.message.includes("422"));
              return (
                <div className="p-3 rounded-lg text-xs border"
                     style={{
                       background: "rgba(255,68,102,0.08)",
                       color: "var(--red)",
                       borderColor: "var(--red)"
                     }}>
                  {is422 ? (
                    <span>No trained model yet for {symbol}. Train one first: <code>python scripts/train_model.py --symbol {symbol}</code></span>
                  ) : (
                    <span>Simulation failed: {err?.detail?.detail ?? err?.message ?? "an unexpected error occurred"}</span>
                  )}
                </div>
              );
            })()}

            {/* Chart Area */}
            <EquityCurveChart
              data={backtestMutation.data?.equity_curve ?? []}
              initialCapital={parseFloat(capital) || 10000}
              height={180}
            />

            {/* Results summary row */}
            {backtestMutation.data && (
              <div className="grid grid-cols-5 gap-3 border-t pt-4 text-xs" style={{ borderColor: "var(--border)" }}>
                {[
                  { label: "Total Return", value: `${backtestMutation.data.summary.total_return_pct >= 0 ? "+" : ""}${backtestMutation.data.summary.total_return_pct}%`, color: backtestMutation.data.summary.total_return_pct >= 0 ? "var(--green)" : "var(--red)" },
                  { label: "Sharpe Ratio", value: backtestMutation.data.risk.sharpe_ratio.toFixed(2), color: backtestMutation.data.risk.sharpe_ratio >= 1.0 ? "var(--green)" : backtestMutation.data.risk.sharpe_ratio >= 0.5 ? "var(--amber)" : "var(--text)" },
                  { label: "Max Drawdown", value: `${backtestMutation.data.risk.max_drawdown_pct.toFixed(1)}%`, color: "var(--red)" },
                  { label: "Win Rate", value: `${backtestMutation.data.trades.win_rate_pct.toFixed(0)}%`, color: backtestMutation.data.trades.win_rate_pct >= 50 ? "var(--green)" : "var(--text)" },
                  { label: "Total Trades", value: backtestMutation.data.trades.total_trades.toString(), color: "var(--text)" }
                ].map(({ label, value, color }) => (
                  <div key={label} className="flex flex-col gap-1 rounded-lg p-2.5" style={{ background: "var(--bg)" }}>
                    <span style={{ color: "var(--text-dim)" }}>{label}</span>
                    <span className="font-semibold mono text-sm" style={{ color }}>{value}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Model metadata */}
          <div className="card p-5">
            <h2 className="text-sm font-medium mb-4" style={{ color: "var(--text-dim)" }}>
              Model metadata
            </h2>
            <div className="grid grid-cols-4 gap-3 text-xs">
              {[
                { label: "Model version", value: analysis.model_version },
                { label: "Walk-forward AUC",
                  value: analysis.walk_forward_auc?.toFixed(4) ?? "No model" },
                { label: "Backtest Sharpe",
                  value: analysis.backtest_sharpe?.toFixed(3) ?? "—" },
                { label: "Analysis time",
                  value: new Date(analysis.analysis_timestamp).toLocaleTimeString() },
              ].map(({ label, value }) => (
                <div key={label} className="rounded-lg p-3"
                     style={{ background: "var(--bg)" }}>
                  <div style={{ color: "var(--text-dim)" }}>{label}</div>
                  <div className="mt-1 font-semibold mono"
                       style={{ color: "var(--text)" }}>{value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Disclaimer */}
          <p className="text-xs text-center pb-2" style={{ color: "var(--text-muted)" }}>
            {analysis.warnings[analysis.warnings.length - 1]}
          </p>
        </>
      )}
    </div>
  );
}
