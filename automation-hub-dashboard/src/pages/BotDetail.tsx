import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { useApp } from "../app-context";
import {
  useLive, hhmmss,
  type LiveBot, type LogRow, type PaperTradeRow,
} from "../lib/api";

interface Props {
  botId: string;
}

const money = (n: number | null | undefined) => `${(n ?? 0) >= 0 ? "+" : "-"}$${Math.abs(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

// Real per-symbol view from the live engine + ledger (paper). No mock.
export default function BotDetail({ botId }: Props) {
  const app = useApp();
  const bots = useLive<LiveBot[]>("/bots/live", 2500);
  const trades = useLive<PaperTradeRow[]>("/paper/trades", 3000);
  const logs = useLive<LogRow[]>("/ledger/logs?limit=60", 3000);

  const bot = (bots.data ?? []).find((b) => b.id === botId);
  const symTrades = (trades.data ?? []).filter((t) => t.symbol === botId);
  const symLogs = (logs.data ?? []).filter((l) => l.symbol === botId);

  return (
    <>
      <PageHeader
        title={bot ? bot.name : botId}
        subtitle={bot ? `${bot.strategy} · ${bot.timeframe} · paper` : "symbol"}
        actions={<button className="btn btn-ghost" onClick={() => app.go("Bots")}><Icon name="chart" size={14} /> Back to Bots</button>}
      />

      {!bot && !bots.loading && (
        <div className="card"><div className="dim">No live data for {botId}. {bots.error ? "Backend not reachable." : ""}</div></div>
      )}

      <div className="stat-row">
        <StatCard label="Position" value={bot?.open ? `${bot.side} ${bot.size.toFixed(4)}` : "flat"} tone={bot?.open ? (bot.side === "long" ? "green" : "red") : "default"} sub={bot?.open ? `entry ${bot.entry.toLocaleString()}` : ""} />
        <StatCard label="Realized P&L" value={money(bot?.realized_pnl)} tone={(bot?.realized_pnl ?? 0) >= 0 ? "green" : "red"} />
        <StatCard label="Trades" value={String(bot?.num_trades ?? 0)} />
        <StatCard label="Win Rate" value={`${((bot?.win_rate ?? 0) * 100).toFixed(0)}%`} />
        <StatCard label="Status" value={bot?.status ?? "—"} tone={bot?.status === "Running" ? "green" : bot?.status === "Paused" ? "amber" : "red"} />
      </div>

      <Card title="Trade History" subtitle={`${symTrades.length} closed trades`}>
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Side</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>R:R</th><th>Closed</th></tr></thead>
            <tbody>
              {symTrades.map((t) => (
                <tr key={t.id}>
                  <td><Badge text={t.side} tone={t.side === "long" ? "green" : "red"} /></td>
                  <td>{t.entry.toLocaleString()}</td>
                  <td>{t.exit !== null ? t.exit.toLocaleString() : "—"}</td>
                  <td className={(t.pnl ?? 0) >= 0 ? "pos" : "neg"}>{money(t.pnl)}</td>
                  <td>{t.rr !== null && t.rr !== undefined ? `${t.rr.toFixed(2)}R` : "—"}</td>
                  <td className="dim mono">{hhmmss(t.closed_at)}</td>
                </tr>
              ))}
              {symTrades.length === 0 && <tr><td colSpan={6} className="dim ta-center" style={{ padding: 16 }}>No closed trades yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Decision Log">
        <ul className="activity">
          {symLogs.slice(0, 20).map((l) => (
            <li key={l.id}><span className="dim mono">{hhmmss(l.ts)}</span> <span className="dim">{l.stage}</span> {l.message}</li>
          ))}
          {symLogs.length === 0 && <li className="dim">No decisions for {botId} yet.</li>}
        </ul>
      </Card>
    </>
  );
}
