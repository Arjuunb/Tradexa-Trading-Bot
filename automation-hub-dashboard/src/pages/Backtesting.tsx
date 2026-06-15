import { useState } from "react";
import Card from "../components/common/Card";
import AreaLine from "../components/chart/AreaLine";
import Icon from "../components/common/Icon";
import { Badge, Field, PageHeader, StatCard } from "../components/common/ui";
import { backtestResult, strategies } from "../data/mock";

export default function BacktestingPage({ initialStrategy }: { initialStrategy?: string }) {
  const [ran, setRan] = useState(true);
  const [strategy, setStrategy] = useState(initialStrategy || strategies[0].name);
  const r = backtestResult;

  return (
    <>
      <PageHeader title="Backtesting" subtitle="Test a strategy on historical data (mock results)" />

      <Card title="Configuration" right={
        <div className="row-actions">
          <button className="btn btn-primary" onClick={() => setRan(true)}><Icon name="play" size={14} /> Run Backtest</button>
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
          <Field label="Timeframe"><select><option>5m</option><option>15m</option><option selected>1h</option><option>4h</option></select></Field>
          <Field label="Start date"><input type="date" defaultValue="2025-01-01" /></Field>
          <Field label="End date"><input type="date" defaultValue="2025-05-22" /></Field>
          <Field label="Starting balance"><input defaultValue="10000" /></Field>
          <Field label="Risk per trade (%)"><input defaultValue="1.0" /></Field>
        </div>
      </Card>

      {ran && (
        <>
          <div className="stat-row six">
            <StatCard label="Net P&L" value={r.netPnl} tone="green" />
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
        </>
      )}
    </>
  );
}
