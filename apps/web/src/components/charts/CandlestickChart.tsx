"use client";
import { useEffect, useRef } from "react";
import { OHLCVBar } from "@/lib/api-client";

interface Props {
  bars: OHLCVBar[];
  height?: number;
}

/**
 * TradingView lightweight-charts candlestick chart.
 * Dynamically imported to avoid SSR issues with the DOM-only library.
 */
export function CandlestickChart({ bars, height = 320 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<unknown>(null);
  const seriesRef    = useRef<unknown>(null);

  useEffect(() => {
    if (!containerRef.current || bars.length === 0) return;

    let chart: unknown;
    let cancelled = false;

    async function init() {
      const { createChart, ColorType, CrosshairMode } =
        await import("lightweight-charts");

      if (cancelled || !containerRef.current) return;

      chart = createChart(containerRef.current, {
        width:  containerRef.current.clientWidth,
        height,
        layout: {
          background:  { type: ColorType.Solid, color: "transparent" },
          textColor:   "#6a82a8",
          fontFamily:  "IBM Plex Mono, monospace",
        },
        grid: {
          vertLines:   { color: "#1e2d4f" },
          horzLines:   { color: "#1e2d4f" },
        },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: "#1e2d4f" },
        timeScale: {
          borderColor: "#1e2d4f",
          timeVisible: true,
          secondsVisible: false,
        },
      });

      // @ts-ignore — lightweight-charts types are version-sensitive
      const series = (chart as any).addCandlestickSeries({
        upColor:        "#00e5a0",
        downColor:      "#ff4466",
        borderUpColor:  "#00e5a0",
        borderDownColor:"#ff4466",
        wickUpColor:    "#00e5a0",
        wickDownColor:  "#ff4466",
      });

      const data = bars.map((b) => ({
        time:  b.t.split("T")[0],
        open:  b.o, high: b.h, low: b.l, close: b.c,
      }));

      series.setData(data);
      // @ts-ignore
      (chart as any).timeScale().fitContent();

      chartRef.current  = chart;
      seriesRef.current = series;
    }

    init();

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        // @ts-ignore
        (chartRef.current as any).applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      cancelled = true;
      ro.disconnect();
      if (chartRef.current) {
        // @ts-ignore
        (chartRef.current as any).remove();
        chartRef.current  = null;
        seriesRef.current = null;
      }
    };
  }, [bars, height]);

  if (bars.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-xl"
           style={{ height, background: "var(--bg)", color: "var(--text-muted)", fontSize: 13 }}>
        No chart data
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ width: "100%", height }}
         className="rounded-xl overflow-hidden" />
  );
}
