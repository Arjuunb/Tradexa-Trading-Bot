import { useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { useLive, hhmmss, type LedgerPosition, type SystemStatus } from "../lib/api";

const MARKETS = ["All", "Crypto", "Equity", "Forex"] as const;
const TFS = ["All", "1h", "4h", "1d"] as const;

export default function MarketsPage() {
  const { data: sys } = useLive<SystemStatus>("/system/status", 3000);
  const { data: positions } = useLive<LedgerPosition[]>("/paper/positions", 3000);
  const [market, setMarket] = useState<(typeof MARKETS)[number]>("All");
  const [tf, setTf] = useState<(typeof TFS)[number]>("All");

  const symbols = sys?.symbols ?? [];
  const posBySym = new Map((positions ?? []).map((p) => [p.symbol, p]));

  return (
    <>
      <PageHeader title="Markets" subtitle="Symbols the engine is actively tracking · paper mode" />

      <div className="stat-row">
        <StatCard label="Engine" value={sys?.engine_running ? "Running" : "Stopped"} tone={sys?.engine_running ? "green" : "red"} />
        <StatCard label="Mode" value={(sys?.mode ?? "paper").toUpperCase()} />
        <StatCard label="Tracked Symbols" value={String(symbols.length)} />
        <StatCard label="Timeframe" value={sys?.timeframe ?? "—"} />
      </div>

      <div className="toolbar">
        <div className="chips">
          {MARKETS.map((m) => (
            <button key={m} className={`chip-btn ${market === m ? "active" : ""}`} onClick={() => setMarket(m)}>{m}</button>
          ))}
        </div>
        <div className="chips">
          {TFS.map((t) => (
            <button key={t} className={`chip-btn ${tf === t ? "active" : ""}`} onClick={() => setTf(t)}>{t}</button>
          ))}
        </div>
      </div>

      <Card title="Watchlist" subtitle="position columns are real engine state · live quotes need a market-data feed (not connected)">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Symbol</th><th>In Position</th><th>Side</th><th>Size</th><th>Entry</th><th>Last</th><th>Volatility</th><th>Opened</th></tr></thead>
            <tbody>
              {symbols.map((sym) => {
                const p = posBySym.get(sym);
                return (
                  <tr key={sym}>
                    <td><b>{sym}</b></td>
                    <td>{p ? <Badge text="Open" tone="green" /> : <span className="dim">—</span>}</td>
                    <td>{p ? <Badge text={p.side} tone={p.side === "long" ? "green" : "red"} /> : <span className="dim">—</span>}</td>
                    <td>{p ? p.size.toFixed(6) : "—"}</td>
                    <td>{p ? p.entry.toLocaleString() : "—"}</td>
                    <td className="dim">—</td>
                    <td className="dim">—</td>
                    <td className="dim mono">{p ? hhmmss(p.opened_at) : "—"}</td>
                  </tr>
                );
              })}
              {symbols.length === 0 && <tr><td colSpan={8} className="dim ta-center" style={{ padding: 20 }}>No symbols configured. Set them on the Settings page.</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="dim" style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
          <Icon name="info" size={14} /> Last price / volatility / spread require a live market-data feed, which isn't connected — shown as “—” rather than faked.
        </p>
      </Card>
    </>
  );
}
