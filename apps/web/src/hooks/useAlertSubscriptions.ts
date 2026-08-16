"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, AlertSubscriptionResponse } from "@/lib/api-client";

export function useAlertSubscriptions() {
  return useQuery<AlertSubscriptionResponse[], Error>({
    queryKey: ["alerts"],
    queryFn: () => api.alerts.get(),
  });
}

export function useToggleAlertSubscription() {
  const queryClient = useQueryClient();
  return useMutation<AlertSubscriptionResponse, Error, { symbol: string; isActive: boolean }>({
    mutationFn: ({ symbol, isActive }) => {
      if (isActive) {
        return api.alerts.subscribe(symbol, true);
      } else {
        return api.alerts.unsubscribe(symbol).then(() => ({ id: "", symbol, name: "", is_active: false }));
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
}
