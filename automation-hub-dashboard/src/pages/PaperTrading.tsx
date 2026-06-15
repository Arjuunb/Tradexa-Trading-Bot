import { useState } from "react";
import Card from "../components/common/Card";
import AreaLine from "../components/chart/AreaLine";
import Icon from "../components/common/Icon";
import { Badge, Field, PageHeader, StatCard } from "../components/common/ui";
import {
  executionLog, paperAccount, paperHistory, paperPnlLabels, paperPnlSeries, paperPositions,
} from "../data/mock";
import { useApp } from "../app-context";

export default function PaperTradingPage() {
  const app = useApp();
  const [running, setRunning] = useState(true);
  const [side, setSide] = useState<"Buy" | "Sell">("Buy");

  return (
    <>
      <PageHeader
        title="Paper Trading"
        subtitle="Simulated account · no real funds at risk"
        actions={
          <div className="row-actions">
            {running ? (
              <button className="btn btn-warn" onClick={() => { setRunning(false); app.toast("Paper bot paused", "info"); }}><Icon name="pause" size={14} /> Pause</button>
            ) : (
              <button className="btn btn-primary" onClick={() => { setRunning(true); app.toast("Paper bot started", "success"); }}><Icon name="play" size={14} /> Start</button>
            )}
            <button className="btn btn-ghost" onClick={() => app.toast("Paper account reset to $10,000", "info")}><Icon name="history" size={14} /> Reset Account</button>
          </div>
        }
      />

      <div className="stat-row">
        <StatCard label="Paper Balance" value={`$${paperAccount.balance.toLocaleString()}`} />
        <StatCard label="Equity" value={`$${paperAccount.equity.toLocaleString()}`} />
        <StatCard label="Realized P&L" value={`+$${paperAccount.pnl.toFixed(2)}`} tone="green" />
        <StatCard label="Open P&L" value={`+$${paperAccount.openPnl.toFixed(2)}`} tone="green" />
        <StatCard label="Margin Used" value={paperAccount.marginUsed} sub={`Status: ${running ? "Running" : "Paused"}`} />
      </div>

      <div className="grid-2-1">
        <Card title="Paper P&L" subtitle="Today" className="span-2">
          <div className="chart-md"><AreaLine labels={paperPnlLabels} series={[{ name: "P&L", data: paperPnlSeries, color: "#22c55e" }]} valueFormatter={(v) => `$${v}`} /></div>
        </Card>

        <Card title="Current Signal">
          <div className="signal-box">
            <span className="signal-action buy">BUY</span>
            <div className="signal-meta">
              <div><span className="dim">Pair</span><b>ETH/USDT</b></div>
              <div><span className="dim">Strategy</span><b>RSI Scalper</b></div>
              <div><span className="dim">Confidence</span><b className="pos">72%</b></div>
              <div><span className="dim">Reason</span><b>RSI crossed up 30</b></div>
            </div>
          </div>
        </Card>
      </div>

      <div className="grid-2-1">
        <Card title="Open Paper Positions" className="span-2">
          <div className="tablewrap">
            <table className="data-table">
              <thead><tr><th>Pair</th><th>Side</th><th>Size</th><th>Entry</th><th>Mark</th><th>P&amp;L</th></tr></thead>
              <tbody>
                {paperPositions.map((p) => (
                  <tr key={p.id}>
                    <td><b>{p.pair}</b></td>
                    <td><Badge text={p.side} tone={p.side === "Long" ? "green" : "red"} /></td>
                    <td>{p.size}</td><td>{p.entry.toLocaleString()}</td><td>{p.mark.toLocaleString()}</td>
                    <td className={p.pnl >= 0 ? "pos" : "neg"}>{p.pnl >= 0 ? "+" : ""}${p.pnl.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Simulated Order">
          <div className="order-side">
            <button className={`order-tab ${side === "Buy" ? "buy" : ""}`} onClick={() => setSide("Buy")}>Buy</button>
            <button className={`order-tab ${side === "Sell" ? "sell" : ""}`} onClick={() => setSide("Sell")}>Sell</button>
          </div>
          <Field label="Pair"><input defaultValue="BTC/USDT" /></Field>
          <Field label="Size"><input defaultValue="0.10" /></Field>
          <Field label="Order type">
            <select><option>Market</option><option>Limit</option></select>
          </Field>
          <button className={`btn full ${side === "Buy" ? "btn-primary" : "btn-danger"}`} style={{ marginTop: 10 }}
            onClick={() => app.toast(`Simulated ${side} order placed`, "success")}>
            Place {side} Order
          </button>
        </Card>
      </div>

      <div className="grid-2-1">
        <Card title="Paper Trade History" className="span-2">
          <div className="tablewrap">
            <table className="data-table">
              <thead><tr><th>Time</th><th>Pair</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>R:R</th><th>Result</th></tr></thead>
              <tbody>
                {paperHistory.map((t) => (
                  <tr key={t.id}>
                    <td className="dim">{t.time}</td><td>{t.pair}</td>
                    <td><Badge text={t.side} tone={t.side === "Long" ? "green" : "red"} /></td>
                    <td>{t.entry}</td><td>{t.exit}</td>
                    <td className={t.pnl >= 0 ? "pos" : "neg"}>{t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}</td>
                    <td>{t.rr}</td>
                    <td><Badge text={t.result} tone={t.result === "Win" ? "green" : "red"} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Execution Log">
          <div className="exec-log">
            {executionLog.map((e, i) => (
              <div className="exec-line" key={i}><span className="exec-time">{e.time}</span> {e.msg}</div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
