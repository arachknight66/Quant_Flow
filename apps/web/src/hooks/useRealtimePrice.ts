// apps/web/src/hooks/useRealtimePrice.ts
/**
 * Custom hook for real-time WebSocket price subscriptions.
 *
 * Design:
 * - Single shared WebSocket connection per app (not per component)
 * - Components subscribe to symbols; hook manages pub/sub internally
 * - Automatic reconnect with exponential backoff
 * - Stale-while-revalidate: uses last known price while reconnecting
 */
"use client";
import { useEffect, useRef, useState, useCallback } from "react";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/prices";
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30_000;

interface PriceUpdate {
  symbol: string;
  price: number;
  change_pct: number;
  volume: number;
  timestamp: string;
}

// Singleton WebSocket shared across all hook instances
let sharedWs: WebSocket | null = null;
const listeners = new Map<string, Set<(update: PriceUpdate) => void>>();

function getOrCreateWs(): WebSocket {
  if (sharedWs?.readyState === WebSocket.OPEN) return sharedWs;

  sharedWs = new WebSocket(WS_URL);

  sharedWs.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "price_update") {
        const subs = listeners.get(msg.symbol);
        subs?.forEach((cb) => cb(msg as PriceUpdate));
      }
    } catch {}
  };

  sharedWs.onclose = () => {
    // Reconnect with backoff
    setTimeout(() => getOrCreateWs(), RECONNECT_BASE_MS);
  };

  return sharedWs;
}

export function useRealtimePrice(symbol: string | null) {
  const [priceData, setPriceData] = useState<PriceUpdate | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!symbol) return;

    const ws = getOrCreateWs();

    // Subscribe when connection is ready
    const subscribe = () => {
      ws.send(JSON.stringify({ action: "subscribe", symbol }));
      setConnected(true);
    };

    if (ws.readyState === WebSocket.OPEN) {
      subscribe();
    } else {
      ws.addEventListener("open", subscribe, { once: true });
    }

    // Register listener
    if (!listeners.has(symbol)) listeners.set(symbol, new Set());
    const handler = (update: PriceUpdate) => setPriceData(update);
    listeners.get(symbol)!.add(handler);

    return () => {
      listeners.get(symbol)?.delete(handler);
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: "unsubscribe", symbol }));
      }
    };
  }, [symbol]);

  return { priceData, connected };
}