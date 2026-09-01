"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, useEffect } from "react";
import { api } from "@/lib/api-client";
import { useAuthStore } from "@/store/auth";

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const tokenRes = await api.auth.refresh();
        if (cancelled) return;
        const user = await api.auth.me();
        if (cancelled) return;
        useAuthStore.getState().setToken(tokenRes.access_token, user);
      } catch {
        // No valid refresh cookie — stay anonymous
      } finally {
        if (!cancelled) setChecking(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (checking) {
    return (
      <div
        className="flex items-center justify-center h-screen"
        style={{ background: "var(--bg)", color: "var(--text-dim)" }}
      >
        <span className="text-xs">Checking session…</span>
      </div>
    );
  }

  return <>{children}</>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 30_000,
          retry: 2,
          refetchOnWindowFocus: true,
        },
      },
    })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        {children}
      </AuthProvider>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
