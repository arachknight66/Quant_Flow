"use client";
import { useState, useRef, useEffect } from "react";
import { api } from "@/lib/api-client";

export interface SearchResult {
  symbol: string;
  name: string;
  asset_type: string;
  currency: string;
}

export function useSymbolSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const search = async (q: string) => {
    if (!q.trim() || q.length < 1) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const r = await api.market.search(q);
      setResults(r);
    } catch {
      /* ignore */
    }
    setSearching(false);
  };

  const handleInput = (v: string) => {
    setQuery(v);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => search(v), 300);
  };

  const clearSearch = () => {
    setQuery("");
    setResults([]);
  };

  useEffect(() => {
    return () => clearTimeout(timerRef.current);
  }, []);

  return {
    query,
    results,
    searching,
    handleInput,
    clearSearch,
    setResults
  };
}
