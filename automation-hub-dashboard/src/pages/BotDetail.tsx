import type { Bot, BotStatus } from "../types";
import Card from "../components/common/Card";
import AreaLine from "../components/chart/AreaLine";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard, StatusBadge } from "../components/common/ui";
import { useApp } from "../app-context";
import { strategies } from "../data/mock";

interface Props {
  bot: Bot | undefined;
  setBots: React.Dispatch<React.SetStateAction<Bot[]>>;
}

const money = (n: number) => (n === 0 ? "$0.00" : `${n > 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`);

// Deterministic equity curve synthesised from the bot's total P&L (no RNG, so
// it stays stable across re-renders).
function botEquity(bot: Bot): number[] {
  const base = 10000;
  const end = base + bot.totalPnl;
  const n = 12;
  return Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1);
    const wobble = Math.sin(i * 1.7) * Math.abs(bot.totalPnl) * 0.05;
    return Math.round(base + (end - base) * t + wobble);
  });
}

const sampleTrades = (bot: Bot) => [
  { id: "d1", time: "10:24", side: "Long", entry: 100, exit: 102, pnl: bot.todayPnl * 0.4, result: "Win" },
  { id: "d2", time: "09:58", side: "Short", entry: 102, exit: 101, pnl: bot.todayPnl * 0.35, result: "Win" },
  { id: "d3", time: "09:31", side: "Long", entry: 99, exit: 98, pnl: -Math.abs(bot.todayPnl) * 0.2, result: "Loss" },
];

export default function BotDetail({ bot, setBots }: Props) {
  const app = useApp();

  if (!bot) {
    return (
      <>
        <PageHeader title="Bot not found" actions={<button className="btn btn-ghost" onClick={() => app.go("Bots")}>← Bots</button>} />
        <div className="empty-state">This bot no longer exists.</div>
      </>
    );
  }

  const setStatus = (status: BotStatus) => setBots((p) => p.map((b) => (b.id === bot.id ? { ...b, status } : b)));
  const active = bot.status === "Running" || bot.status === "Live";
  const stratName = strategies.find((s) => s.name.startsWith(bot.strategy))?.name ?? strategies[0].name;
  const labels = ["", "", "", "", "", "", "", "", "", "", "", ""];

  return (
    <>
      <PageHeader
        title={bot.name}
        subtitle={`${bot.strategy} · ${bot.pair} · ${bot.timeframe}`}
        actions={
          <div className="row-actions">
            <button className="btn btn-ghost" onClick={() => app.go("Bots")}>← Bots</button>
            {active
              ? <button className="btn btn-warn" onClick={() => setStatus("Paused")}><Icon name="pause" size={14} /> Pause</button>
              : <button className="btn btn-primary" onClick={() => setStatus("Running")}><Icon name="play" size={14} /> Start</button>}
            <button className="btn btn-ghost" onClick={() => setStatus("Stopped")}><Icon name="close" size={14} /> Stop</button>
            <button className="btn btn-soft" onClick={() => app.backtest(stratName)}><Icon name="history" size={14} /> Backtest</button>
          </div>
        }
      />

      <div className="stat-row six">
        <StatCard label="Status" value={bot.status} />
        <StatCard label="Today P&L" value={money(bot.todayPnl)} tone={bot.todayPnl >= 0 ? "green" : "red"} />
        <StatCard label="Total P&L" value={money(bot.totalPnl)} tone={bot.totalPnl >= 0 ? "green" : "red"} />
        <StatCard label="Risk / trade" value={`${bot.riskPct}%`} />
        <StatCard label="Strategy" value={bot.strategy} />
        <StatCard label="Symbol" value={bot.pair} />
      </div>

      <Card title="Equity Curve" subtitle={bot.name} right={<StatusBadge status={bot.status} />}>
        <div className="chart-md">
          <AreaLine labels={labels} series={[{ name: "Equity", data: botEquity(bot), color: "#8b5cf6" }]} yFormatter={(v) => `$${(v / 1000).toFixed(1)}K`} valueFormatter={(v) => `$${v.toLocaleString()}`} />
        </div>
      </Card>

      <Card title="Recent Trades">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Time</th><th>Pair</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Result</th></tr></thead>
            <tbody>
              {sampleTrades(bot).map((t) => (
                <tr key={t.id}>
                  <td className="dim">{t.time}</td><td>{bot.pair}</td>
                  <td><Badge text={t.side} tone={t.side === "Long" ? "green" : "red"} /></td>
                  <td>{t.entry}</td><td>{t.exit}</td>
                  <td className={t.pnl >= 0 ? "pos" : "neg"}>{money(t.pnl)}</td>
                  <td><Badge text={t.result} tone={t.result === "Win" ? "green" : "red"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
