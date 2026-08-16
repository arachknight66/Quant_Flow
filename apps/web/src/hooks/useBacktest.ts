"use client";
import { useMutation } from "@tanstack/react-query";
import { api, BacktestRequest, BacktestResult } from "@/lib/api-client";

export function useBacktest() {
  return useMutation<BacktestResult, Error, BacktestRequest>({
    mutationFn: (req: BacktestRequest) => api.analysis.backtest(req),
  });
}
