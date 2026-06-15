import { useState } from "react";
import Card from "../components/common/Card";
import ProgressBar from "../components/common/ProgressBar";
import Icon from "../components/common/Icon";
import { Badge, Field, PageHeader, Toggle } from "../components/common/ui";
import { defaultRiskSettings, riskAlertRows, riskMetrics } from "../data/mock";
import { useApp } from "../app-context";
import CapitalProtection from "../components/safety/CapitalProtection";

export default function RiskCenterPage() {
  const app = useApp();
  const [s, setS] = useState(defaultRiskSettings);
  const set = (k: keyof typeof s, v: number) => setS((p) => ({ ...p, [k]: v }));

  return (
    <>
      <PageHeader
        title="Risk Center"
        subtitle="Global risk controls applied across every bot"
        actions={<button className="btn btn-primary" onClick={() => app.toast("Risk settings saved", "success")}><Icon name="check" size={14} /> Save Settings</button>}
      />

      <CapitalProtection />

      <div className="grid-2-eq">
        <Card title="Global Risk Settings">
          <div className="form-grid-2">
            <Field label="Risk per trade (%)"><input type="number" step="0.1" value={s.riskPct} onChange={(e) => set("riskPct", +e.target.value)} /></Field>
            <Field label="Daily loss limit ($)"><input type="number" value={s.dailyLossLimit} onChange={(e) => set("dailyLossLimit", +e.target.value)} /></Field>
            <Field label="Max drawdown (%)"><input type="number" value={s.maxDrawdown} onChange={(e) => set("maxDrawdown", +e.target.value)} /></Field>
            <Field label="Max open trades"><input type="number" value={s.maxOpenTrades} onChange={(e) => set("maxOpenTrades", +e.target.value)} /></Field>
            <Field label="Consecutive loss limit"><input type="number" value={s.consecutiveLossLimit} onChange={(e) => set("consecutiveLossLimit", +e.target.value)} /></Field>
          </div>
          <div className="toggle-row">
            <div><b>Auto-pause on breach</b><span className="dim">Pause a bot automatically when a limit trips</span></div>
            <Toggle checked={s.autoPause} onChange={(v) => setS((p) => ({ ...p, autoPause: v }))} />
          </div>
        </Card>

        <Card title="Risk Usage">
          <div className="risk-list">
            {riskMetrics.map((r) => (
              <div className="risk-item" key={r.label}>
                <div className="risk-head"><span className="dim">{r.label}</span><b>{r.value}</b></div>
                <ProgressBar pct={r.pct} tone={r.tone} />
                <span className="risk-pct">{r.pct}%</span>
              </div>
            ))}
          </div>
          <div className="estop-box">
            <div><b className="neg">Emergency Stop</b><span className="dim">Immediately halt and flatten every bot.</span></div>
            <button className="btn btn-danger" onClick={() => app.toast("Emergency stop — all bots halted", "error")}><Icon name="close" size={14} /> Stop All Bots</button>
          </div>
        </Card>
      </div>

      <Card title="Risk Alerts">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Time</th><th>Rule</th><th>Level</th><th>Detail</th><th>Bot</th></tr></thead>
            <tbody>
              {riskAlertRows.map((r) => (
                <tr key={r.id}>
                  <td className="dim">{r.time}</td><td><b>{r.rule}</b></td>
                  <td><Badge text={r.level} tone={r.level === "Warning" ? "amber" : "blue"} /></td>
                  <td className="dim">{r.detail}</td><td>{r.bot}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
