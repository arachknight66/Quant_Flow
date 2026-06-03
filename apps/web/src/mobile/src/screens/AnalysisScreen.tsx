// apps/mobile/src/screens/AnalysisScreen.tsx
import React, { useState, useCallback } from "react";
import {
  View,
  Text,
  TextInput,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Alert,
} from "react-native";
import { useQuery, useMutation } from "@tanstack/react-query";
import { mobileApiClient } from "@/lib/api-client";
import { SignalBadge } from "@/components/SignalBadge";
import { IndicatorRow } from "@/components/IndicatorRow";
import { RiskMeter } from "@/components/RiskMeter";

export function AnalysisScreen() {
  const [symbol, setSymbol] = useState("");
  const [riskTolerance, setRiskTolerance] = useState<"conservative" | "moderate" | "aggressive">(
    "moderate"
  );
  const [capital, setCapital] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);

  const {
    data: analysis,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["analysis", submitted, riskTolerance, capital],
    queryFn: () =>
      mobileApiClient.analyze({
        symbol: submitted!,
        asset_type: "stock",
        timeframe: "1d",
        risk_tolerance: riskTolerance,
        capital: capital ? parseFloat(capital) : undefined,
      }),
    enabled: !!submitted,
    staleTime: 60_000, // 1 minute — don't hammer the API
    retry: 1,
  });

  const handleAnalyze = useCallback(() => {
    if (!symbol.trim()) {
      Alert.alert("Enter a symbol", "Please enter a stock or crypto ticker.");
      return;
    }
    setSubmitted(symbol.trim().toUpperCase());
  }, [symbol]);

  return (
    <ScrollView
      style={styles.container}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.content}
    >
      {/* Search bar */}
      <View style={styles.searchRow}>
        <TextInput
          style={styles.input}
          value={symbol}
          onChangeText={setSymbol}
          placeholder="Symbol (AAPL, BTC-USD...)"
          autoCapitalize="characters"
          autoCorrect={false}
          returnKeyType="search"
          onSubmitEditing={handleAnalyze}
          accessibilityLabel="Enter ticker symbol"
        />
        <TouchableOpacity
          style={styles.analyzeBtn}
          onPress={handleAnalyze}
          disabled={isLoading}
          accessibilityLabel="Analyze"
        >
          <Text style={styles.analyzeBtnText}>Analyze</Text>
        </TouchableOpacity>
      </View>

      {/* Risk selector */}
      <View style={styles.riskRow}>
        {(["conservative", "moderate", "aggressive"] as const).map((r) => (
          <TouchableOpacity
            key={r}
            style={[styles.riskChip, riskTolerance === r && styles.riskChipActive]}
            onPress={() => setRiskTolerance(r)}
            accessibilityRole="radio"
            accessibilityState={{ selected: riskTolerance === r }}
          >
            <Text style={[styles.riskChipText, riskTolerance === r && styles.riskChipTextActive]}>
              {r.charAt(0).toUpperCase() + r.slice(1)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Capital input */}
      <TextInput
        style={styles.input}
        value={capital}
        onChangeText={setCapital}
        placeholder="Capital (USD, optional)"
        keyboardType="numeric"
        accessibilityLabel="Available capital in USD"
      />

      {/* Loading */}
      {isLoading && (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#3B82F6" />
          <Text style={styles.loadingText}>Analysing {submitted}...</Text>
        </View>
      )}

      {/* Error */}
      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>
            {(error as Error).message}
          </Text>
          <TouchableOpacity onPress={() => refetch()} style={styles.retryBtn}>
            <Text style={styles.retryText}>Retry</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Results */}
      {analysis && !isLoading && (
        <View style={styles.results}>
          {/* Price header */}
          <View style={styles.priceRow}>
            <Text style={styles.symbolLabel}>{analysis.symbol}</Text>
            <Text style={styles.price}>${analysis.current_price.toLocaleString()}</Text>
            <Text
              style={[
                styles.priceChange,
                analysis.price_change_24h_pct >= 0 ? styles.positive : styles.negative,
              ]}
            >
              {analysis.price_change_24h_pct >= 0 ? "+" : ""}
              {analysis.price_change_24h_pct.toFixed(2)}%
            </Text>
          </View>

          {/* Signal */}
          <SignalBadge
            action={analysis.action}
            confidence={analysis.confidence}
            probProfit={analysis.prob_profit}
          />

          {/* Key metrics grid */}
          <View style={styles.metricsGrid}>
            <MetricCard
              label="Prob. profit"
              value={`${(analysis.prob_profit * 100).toFixed(1)}%`}
              sub="Calibrated"
            />
            <MetricCard
              label="95% VaR"
              value={`-${analysis.var_95.toFixed(2)}%`}
              sub="Daily downside"
              negative
            />
            <MetricCard
              label="Exp. return low"
              value={`${analysis.expected_return_lo >= 0 ? "+" : ""}${analysis.expected_return_lo.toFixed(1)}%`}
              sub="5-day range"
            />
            <MetricCard
              label="Exp. return high"
              value={`${analysis.expected_return_hi >= 0 ? "+" : ""}${analysis.expected_return_hi.toFixed(1)}%`}
              sub="5-day range"
            />
          </View>

          {/* Indicators */}
          <Text style={styles.sectionTitle}>Technical indicators</Text>
          {analysis.indicators.rsi !== null && (
            <IndicatorRow
              label="RSI (14)"
              value={analysis.indicators.rsi}
              formatter={(v) => v.toFixed(1)}
              warningHigh={70}
              warningLow={30}
            />
          )}
          {analysis.indicators.bb_pct_b !== null && (
            <IndicatorRow
              label="Bollinger %B"
              value={analysis.indicators.bb_pct_b * 100}
              formatter={(v) => `${v.toFixed(1)}%`}
              warningHigh={100}
              warningLow={0}
            />
          )}
          {analysis.indicators.vol_20d !== null && (
            <IndicatorRow
              label="20d volatility"
              value={analysis.indicators.vol_20d * 100}
              formatter={(v) => `${v.toFixed(1)}%`}
            />
          )}

          {/* Position sizing */}
          {analysis.position_sizing && (
            <View style={styles.sizingCard}>
              <Text style={styles.sizingTitle}>Suggested position</Text>
              <View style={styles.sizingGrid}>
                <SizingRow label="Allocation" value={`$${analysis.position_sizing.position_value_usd.toLocaleString()} (${analysis.position_sizing.allocation_pct.toFixed(1)}%)`} />
                <SizingRow label="Stop loss" value={`$${analysis.position_sizing.stop_loss_price.toFixed(2)}`} negative />
                <SizingRow label="Take profit" value={`$${analysis.position_sizing.take_profit_price.toFixed(2)}`} positive />
                <SizingRow label="Risk/reward" value={`${analysis.position_sizing.risk_reward_ratio.toFixed(2)}:1`} />
              </View>
            </View>
          )}

          {/* Warnings */}
          {analysis.warnings.map((w, i) => (
            <View key={i} style={styles.warning}>
              <Text style={styles.warningText}>{w}</Text>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

function MetricCard({
  label, value, sub, negative = false,
}: { label: string; value: string; sub: string; negative?: boolean }) {
  return (
    <View style={styles.metricCard}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricValue, negative && styles.negative]}>{value}</Text>
      <Text style={styles.metricSub}>{sub}</Text>
    </View>
  );
}

function SizingRow({
  label, value, negative = false, positive = false,
}: { label: string; value: string; negative?: boolean; positive?: boolean }) {
  return (
    <View style={styles.sizingRow}>
      <Text style={styles.sizingLabel}>{label}</Text>
      <Text style={[styles.sizingValue, negative && styles.negative, positive && styles.positive]}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F8FAFC" },
  content: { padding: 16, paddingBottom: 40 },
  searchRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  input: {
    flex: 1,
    height: 48,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 10,
    paddingHorizontal: 14,
    fontSize: 15,
    backgroundColor: "#fff",
    color: "#1E293B",
  },
  analyzeBtn: {
    height: 48,
    paddingHorizontal: 18,
    backgroundColor: "#3B82F6",
    borderRadius: 10,
    justifyContent: "center",
    alignItems: "center",
  },
  analyzeBtnText: { color: "#fff", fontWeight: "600", fontSize: 15 },
  riskRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  riskChip: {
    flex: 1,
    height: 36,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 8,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#fff",
  },
  riskChipActive: { backgroundColor: "#EFF6FF", borderColor: "#3B82F6" },
  riskChipText: { fontSize: 12, color: "#64748B" },
  riskChipTextActive: { color: "#1D4ED8", fontWeight: "600" },
  loadingContainer: { alignItems: "center", paddingVertical: 40, gap: 12 },
  loadingText: { color: "#64748B", fontSize: 14 },
  errorBox: {
    backgroundColor: "#FEF2F2",
    borderRadius: 10,
    padding: 14,
    borderWidth: 1,
    borderColor: "#FECACA",
    marginTop: 16,
  },
  errorText: { color: "#B91C1C", fontSize: 13, marginBottom: 8 },
  retryBtn: { alignSelf: "flex-start" },
  retryText: { color: "#3B82F6", fontSize: 13, fontWeight: "600" },
  results: { marginTop: 16, gap: 14 },
  priceRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  symbolLabel: { fontSize: 22, fontWeight: "700", color: "#0F172A", flex: 1 },
  price: { fontSize: 20, fontWeight: "600", color: "#1E293B" },
  priceChange: { fontSize: 14, fontWeight: "500" },
  positive: { color: "#16A34A" },
  negative: { color: "#DC2626" },
  metricsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  metricCard: {
    flex: 1,
    minWidth: "45%",
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 12,
    borderWidth: 1,
    borderColor: "#F1F5F9",
  },
  metricLabel: { fontSize: 11, color: "#94A3B8", marginBottom: 3 },
  metricValue: { fontSize: 18, fontWeight: "700", color: "#0F172A" },
  metricSub: { fontSize: 10, color: "#CBD5E1", marginTop: 2 },
  sectionTitle: { fontSize: 15, fontWeight: "600", color: "#374151", marginTop: 4 },
  sizingCard: {
    backgroundColor: "#EFF6FF",
    borderRadius: 12,
    padding: 14,
    borderWidth: 1,
    borderColor: "#BFDBFE",
  },
  sizingTitle: { fontSize: 14, fontWeight: "600", color: "#1E40AF", marginBottom: 10 },
  sizingGrid: { gap: 6 },
  sizingRow: { flexDirection: "row", justifyContent: "space-between" },
  sizingLabel: { fontSize: 13, color: "#3B82F6" },
  sizingValue: { fontSize: 13, fontWeight: "600", color: "#1E293B" },
  warning: {
    backgroundColor: "#FFFBEB",
    borderRadius: 8,
    padding: 10,
    borderLeftWidth: 3,
    borderLeftColor: "#F59E0B",
  },
  warningText: { fontSize: 11, color: "#92400E", lineHeight: 16 },
});