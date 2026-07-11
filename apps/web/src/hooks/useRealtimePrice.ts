"use client";
import { useEffect, useState } from "react";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/prices";

interface PriceUpdate {
  symbol: string; price: number; change_pct: number;
  volume: number; high: number; low: number; timestamp: string;
}

// Singleton WebSocket — shared across all hook instances
let _ws: WebSocket | null = null;
const _listeners = new Map<string, Set<(u: PriceUpdate) => void>>();
let _reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
const RECONNECT_MS = 3000;

function getWs(): WebSocket {
  if (_ws?.readyState === WebSocket.OPEN) return _ws;

  _ws = new WebSocket(WS_URL);

  _ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === "price_update") {
        _listeners.get(msg.symbol)?.forEach((cb) => cb(msg as PriceUpdate));
      }
    } catch { /* ignore malformed */ }
  };

  _ws.onclose = () => {
    if (_reconnectTimeout) clearTimeout(_reconnectTimeout);
    _reconnectTimeout = setTimeout(() => getWs(), RECONNECT_MS);
  };

  return _ws;
}

export function useRealtimePrice(symbol: string | null) {
  const [data, setData] = useState<PriceUpdate | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!symbol) return;
    const sym = symbol.toUpperCase();
    const ws  = getWs();

    const subscribe = () => {
      ws.send(JSON.stringify({ action: "subscribe", symbol: sym }));
      setConnected(true);
    };

    if (ws.readyState === WebSocket.OPEN) subscribe();
    else ws.addEventListener("open", subscribe, { once: true });

    if (!_listeners.has(sym)) _listeners.set(sym, new Set());
    const handler = (u: PriceUpdate) => setData(u);
    _listeners.get(sym)!.add(handler);

    return () => {
      _listeners.get(sym)?.delete(handler);
      if (ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ action: "unsubscribe", symbol: sym }));
    };
  }, [symbol]);

  return { data, connected };
}
