/**
 * Plain-language translation layer for QuantPlatform.
 * Converts raw model output into honest, accessible English.
 */
import { FullAnalysisResponse } from "@/lib/api-client";

export function summarizeSignal(data: FullAnalysisResponse): string {
  const { action, confidence, price_change_24h_pct } = data;
  const high = confidence > 0.6;
  const medium = confidence > 0.35;

  // Price context fragment
  const priceCtx =
    Math.abs(price_change_24h_pct) > 3
      ? price_change_24h_pct > 0
        ? " after a strong recent move up"
        : " after a sharp recent drop"
      : "";

  if (action === "BUY") {
    if (high) {
      return `The model sees a decent buying opportunity here${priceCtx}, with fairly high confidence.`;
    }
    if (medium) {
      return `The model leans positive${priceCtx}, but with only moderate confidence — consider doing your own research before acting.`;
    }
    return `The model leans slightly positive${priceCtx}, but isn't very confident — worth doing your own research before acting.`;
  }

  if (action === "SELL") {
    if (high) {
      return `The model sees meaningful downside risk here${priceCtx} with fairly high confidence.`;
    }
    if (medium) {
      return `The model leans negative${priceCtx}, with moderate confidence — the picture could change with new data.`;
    }
    return `The model sees some downside risk${priceCtx}, but isn't confident enough to make a strong call.`;
  }

  // HOLD
  if (high) {
    return `The model doesn't see a clear edge either way right now${priceCtx} — probably best to wait and see.`;
  }
  return `The model doesn't see a clear edge right now${priceCtx} — it's essentially a coin flip at this point.`;
}

export function explainIndicator(name: string, value: number): string {
  const key = name.toLowerCase().replace(/[\s()]/g, "_");

  if (key.includes("rsi")) {
    if (value > 70) return "This has climbed a lot recently — it may be due for a pullback.";
    if (value < 30) return "This has dropped a lot recently — it may be due for a bounce.";
    if (value >= 30 && value <= 70) return "Momentum looks balanced right now.";
  }

  if (key.includes("macd_hist") || key === "macd_hist") {
    if (value > 0.5) return "Bullish momentum is building — recent gains are accelerating.";
    if (value < -0.5) return "Bearish momentum is building — recent losses are accelerating.";
    if (Math.abs(value) <= 0.5) return "Momentum is relatively flat right now.";
  }

  if (key.includes("bb_pct") || key.includes("bb_%b") || key === "bb_%b") {
    if (value > 80) return "Price is near the top of its recent range — could be stretched.";
    if (value < 20) return "Price is near the bottom of its recent range — could be oversold.";
    return "Price is in the middle of its recent trading range.";
  }

  if (key.includes("atr")) {
    if (value > 3) return "Expect large daily swings — this is more volatile than usual.";
    if (value < 1) return "Daily swings are relatively small right now.";
    return "";
  }

  if (key.includes("vol_20d") || key.includes("ann._vol")) {
    if (value > 0.50) return "This has been very volatile — expect significant swings.";
    if (value > 0.35) return "This has been moving around a lot lately — expect bigger swings.";
    if (value > 0.20) return "Volatility is moderate — moves are within a normal range.";
    return "Volatility has been low — this has been relatively calm.";
  }

  if (key.includes("momentum")) {
    if (value > 0.05) return "Strong upward momentum over the last 10 days.";
    if (value < -0.05) return "Noticeable downward momentum over the last 10 days.";
    if (Math.abs(value) <= 0.05) return "Momentum is close to flat — no strong trend.";
  }

  return "";
}

/** Short glossary for model-specific metrics shown in the stats grid */
export const METRIC_GLOSSARY: Record<string, string> = {
  "Expected lo":
    "The low end of where the model thinks the price might go.",
  "Expected hi":
    "The high end of where the model thinks the price might go.",
  "VaR 95%":
    "The worst loss you'd statistically expect on a bad day, 95% of the time.",
  "WF AUC":
    "How well the model's predictions have historically matched what actually happened. 0.5 = random guess, 1.0 = perfect.",
  "Kelly fraction":
    "The math-optimal fraction of your money to risk on this trade, before we conservatively cut it to a quarter of that.",
};
