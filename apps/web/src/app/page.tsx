"use client";

import { useState } from "react";
import { AnalysisPanel } from "@/components/analysis/AnalysisPanel";
import { Sidebar } from "@/components/ui/Sidebar";
import { Header } from "@/components/ui/Header";

export default function HomePage() {
  const [symbol, setSymbol] = useState<string>("AAPL");

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--bg)" }}>
      <Sidebar activeSymbol={symbol} onSelectSymbol={setSymbol} />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header symbol={symbol} onSymbolChange={setSymbol} />
        <main className="flex-1 overflow-y-auto p-6">
          <AnalysisPanel symbol={symbol} />
        </main>
      </div>
    </div>
  );
}
