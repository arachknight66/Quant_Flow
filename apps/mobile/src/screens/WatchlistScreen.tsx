import React, { useState } from "react";
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { useQuery } from "@tanstack/react-query";

const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const WATCHLIST_SYMBOLS = ["AAPL", "MSFT", "TSLA", "BTC-USD", "ETH-USD", "SPY"];

export function WatchlistScreen() {
  const { data: prices, isLoading, refetch } = useQuery({
    queryKey: ["watchlist-prices"],
    queryFn: async () => {
      const results = [];
      for (const sym of WATCHLIST_SYMBOLS) {
        try {
          const resp = await fetch(`${API_URL}/market/ohlcv?symbol=${sym}&interval=1d&days=2`);
          if (resp.ok) {
            const data = await resp.json();
            const bars = data.bars;
            if (bars && bars.length > 0) {
              const latest = bars[bars.length - 1];
              const prev = bars.length > 1 ? bars[bars.length - 2] : latest;
              const chg = latest.c - prev.c;
              const pct = (chg / prev.c) * 100;
              results.push({ symbol: sym, price: latest.c, change_pct: pct });
            }
          }
        } catch {
          results.push({ symbol: sym, price: null, change_pct: null });
        }
      }
      return results;
    },
    staleTime: 30_000
  });

  return (
    <ScrollView style={s.container} contentContainerStyle={s.content}>
      <View style={s.header}>
        <Text style={s.title}>My Watchlist</Text>
        <TouchableOpacity style={s.refreshBtn} onPress={() => refetch()}>
          <Text style={s.refreshBtnText}>Refresh</Text>
        </TouchableOpacity>
      </View>

      {isLoading ? (
        <ActivityIndicator size="large" color="#00d4ff" style={{ marginTop: 40 }} />
      ) : (
        <View style={s.list}>
          {prices && prices.map((item: any) => (
            <View key={item.symbol} style={s.itemRow}>
              <View>
                <Text style={s.symbolText}>{item.symbol}</Text>
                <Text style={s.nameText}>Tracked Asset</Text>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                {item.price !== null ? (
                  <>
                    <Text style={s.priceText}>${item.price.toFixed(2)}</Text>
                    <Text style={[s.changeText, { color: item.change_pct >= 0 ? "#00e5a0" : "#ff4466" }]}>
                      {item.change_pct >= 0 ? "+" : ""}{item.change_pct.toFixed(2)}%
                    </Text>
                  </>
                ) : (
                  <Text style={s.dim}>No data</Text>
                )}
              </View>
            </View>
          ))}
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
  refreshBtn: { paddingHorizontal: 12, paddingVertical: 6, backgroundColor: "#0f1628", borderWidth: 1, borderColor: "#1e2d4f", borderRadius: 6 },
  refreshBtnText: { color: "#c8d8f0", fontSize: 12, fontWeight: "600" },
  list: { gap: 8 },
  itemRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", backgroundColor: "#0f1628", borderRadius: 10, padding: 14, borderWidth: 1, borderColor: "#1e2d4f", marginBottom: 8 },
  symbolText: { fontSize: 15, fontWeight: "700", color: "#c8d8f0" },
  nameText: { fontSize: 11, color: "#6a82a8", marginTop: 2 },
  priceText: { fontSize: 15, fontWeight: "600", color: "#c8d8f0" },
  changeText: { fontSize: 12, fontWeight: "600", marginTop: 2 },
  dim: { color: "#6a82a8", fontSize: 13 }
});
