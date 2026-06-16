import { useMemo, useState } from "react";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatusBadge } from "../components/common/ui";
import { useApp } from "../app-context";
import { apiPost, useLive, type EngineStatus, type LiveBot } from "../lib/api";

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`;

export default function BotsPage() {
  const app = useApp();
  const bots = useLive<LiveBot[]>("/bots/live", 2000);
  const engine = useLive<EngineStatus>("/engine/status", 2000);
  const [query, setQuery] = useState("");

  const items = bots.data ?? [];
  const visible = useMemo(
    () => items.filter((b) =>
      b.symbol.toLowerCase().includes(query.toLowerCase()) ||
      b.strategy.toLowerCase().includes(query.toLowerCase())),
    [items, query],
  );

  const running = engine.data?.running;
  const act = async (path: string, msg: string) => {
    try { await apiPost(path); app.toast(msg, "success"); engine.refetch(); bots.refetch(); }
    catch { app.toast("Backend not reachable", "error"); }
  };

  return (
    <>
      <PageHeader
        title="Bots"
        subtitle={`${items.length} symbols · engine ${running ? "running" : "stopped"}`}
        actions={
          <div className="row-actions">
            {running ? (
              <button className="btn btn-warn" onClick={() => act("/engine/stop", "Engine stopped")}><Icon name="pause" size={14} /> Stop Engine</button>
            ) : (
              <button className="btn btn-primary" onClick={() => act("/engine/start", "Engine started")}><Icon name="play" size={14} /> Start Engine</button>
            )}
          </div>
        }
      />

      {bots.error && !bots.data && (
        <div className="card" style={{ borderColor: "#ef4444" }}>
          <Icon name="warning" size={15} className="neg" /> Backend not reachable. Start the API to see live bots.
        </div>
      )}

      <div className="toolbar">
        <div className="search">
          <Icon name="info" size={15} className="search-icon" />
          <input placeholder="Search symbols / strategies…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>

      <div className="card">
        <div className="tablewrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Bot</th><th>Strategy</th><th>Symbol</th><th>TF</th>
                <th>Position</th><th>Trades</th><th>Win rate</th><th>Realized P&amp;L</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((b) => (
                <tr key={b.id}>
                  <td><b>{b.name}</b></td>
                  <td className="dim">{b.strategy}</td>
                  <td>{b.symbol}</td>
                  <td className="dim">{b.timeframe}</td>
                  <td>
                    {b.open
                      ? <Badge text={`${b.side} ${b.size.toFixed(4)}`} tone={b.side === "long" ? "green" : "red"} />
                      : <span className="dim">flat</span>}
                  </td>
                  <td>{b.num_trades}</td>
                  <td className="dim">{(b.win_rate * 100).toFixed(0)}%</td>
                  <td className={b.realized_pnl >= 0 ? "pos" : "neg"}>{money(b.realized_pnl)}</td>
                  <td><StatusBadge status={b.status} /></td>
                  <td><button className="icon-btn sm" title="View details" onClick={() => app.viewBot(b.id)}><Icon name="chart" size={14} /></button></td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr><td colSpan={10} className="dim ta-center" style={{ padding: 24 }}>
                  {bots.loading ? "Loading…" : "No bots match your search."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
