import React, { useState } from "react";
import { View, Text, ScrollView, StyleSheet, ActivityIndicator, TouchableOpacity } from "react-native";
import { useQuery } from "@tanstack/react-query";

const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export function PortfolioScreen() {
  const { data: summary, isLoading: sumLoading, refetch: refetchSummary } = useQuery({
    queryKey: ["portfolio-summary"],
    queryFn: async () => {
      const resp = await fetch(`${API_URL}/portfolio/summary`);
      return resp.json();
    }
  });

  const { data: positions, isLoading: posLoading, refetch: refetchPositions } = useQuery({
    queryKey: ["portfolio-positions"],
    queryFn: async () => {
      const resp = await fetch(`${API_URL}/portfolio/positions`);
      return resp.json();
    }
  });

  const handleRefresh = () => {
    refetchSummary();
    refetchPositions();
  };

  const loading = sumLoading || posLoading;
  const activePositions = positions?.filter((p: any) => p.is_open) || [];
  const closedPositions = positions?.filter((p: any) => !p.is_open) || [];

  return (
    <ScrollView style={s.container} contentContainerStyle={s.content}>
      <View style={s.header}>
        <Text style={s.title}>Portfolio & Positions</Text>
        <TouchableOpacity style={s.refreshBtn} onPress={handleRefresh}>
          <Text style={s.refreshBtnText}>Refresh</Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <ActivityIndicator size="large" color="#00d4ff" style={{ marginTop: 40 }} />
      ) : (
        <View style={s.body}>
          {/* Summary grid */}
          <View style={s.grid}>
            <View style={s.card}>
              <Text style={s.cardLabel}>Net Asset Value</Text>
              <Text style={s.cardValue}>${summary?.total_value_usd?.toFixed(2) || "0.00"}</Text>
            </View>
            <View style={s.card}>
              <Text style={s.cardLabel}>Cash Balance</Text>
              <Text style={s.cardValue}>${summary?.cash_usd?.toFixed(2) || "0.00"}</Text>
            </View>
            <View style={s.card}>
              <Text style={s.cardLabel}>Invested</Text>
              <Text style={s.cardValue}>${summary?.invested_usd?.toFixed(2) || "0.00"}</Text>
            </View>
            <View style={s.card}>
              <Text style={s.cardLabel}>Total P&L</Text>
              <Text style={[s.cardValue, { color: (summary?.total_pnl_usd >= 0) ? "#00e5a0" : "#ff4466" }]}>
                ${summary?.total_pnl_usd?.toFixed(2) || "0.00"}
              </Text>
            </View>
          </View>

          {/* Active Positions */}
          <Text style={s.subTitle}>Active Positions</Text>
          {activePositions.length > 0 ? (
            activePositions.map((pos: any) => (
              <View key={pos.id} style={s.positionRow}>
                <View>
                  <Text style={s.symbolText}>{pos.symbol}</Text>
                  <Text style={s.qtyText}>{pos.quantity} shares</Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={s.priceText}>Avg: ${pos.avg_entry_price.toFixed(2)}</Text>
                  <Text style={[s.pnlText, { color: "#00e5a0" }]}>Active</Text>
                </View>
              </View>
            ))
          ) : (
            <Text style={s.dim}>No active positions</Text>
          )}

          {/* Closed Positions */}
          <Text style={s.subTitle}>Closed Trade History</Text>
          {closedPositions.length > 0 ? (
            closedPositions.map((pos: any) => (
              <View key={pos.id} style={[s.positionRow, { opacity: 0.7 }]}>
                <View>
                  <Text style={[s.symbolText, { color: "#6a82a8" }]}>{pos.symbol}</Text>
                  <Text style={s.qtyText}>{pos.quantity} shares</Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={s.priceText}>Entry: ${pos.avg_entry_price.toFixed(2)}</Text>
                  <Text style={s.qtyText}>{pos.notes || "Closed"}</Text>
                </View>
              </View>
            ))
          ) : (
            <Text style={s.dim}>No closed positions</Text>
          )}
        </View>
      )}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0a0e1a" },
  content: { padding: 16, paddingBottom: 40 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 20 },
  title: { fontSize: 22, fontWeight: "700", color: "#c8d8f0" },
  subTitle: { fontSize: 16, fontWeight: "600", color: "#00d4ff", marginTop: 24, marginBottom: 12 },
  refreshBtn: { paddingHorizontal: 12, paddingVertical: 6, backgroundColor: "#0f1628", borderWidth: 1, borderColor: "#1e2d4f", borderRadius: 6 },
  refreshBtnText: { color: "#c8d8f0", fontSize: 12, fontWeight: "600" },
  body: { gap: 10 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  card: { flex: 1, minWidth: "45%", backgroundColor: "#0f1628", borderRadius: 10, padding: 14, borderWidth: 1, borderColor: "#1e2d4f" },
  cardLabel: { fontSize: 10, color: "#6a82a8", textTransform: "uppercase", marginBottom: 4 },
  cardValue: { fontSize: 18, fontWeight: "700", color: "#c8d8f0" },
  positionRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", backgroundColor: "#0f1628", borderRadius: 10, padding: 14, borderWidth: 1, borderColor: "#1e2d4f", marginBottom: 8 },
  symbolText: { fontSize: 15, fontWeight: "700", color: "#c8d8f0" },
  qtyText: { fontSize: 12, color: "#6a82a8", marginTop: 2 },
  priceText: { fontSize: 13, fontWeight: "600", color: "#c8d8f0" },
  pnlText: { fontSize: 12, fontWeight: "600", marginTop: 2 },
  dim: { color: "#6a82a8", fontSize: 13, textAlign: "center", paddingVertical: 12 }
});
