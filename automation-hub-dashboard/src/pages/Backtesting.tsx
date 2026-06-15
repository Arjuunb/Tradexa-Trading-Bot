import { useState } from "react";
import Card from "../components/common/Card";
import AreaLine from "../components/chart/AreaLine";
import Icon from "../components/common/Icon";
import { Badge, Field, PageHeader, StatCard } from "../components/common/ui";
import { backtestResult, strategies } from "../data/mock";

interface BtTrade {
  id: string; time: string; pair: string; side: "Long" | "Short";
  entry: number; exit: number; pnl: number; rr: number; result: "Win" | "Loss";
}
interface Result {
  netPnl: string; winRate: string; profitFactor: string; maxDrawdown: string;
  totalTrades: string; avgRR: string;
  equityLabels: string[]; equity: number[]; drawdown: number[]; trades: BtTrade[];
}

const rnd = (a: number, b: number) => a + Math.random() * (b - a);

// Generate a fresh, plausible backtest result so "Run" feels interactive.
function genResult(): Result {
  const labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"];
  const equity = [10000];
  for (let i = 1; i < labels.length; i++) equity.push(Math.round(equity[i - 1] * (1 + rnd(-0.03, 0.1))));
  const drawdown = labels.map((_, i) => (i === 0 ? 0 : -Math.round(rnd(1, 9) * 10) / 10));
  const net = equity[equity.length - 1] - 10000;
  const total = Math.round(rnd(80, 200));
  const pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT"];
  const trades = Array.from({ length: 4 }, (_, i) => {
    const win = Math.random() > 0.4;
    const pnl = Math.round((win ? rnd(60, 240) : -rnd(40, 120)) * 10) / 10;
    return {
      id: "g" + i, time: `2025-05-${20 - i} ${10 + i}:00`, pair: pairs[i % pairs.length],
      side: (Math.random() > 0.5 ? "Long" : "Short") as "Long" | "Short",
      entry: Math.round(rnd(60000, 67000)), exit: Math.round(rnd(60000, 67000)),
      pnl, rr: Math.round((win ? rnd(1.2, 2.6) : -1) * 10) / 10,
      result: (win ? "Win" : "Loss") as "Win" | "Loss",
    };
  });
  return {
    netPnl: `${net >= 0 ? "+" : "-"}$${Math.abs(net).toLocaleString()}`,
    winRate: `${rnd(54, 68).toFixed(1)}%`,
    profitFactor: rnd(1.4, 2.6).toFixed(2),
    maxDrawdown: `${Math.abs(Math.min(...drawdown)).toFixed(1)}%`,
    totalTrades: `${total}`,
    avgRR: rnd(1.3, 2.1).toFixed(2),
    equityLabels: labels, equity, drawdown, trades,
  };
}

export default function BacktestingPage({ initialStrategy }: { initialStrategy?: string }) {
  const hasInitial = !!initialStrategy && strategies.some((s) => s.name === initialStrategy);
  const [strategy, setStrategy] = useState(hasInitial ? initialStrategy! : strategies[0].name);
  const [result, setResult] = useState<Result>(backtestResult);
  const [running, setRunning] = useState(false);
  const [ran, setRan] = useState(true);

  const run = () => {
    setRunning(true);
    setTimeout(() => {
      setResult(genResult());
      setRunning(false);
      setRan(true);
    }, 650);
  };

  const r = result;

  return (
    <>
      <PageHeader title="Backtesting" subtitle="Test a strategy on historical data (mock results)" />

      <Card title="Configuration" right={
        <div className="row-actions">
          <button className="btn btn-primary" onClick={run} disabled={running}>
            <Icon name={running ? "history" : "play"} size={14} /> {running ? "Running…" : "Run Backtest"}
          </button>
          {ran && <button className="btn btn-ghost"><Icon name="check" size={14} /> Save</button>}
        </div>
      }>
        <div className="form-grid-3">
          <Field label="Strategy">
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {strategies.map((s) => <option key={s.id}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="Symbol"><select><option>BTC/USDT</option><option>ETH/USDT</option><option>SOL/USDT</option></select></Field>
          <Field label="Timeframe"><select><option>5m</option><option>15m</option><option defaultValue="1h">1h</option><option>4h</option></select></Field>
          <Field label="Start date"><input type="date" defaultValue="2025-01-01" /></Field>
          <Field label="End date"><input type="date" defaultValue="2025-05-22" /></Field>
          <Field label="Starting balance"><input defaultValue="10000" /></Field>
          <Field label="Risk per trade (%)"><input defaultValue="1.0" /></Field>
        </div>
      </Card>

      {ran && (
        <div className={running ? "is-running" : ""}>
          <div className="stat-row six">
            <StatCard label="Net P&L" value={r.netPnl} tone={r.netPnl.startsWith("+") ? "green" : "red"} />
            <StatCard label="Win Rate" value={r.winRate} />
            <StatCard label="Profit Factor" value={r.profitFactor} />
            <StatCard label="Max Drawdown" value={r.maxDrawdown} tone="red" />
            <StatCard label="Total Trades" value={r.totalTrades} />
            <StatCard label="Avg R:R" value={r.avgRR} />
          </div>

          <div className="grid-2-eq">
            <Card title="Equity Curve">
              <div className="chart-md"><AreaLine labels={r.equityLabels} series={[{ name: "Equity", data: r.equity, color: "#8b5cf6" }]} yFormatter={(v) => `$${(v / 1000).toFixed(0)}K`} valueFormatter={(v) => `$${v.toLocaleString()}`} /></div>
            </Card>
            <Card title="Drawdown">
              <div className="chart-md"><AreaLine labels={r.equityLabels} series={[{ name: "Drawdown", data: r.drawdown, color: "#ef4444" }]} yFormatter={(v) => `${v}%`} valueFormatter={(v) => `${v}%`} /></div>
            </Card>
          </div>

          <Card title="Trade Results" subtitle={`${r.trades.length} of ${r.totalTrades} shown`}>
            <div className="tablewrap">
              <table className="data-table">
                <thead><tr><th>Time</th><th>Pair</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>R:R</th><th>Result</th></tr></thead>
                <tbody>
                  {r.trades.map((t) => (
                    <tr key={t.id}>
                      <td className="dim">{t.time}</td><td>{t.pair}</td>
                      <td><Badge text={t.side} tone={t.side === "Long" ? "green" : "red"} /></td>
                      <td>{t.entry.toLocaleString()}</td><td>{t.exit.toLocaleString()}</td>
                      <td className={t.pnl >= 0 ? "pos" : "neg"}>{t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}</td>
                      <td>{t.rr}</td>
                      <td><Badge text={t.result} tone={t.result === "Win" ? "green" : "red"} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
