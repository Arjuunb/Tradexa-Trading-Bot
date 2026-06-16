import { useState } from "react";
import Card from "../components/common/Card";
import AreaLine from "../components/chart/AreaLine";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import type { TradingState, WebhookStatus } from "../types";
import {
  paperAccount, paperHistory, paperPnlLabels, paperPnlSeries, paperPositions,
  webhookConfig, webhookEvents,
} from "../data/mock";
import { useApp } from "../app-context";

const stateTone = (s: TradingState) => (s === "Active" ? "green" : s === "Paused" ? "amber" : "red");
const statusTone = (s: WebhookStatus) => (s === "Accepted" ? "green" : s === "Duplicate" ? "amber" : "red");

export default function PaperTradingPage() {
  const app = useApp();
  const [tradingState, setTradingState] = useState<TradingState>("Active");

  const setState = (s: TradingState, msg: string, kind: "info" | "success" | "error") => {
    setTradingState(s);
    app.toast(msg, kind);
  };

  return (
    <>
      <PageHeader
        title="Paper Trading"
        subtitle="TradingView webhook → paper execution · no real funds at risk"
        actions={
          <div className="row-actions">
            <button className="btn btn-warn" onClick={() => setState("Paused", "Trading paused — new entries blocked", "info")}><Icon name="pause" size={14} /> Pause All</button>
            <button className="btn btn-danger" onClick={() => setState("Stopped", "Trading stopped — all entries halted", "error")}><Icon name="close" size={14} /> Stop All</button>
            <button className="btn btn-primary" onClick={() => setState("Active", "Trading resumed", "success")}><Icon name="play" size={14} /> Resume</button>
          </div>
        }
      />

      {tradingState !== "Active" && (
        <div className="card" style={{ borderColor: tradingState === "Stopped" ? "#ef4444" : "#f59e0b", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="warning" size={16} className={tradingState === "Stopped" ? "neg" : "amber"} />
          <span><b>Trading {tradingState}.</b> Incoming TradingView webhook entries are blocked. Open positions still close on exit signals. Paper mode only.</span>
        </div>
      )}

      <div className="stat-row">
        <StatCard label="Paper Balance" value={`$${paperAccount.balance.toLocaleString()}`} />
        <StatCard label="Equity" value={`$${paperAccount.equity.toLocaleString()}`} />
        <StatCard label="Realized P&L" value={`+$${paperAccount.pnl.toFixed(2)}`} tone="green" />
        <StatCard label="Open Positions" value={String(paperPositions.length)} />
        <StatCard label="Trading State" value={tradingState} tone={stateTone(tradingState)} />
      </div>

      <Card title="TradingView Webhook" subtitle="Secret-gated endpoint · dedup → risk → sizing → paper execution">
        <div className="webhook-meta">
          <div><span className="dim">Endpoint</span><b className="mono">{webhookConfig.endpoint}</b></div>
          <div><span className="dim">Secret header</span><b className="mono">{webhookConfig.secretHeader}</b> <Badge text={webhookConfig.secretStatus} tone="green" /></div>
          <div><span className="dim">Duplicate window</span><b>{webhookConfig.dedupWindowSec}s</b></div>
          <div><span className="dim">Risk / trade</span><b>{webhookConfig.riskPerTradePct}%</b></div>
          <div><span className="dim">Exposure limit</span><b>{webhookConfig.exposureLimitPct}%</b></div>
        </div>
        <div className="tablewrap" style={{ marginTop: 12 }}>
          <table className="data-table">
            <thead><tr><th>Time</th><th>Alert ID</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Stop</th><th>Stage</th><th>Outcome</th><th>Reason</th></tr></thead>
            <tbody>
              {webhookEvents.map((e) => (
                <tr key={e.id}>
                  <td className="dim mono">{e.time}</td>
                  <td className="mono">{e.alertId}</td>
                  <td><b>{e.symbol}</b></td>
                  <td><Badge text={e.side} tone={e.side === "Buy" ? "green" : e.side === "Sell" ? "red" : "blue"} /></td>
                  <td>{e.entry.toLocaleString()}</td>
                  <td className="dim">{e.stop !== null ? e.stop.toLocaleString() : "—"}</td>
                  <td className="dim">{e.stage}</td>
                  <td><Badge text={e.status} tone={statusTone(e.status)} /></td>
                  <td className="dim">{e.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid-2-1">
        <Card title="Paper P&L" subtitle="Today" className="span-2">
          <div className="chart-md"><AreaLine labels={paperPnlLabels} series={[{ name: "P&L", data: paperPnlSeries, color: "#22c55e" }]} valueFormatter={(v) => `$${v}`} /></div>
        </Card>

        <Card title="Latest Signal">
          <div className="signal-box">
            <span className="signal-action buy">BUY</span>
            <div className="signal-meta">
              <div><span className="dim">Symbol</span><b>BTCUSDT</b></div>
              <div><span className="dim">Entry</span><b>67,500</b></div>
              <div><span className="dim">Stop</span><b>66,800</b></div>
              <div><span className="dim">Outcome</span><b className="pos">Paper trade opened</b></div>
            </div>
          </div>
        </Card>
      </div>

      <Card title="Open Paper Positions">
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

      <Card title="Paper Trade History">
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
    </>
  );
}
