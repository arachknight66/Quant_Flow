import React, { useState, useCallback } from "react";
import {
  View, Text, TextInput, ScrollView, TouchableOpacity,
  ActivityIndicator, StyleSheet, Alert,
} from "react-native";
import { useQuery } from "@tanstack/react-query";

const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function analyzeSymbol(
  symbol: string, riskTolerance: string, capital?: number
) {
  const resp = await fetch(`${API_URL}/analysis/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol, asset_type: "stock", timeframe: "1d",
      risk_tolerance: riskTolerance,
      ...(capital ? { capital } : {}),
      lookback_days: 365,
    }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${resp.status}`);
  }
  return resp.json();
}

export function AnalysisScreen() {
  const [symbol,        setSymbol]        = useState("");
  const [riskTolerance, setRiskTolerance] = useState<"conservative"|"moderate"|"aggressive">("moderate");
  const [capital,       setCapital]       = useState("");
  const [submitted,     setSubmitted]     = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["analysis", submitted, riskTolerance, capital],
    queryFn:  () => analyzeSymbol(
      submitted!, riskTolerance,
      capital ? parseFloat(capital) : undefined
    ),
    enabled:   !!submitted,
    staleTime: 60_000,
    retry: 1,
  });

  const handleAnalyze = useCallback(() => {
    const sym = symbol.trim().toUpperCase();
    if (!sym) { Alert.alert("Enter a symbol", "e.g. AAPL or BTC-USD"); return; }
    setSubmitted(sym);
  }, [symbol]);

  const actionColor = data?.action === "BUY"  ? "#00e5a0"
                    : data?.action === "SELL" ? "#ff4466" : "#ffb020";

  return (
    <ScrollView style={s.container} keyboardShouldPersistTaps="handled"
                contentContainerStyle={s.content}>

      {/* Search row */}
      <View style={s.row}>
        <TextInput style={s.input} value={symbol} onChangeText={setSymbol}
          placeholder="Symbol (AAPL, BTC-USD…)" placeholderTextColor="#3a4f78"
          autoCapitalize="characters" autoCorrect={false}
          returnKeyType="search" onSubmitEditing={handleAnalyze}
          accessibilityLabel="Enter ticker symbol" />
        <TouchableOpacity style={s.btn} onPress={handleAnalyze} disabled={isLoading}
                          accessibilityLabel="Analyse">
          <Text style={s.btnText}>{isLoading ? "…" : "Analyse"}</Text>
        </TouchableOpacity>
      </View>

      {/* Risk selector */}
      <View style={s.row}>
        {(["conservative","moderate","aggressive"] as const).map((r) => (
          <TouchableOpacity key={r}
            style={[s.chip, riskTolerance === r && s.chipActive]}
            onPress={() => setRiskTolerance(r)}
            accessibilityRole="radio" accessibilityState={{ selected: riskTolerance === r }}>
            <Text style={[s.chipText, riskTolerance === r && s.chipTextActive]}>
              {r[0].toUpperCase() + r.slice(1)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Capital */}
      <TextInput style={[s.input, { marginBottom: 16 }]} value={capital}
        onChangeText={setCapital} placeholder="Capital USD (optional)"
        placeholderTextColor="#3a4f78" keyboardType="numeric"
        accessibilityLabel="Available capital in USD" />

      {/* Loading */}
      {isLoading && (
        <View style={s.center}>
          <ActivityIndicator size="large" color="#00d4ff" />
          <Text style={s.dim}>Analysing {submitted}…</Text>
        </View>
      )}

      {/* Error */}
      {error && !isLoading && (
        <View style={s.errorBox}>
          <Text style={s.errorText}>{(error as Error).message}</Text>
          <TouchableOpacity onPress={() => refetch()}>
            <Text style={{ color: "#00d4ff", fontSize: 13 }}>Retry</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Results */}
      {data && !isLoading && (
        <View style={s.results}>
          {/* Price row */}
          <View style={[s.row, { marginBottom: 16 }]}>
            <Text style={s.symbolLabel}>{data.symbol}</Text>
            <Text style={s.price}>${data.current_price.toLocaleString()}</Text>
            <Text style={[s.change, { color: data.price_change_24h_pct >= 0 ? "#00e5a0" : "#ff4466" }]}>
              {data.price_change_24h_pct >= 0 ? "+" : ""}{data.price_change_24h_pct.toFixed(2)}%
            </Text>
          </View>

          {/* Signal */}
          <View style={[s.signalBox, { borderColor: actionColor }]}>
            <Text style={[s.signalAction, { color: actionColor }]}>{data.action}</Text>
            <Text style={s.signalProb}>
              {(data.prob_profit * 100).toFixed(1)}% prob · {(data.confidence * 100).toFixed(0)}% conf
            </Text>
          </View>

          {/* Metrics */}
          <View style={s.metricsRow}>
            {[
              ["VaR 95%", `-${data.var_95.toFixed(2)}%`, "#ff4466"],
              ["Exp lo",  `${data.expected_return_lo >= 0 ? "+" : ""}${data.expected_return_lo.toFixed(1)}%`,
               data.expected_return_lo >= 0 ? "#00e5a0" : "#ff4466"],
              ["Exp hi",  `${data.expected_return_hi >= 0 ? "+" : ""}${data.expected_return_hi.toFixed(1)}%`,
               data.expected_return_hi >= 0 ? "#00e5a0" : "#ff4466"],
              ["WF AUC",  data.walk_forward_auc?.toFixed(4) ?? "—", "#c8d8f0"],
            ].map(([label, value, color]) => (
              <View key={label as string} style={s.metric}>
                <Text style={s.metricLabel}>{label as string}</Text>
                <Text style={[s.metricValue, { color: color as string }]}>{value as string}</Text>
              </View>
            ))}
          </View>

          {/* RSI */}
          {data.indicators.rsi != null && (
            <View style={s.indicatorRow}>
              <Text style={s.indicatorLabel}>RSI (14)</Text>
              <Text style={[s.indicatorValue, {
                color: data.indicators.rsi > 70 ? "#ff4466"
                     : data.indicators.rsi < 30 ? "#00e5a0" : "#c8d8f0",
              }]}>{data.indicators.rsi.toFixed(1)}</Text>
            </View>
          )}

          {/* Position sizing */}
          {data.position_sizing && (
            <View style={s.sizingBox}>
              <Text style={s.sizingTitle}>Suggested position</Text>
              {[
                ["Allocation", `$${data.position_sizing.position_value_usd.toLocaleString()} (${data.position_sizing.allocation_pct.toFixed(1)}%)`],
                ["Stop loss",  `$${data.position_sizing.stop_loss_price.toFixed(2)}`],
                ["Take profit",`$${data.position_sizing.take_profit_price.toFixed(2)}`],
                ["R:R",        `${data.position_sizing.risk_reward_ratio.toFixed(2)}:1`],
              ].map(([l, v]) => (
                <View key={l as string} style={[s.row, { justifyContent: "space-between" }]}>
                  <Text style={s.dim}>{l as string}</Text>
                  <Text style={{ color: "#c8d8f0", fontSize: 13 }}>{v as string}</Text>
                </View>
              ))}
            </View>
          )}

          {/* Warnings */}
          {data.warnings.slice(0, -1).map((w: string, i: number) => (
            <View key={i} style={s.warning}>
              <Text style={s.warningText}>{w}</Text>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  container:      { flex: 1, backgroundColor: "#0a0e1a" },
  content:        { padding: 16, paddingBottom: 40 },
  row:            { flexDirection: "row", gap: 8, marginBottom: 12 },
  input:          { flex: 1, height: 46, borderWidth: 1, borderColor: "#1e2d4f",
                    borderRadius: 10, paddingHorizontal: 14, fontSize: 14,
                    backgroundColor: "#0f1628", color: "#c8d8f0" },
  btn:            { height: 46, paddingHorizontal: 18, backgroundColor: "#00d4ff",
                    borderRadius: 10, justifyContent: "center", alignItems: "center" },
  btnText:        { color: "#000", fontWeight: "700", fontSize: 14 },
  chip:           { flex: 1, height: 34, borderWidth: 1, borderColor: "#1e2d4f",
                    borderRadius: 8, justifyContent: "center", alignItems: "center",
                    backgroundColor: "#0f1628" },
  chipActive:     { backgroundColor: "#141d35", borderColor: "#00d4ff" },
  chipText:       { fontSize: 12, color: "#6a82a8" },
  chipTextActive: { color: "#00d4ff", fontWeight: "600" },
  center:         { alignItems: "center", paddingVertical: 32, gap: 10 },
  dim:            { color: "#6a82a8", fontSize: 13 },
  errorBox:       { backgroundColor: "#1a0f16", borderRadius: 10, padding: 14,
                    borderWidth: 1, borderColor: "#ff4466", gap: 8 },
  errorText:      { color: "#ff4466", fontSize: 13 },
  results:        { gap: 12 },
  symbolLabel:    { fontSize: 22, fontWeight: "700", color: "#c8d8f0", flex: 1 },
  price:          { fontSize: 18, fontWeight: "600", color: "#c8d8f0" },
  change:         { fontSize: 14, fontWeight: "500" },
  signalBox:      { borderWidth: 1, borderRadius: 12, padding: 16, alignItems: "center", gap: 4 },
  signalAction:   { fontSize: 28, fontWeight: "800", letterSpacing: 4 },
  signalProb:     { fontSize: 13, color: "#6a82a8" },
  metricsRow:     { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  metric:         { flex: 1, minWidth: "45%", backgroundColor: "#0f1628",
                    borderRadius: 10, padding: 12, borderWidth: 1, borderColor: "#1e2d4f" },
  metricLabel:    { fontSize: 10, color: "#6a82a8", marginBottom: 4 },
  metricValue:    { fontSize: 16, fontWeight: "700" },
  indicatorRow:   { flexDirection: "row", justifyContent: "space-between",
                    backgroundColor: "#0f1628", borderRadius: 10, padding: 12,
                    borderWidth: 1, borderColor: "#1e2d4f" },
  indicatorLabel: { fontSize: 13, color: "#6a82a8" },
  indicatorValue: { fontSize: 13, fontWeight: "600" },
  sizingBox:      { backgroundColor: "#0f1628", borderRadius: 12, padding: 14,
                    borderWidth: 1, borderColor: "#1e2d4f", gap: 8 },
  sizingTitle:    { fontSize: 13, fontWeight: "600", color: "#00d4ff", marginBottom: 4 },
  warning:        { backgroundColor: "#1a1608", borderRadius: 8, padding: 10,
                    borderLeftWidth: 3, borderLeftColor: "#ffb020" },
  warningText:    { fontSize: 11, color: "#ffb020", lineHeight: 16 },
});
