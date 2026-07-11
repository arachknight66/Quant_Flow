"use client";
import { useQuery } from "@tanstack/react-query";
import { api, AnalysisRequest, FullAnalysisResponse } from "@/lib/api-client";

export function useAnalysis(request: AnalysisRequest | null) {
  return useQuery<FullAnalysisResponse, Error>({
    queryKey: ["analysis", request?.symbol, request?.timeframe,
               request?.risk_tolerance, request?.capital],
    queryFn: () => api.analysis.analyze(request!),
    enabled: !!request?.symbol,
    staleTime: 60_000,     // 1 min — don't hammer on every keystroke
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

export function useOHLCV(symbol: string | null, interval = "1d", days = 365) {
  return useQuery({
    queryKey: ["ohlcv", symbol, interval, days],
    queryFn: () => api.market.ohlcv(symbol!, interval, days),
    enabled: !!symbol,
    staleTime: 300_000,
  });
}
