"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, WatchlistItemResponse } from "@/lib/api-client";

export function useWatchlist() {
  return useQuery<WatchlistItemResponse[], Error>({
    queryKey: ["watchlist"],
    queryFn: () => api.watchlist.get(),
  });
}

export function useAddWatchlistItem() {
  const queryClient = useQueryClient();
  return useMutation<WatchlistItemResponse, Error, { symbol: string; notes?: string }>({
    mutationFn: (data) => api.watchlist.add(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });
}

export function useRemoveWatchlistItem() {
  const queryClient = useQueryClient();
  return useMutation<any, Error, string>({
    mutationFn: (assetId) => api.watchlist.remove(assetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });
}
