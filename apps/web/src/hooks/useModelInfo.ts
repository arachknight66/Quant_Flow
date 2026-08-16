"use client";
import { useQuery } from "@tanstack/react-query";
import { api, ModelInfoResponse } from "@/lib/api-client";

export function useModelInfo(symbol: string | null, timeframe = "1d") {
  return useQuery<ModelInfoResponse, Error>({
    queryKey: ["model-info", symbol, timeframe],
    queryFn: () => api.analysis.modelInfo(symbol!, timeframe),
    enabled: !!symbol,
    staleTime: 300_000,
    retry: false
  });
}
