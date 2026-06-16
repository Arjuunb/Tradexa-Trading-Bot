import Card from "../components/common/Card";
import ProgressBar from "../components/common/ProgressBar";
import Icon from "../components/common/Icon";
import { Badge, PageHeader } from "../components/common/ui";
import { useApp } from "../app-context";
import {
  apiPost, useLive, hhmmss,
  type AlertRow, type RiskSummary,
} from "../lib/api";

const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const sevTone = (s: string) => ({ info: "blue", warning: "amber", critical: "red" }[s] as any) ?? "default";

export default function RiskCenterPage() {
  const app = useApp();
  const risk = useLive<RiskSummary>("/risk/summary", 2000);
  const alerts = useLive<AlertRow[]>("/ledger/alerts?limit=60", 3000);
  const r = risk.data;

  const exposureUse = r && r.exposure_limit_pct > 0 ? Math.min(100, (r.exposure_pct / r.exposure_limit_pct) * 100) : 0;
  const tradesUse = r && r.max_open_positions > 0 ? Math.min(100, (r.open_positions / r.max_open_positions) * 100) : 0;
  const tone = (u: number) => (u >= 90 ? "red" : u >= 60 ? "amber" : "green");

  const stop = async () => {
    try { await apiPost("/controls/stop-all"); app.toast("Emergency stop — trading halted", "error"); risk.refetch(); }
    catch { app.toast("Backend not reachable", "error"); }
  };
  const resume = async () => {
    try { await apiPost("/controls/resume"); app.toast("Trading resumed", "success"); risk.refetch(); }
    catch { app.toast("Backend not reachable", "error"); }
  };

  return (
    <>
      <PageHeader title="Risk Center" subtitle="Live risk usage across the engine · paper mode" />

      {risk.error && !r && (
        <div className="card" style={{ borderColor: "#ef4444" }}>
          <Icon name="warning" size={15} className="neg" /> Backend not reachable. Start the API to see live risk usage.
        </div>
      )}

      <div className="grid-2-eq">
        <Card title="Risk Configuration" subtitle="set on the backend (env)">
          <div className="risk-list">
            <div className="risk-item"><div className="risk-head"><span className="dim">Risk per trade</span><b>{r ? pct(r.risk_per_trade_pct) : "—"}</b></div></div>
            <div className="risk-item"><div className="risk-head"><span className="dim">Exposure limit</span><b>{r ? pct(r.exposure_limit_pct) : "—"}</b></div></div>
            <div className="risk-item"><div className="risk-head"><span className="dim">Max open positions</span><b>{r?.max_open_positions ?? "—"}</b></div></div>
            <div className="risk-item"><div className="risk-head"><span className="dim">Trading state</span><b className={r?.trading_state === "Active" ? "pos" : "neg"}>{r?.trading_state ?? "—"}</b></div></div>
            <div className="risk-item"><div className="risk-head"><span className="dim">Risk-blocked signals</span><b>{r?.rejections ?? 0}</b></div></div>
          </div>
          <div className="estop-box">
            <div><b className="neg">Emergency Stop</b><span className="dim">Immediately block all new entries.</span></div>
            <div className="row-actions" style={{ gap: 8 }}>
              <button className="btn btn-danger" onClick={stop}><Icon name="close" size={14} /> Stop All</button>
              <button className="btn btn-primary" onClick={resume}><Icon name="play" size={14} /> Resume</button>
            </div>
          </div>
        </Card>

        <Card title="Risk Usage">
          <div className="risk-list">
            <div className="risk-item">
              <div className="risk-head"><span className="dim">Exposure</span><b>{r ? pct(r.exposure_pct) : "—"} / {r ? pct(r.exposure_limit_pct) : "—"}</b></div>
              <ProgressBar pct={Math.round(exposureUse)} tone={tone(exposureUse)} />
              <span className="risk-pct">{Math.round(exposureUse)}% of limit</span>
            </div>
            <div className="risk-item">
              <div className="risk-head"><span className="dim">Open Positions</span><b>{r?.open_positions ?? 0} / {r?.max_open_positions ?? 0}</b></div>
              <ProgressBar pct={Math.round(tradesUse)} tone={tone(tradesUse)} />
              <span className="risk-pct">{Math.round(tradesUse)}% used</span>
            </div>
            <div className="risk-item">
              <div className="risk-head"><span className="dim">Realized P&amp;L</span><b className={(r?.realized_pnl ?? 0) >= 0 ? "pos" : "neg"}>{(r?.realized_pnl ?? 0) >= 0 ? "+" : ""}${(r?.realized_pnl ?? 0).toFixed(2)}</b></div>
            </div>
            <div className="risk-item">
              <div className="risk-head"><span className="dim">Equity</span><b>${(r?.equity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</b></div>
            </div>
          </div>
        </Card>
      </div>

      <Card title="Risk & Trade Alerts">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Time</th><th>Severity</th><th>Category</th><th>Title</th><th>Detail</th></tr></thead>
            <tbody>
              {(alerts.data ?? []).map((a) => (
                <tr key={a.id}>
                  <td className="dim mono">{hhmmss(a.ts)}</td>
                  <td><Badge text={a.severity} tone={sevTone(a.severity)} /></td>
                  <td className="dim">{a.category}</td>
                  <td><b>{a.title}</b></td>
                  <td className="dim">{a.detail}</td>
                </tr>
              ))}
              {(alerts.data?.length ?? 0) === 0 && <tr><td colSpan={5} className="dim ta-center" style={{ padding: 18 }}>No alerts yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
