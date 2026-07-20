import { useMemo, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard, StatusBadge } from "../components/common/ui";
import { useApp } from "../app-context";
import { apiPost, apiPostJson, useLive, type EngineStatus, type LiveBot, type CustomSpec } from "../lib/api";

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`;

export default function BotsPage() {
  const app = useApp();
  const bots = useLive<LiveBot[]>("/bots/live", 2000);
  const engine = useLive<EngineStatus>("/engine/status", 2000);
  const fleet = useLive<CustomSpec[]>("/strategy/custom", 6000);
  const [query, setQuery] = useState("");
  const [deploying, setDeploying] = useState("");

  const items = bots.data ?? [];
  const strategies = fleet.data ?? [];
  const liveLabel = (engine.data?.strategy ?? "").toLowerCase();
  const running = engine.data?.running;

  const visible = useMemo(
    () => items.filter((b) =>
      b.symbol.toLowerCase().includes(query.toLowerCase()) ||
      b.strategy.toLowerCase().includes(query.toLowerCase())),
    [items, query],
  );

  const act = async (path: string, msg: string) => {
    try { await apiPost(path); app.toast(msg, "success"); engine.refetch(); bots.refetch(); }
    catch { app.toast("Backend not reachable", "error"); }
  };
  const deploy = async (s: CustomSpec) => {
    setDeploying(s.id ?? "");
    try { await apiPostJson(`/strategy/custom/${s.id}/deploy`, {}); app.toast(`Deployed "${s.name}" to the paper engine`, "success"); engine.refetch(); }
    catch { app.toast("Deploy failed", "error"); }
    finally { setDeploying(""); }
  };

  const openTrades = items.filter((b) => b.open).length;
  const totalPnl = items.reduce((s, b) => s + b.realized_pnl, 0);

  return (
    <>
      <PageHeader
        title="Fleet Manager"
        subtitle={`${strategies.length} strategies in the fleet · engine ${running ? "running" : "stopped"}`}
        actions={
          <div className="row-actions">
            <button className="btn btn-soft btn-sm" onClick={() => app.go("Strategy Studio")}><Icon name="settings" size={13} /> New strategy</button>
            {running ? (
              <button className="btn btn-warn" onClick={() => act("/engine/stop", "Engine stopped")}><Icon name="pause" size={14} /> Stop Engine</button>
            ) : (
              <button className="btn btn-primary" onClick={() => act("/engine/start", "Engine started")}><Icon name="play" size={14} /> Start Engine</button>
            )}
          </div>
        }
      />

      <div className="stat-row">
        <StatCard label="Fleet size" value={String(strategies.length)} sub="saved strategies" />
        <StatCard label="Live on engine" value={engine.data?.strategy ?? "—"} tone={running ? "green" : "amber"} sub={running ? "running · paper" : "stopped"} />
        <StatCard label="Open positions" value={String(openTrades)} sub={`across ${items.length} symbols`} />
        <StatCard label="Realized P&L (live)" value={money(totalPnl)} tone={totalPnl >= 0 ? "green" : "red"} sub="paper" />
      </div>

      {bots.error && !bots.data && (
        <div className="card" style={{ borderColor: "#ef4444" }}>
          <Icon name="warning" size={15} className="neg" /> Backend not reachable. Start the API to see the fleet.
        </div>
      )}

      <Card title="Strategy Fleet" subtitle="your saved strategies — deploy any one to the paper engine · only one runs live at a time">
        {strategies.length === 0 ? (
          <div className="dim" style={{ padding: 12 }}>
            No strategies yet — build one in <button className="chip-btn" onClick={() => app.go("Strategy Studio")}>Strategy Studio</button> and it joins the fleet.
          </div>
        ) : (
          <div className="tablewrap">
            <table className="data-table">
              <thead><tr><th>Strategy</th><th>Symbol</th><th>TF</th><th>Side</th><th>Rules</th><th>Versions</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {strategies.map((s) => {
                  const isLive = running && liveLabel.includes((s.name ?? "").toLowerCase()) && !!s.name;
                  return (
                    <tr key={s.id}>
                      <td><b>{s.name}</b>{(s as { favorite?: boolean }).favorite && <span style={{ marginLeft: 5 }}><Icon name="check" size={12} className="pos" /></span>}</td>
                      <td>{s.symbol}</td>
                      <td className="dim">{s.timeframe}</td>
                      <td><Badge text={s.side} tone={s.side === "long" ? "green" : "red"} /></td>
                      <td className="dim">{s.entry?.rules?.length ?? 0}{s.exit?.rules?.length ? ` +${s.exit.rules.length} exit` : ""}</td>
                      <td className="dim">{s.versions?.length ?? 0}</td>
                      <td>{isLive ? <Badge text="LIVE" tone="green" /> : <span className="dim">idle</span>}</td>
                      <td>
                        <div className="row-actions" style={{ gap: 4, justifyContent: "flex-end" }}>
                          <button className="chip-btn" onClick={() => app.go("Strategy Studio")} title="Edit in Studio">Edit</button>
                          <button className="chip-btn" disabled={deploying === s.id} onClick={() => deploy(s)} title="Deploy to the paper engine">
                            <Icon name="rocket" size={12} /> {deploying === s.id ? "…" : "Deploy"}</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Live engine — per symbol" subtitle="the running engine's real state for each tracked symbol"
        right={<div className="search" style={{ maxWidth: 240 }}>
          <Icon name="search" size={15} className="search-icon" />
          <input placeholder="Search symbols / strategies…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>}>
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
                  {bots.loading ? "Loading…" : "No symbols match your search."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
