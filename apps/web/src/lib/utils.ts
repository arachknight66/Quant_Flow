import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmt(n: number, decimals = 2): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function fmtPct(n: number, decimals = 2): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${fmt(n, decimals)}%`;
}

export function fmtUsd(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: 2,
  }).format(n);
}

export function fmtCurrency(n: number, currency = "USD"): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency.toUpperCase() === "GBX" ? "GBP" : currency.toUpperCase(),
      minimumFractionDigits: 2,
    }).format(n);
  } catch {
    return `${currency.toUpperCase()} ${fmt(n, 2)}`;
  }
}

export function signColor(n: number): string {
  if (n > 0) return "var(--green)";
  if (n < 0) return "var(--red)";
  return "var(--text-dim)";
}
