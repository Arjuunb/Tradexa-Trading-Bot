import { useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader } from "../components/common/ui";
import { useApp } from "../app-context";
import { apiPost, apiPostJson, useLive, type PaperTradeRow, type SystemStatus, type AlertChannels, type AlertEvent, type EconProtection } from "../lib/api";
import { getProgress } from "../lib/progress";

const STAGES = ["Backtest", "Simulation", "Paper Trading", "Live Trading"];

export default function SafetyCenterPage() {
  const app = useApp();
  const sys = useLive<SystemStatus>("/system/status", 3000);
  const trades = useLive<PaperTradeRow[]>("/paper/trades", 4000);
  const prog = getProgress();

  const done = [
    prog.backtest,
    prog.simulation,
    (trades.data?.length ?? 0) > 0,
    !!sys.data?.broker_connected,
  ];

  const killAll = async () => {
    if (!window.confirm("KILL SWITCH: immediately halt all trading and stop the engine?")) return;
    try {
      await apiPost("/controls/stop-all");
      await apiPost("/engine/stop");
      app.toast("All trading halted", "error");
      sys.refetch();
    } catch {
      app.toast("Backend not reachable", "error");
    }
  };

  return (
    <>
      <PageHeader title="Safety Center" subtitle="Progression flow, data separation and emergency controls" />

      <Card title="Required Progression" subtitle="strategies can never skip a step">
        <div className="flow-row" style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          {STAGES.map((name, i) => (
            <span key={name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="ui-badge" style={{ background: done[i] ? "#22c55e22" : "#5b647822", color: done[i] ? "#22c55e" : "#8a93a6", display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Icon name={done[i] ? "check" : "lock"} size={13} /> {name}
              </span>
              {i < STAGES.length - 1 && <Icon name="chevron" size={14} className="dim" />}
            </span>
          ))}
        </div>
        <p className="dim" style={{ marginTop: 10 }}>
          Live stays locked until every earlier stage has real, recorded results and a broker is connected.
        </p>
      </Card>

      <Card title="Data Separation" subtitle="datasets are never mixed or cross-shown">
        <div className="risk-list">
          <div className="risk-item"><b>Backtest</b> <span className="dim">— historical, on the Backtesting page.</span></div>
          <div className="risk-item"><b>Simulation</b> <span className="dim">— forward sim, on the Simulation page.</span></div>
          <div className="risk-item"><b>Paper</b> <span className="dim">— real engine, simulated money, on the Paper Trading page.</span></div>
          <div className="risk-item"><b>Live</b> <span className="dim">— locked; no live data exists until a broker is connected.</span></div>
        </div>
        <p className="dim" style={{ marginTop: 8 }}>Simulated and paper performance are always labelled as such — never shown as live results.</p>
      </Card>

      <Card title="Emergency Controls">
        <div className="estop-box">
          <div><b className="neg">Kill Switch</b><span className="dim">Immediately halt all trading and stop the engine (paper).</span></div>
          <button className="btn btn-danger" onClick={killAll}><Icon name="close" size={14} /> Stop Everything</button>
        </div>
      </Card>

      <AlertsPanel />
      <EconProtectionPanel />
    </>
  );
}

function EconProtectionPanel() {
  const e = useLive<EconProtection>("/econ/protection", 15000).data;
  const tone = e?.mode === "normal" ? "green" : e?.mode === "caution" ? "amber" : "red";
  return (
    <Card title="Economic Event Protection" subtitle="halt / reduce size / widen stops around CPI · FOMC · NFP · rate decisions"
      right={e && <Badge text={e.mode} tone={tone as any} />}>
      {!e ? <div className="dim">—</div> : (
        <>
          <div className="risk-list">
            <div className="risk-item"><span className="dim">Next high-impact event</span> <b>{e.next_event ? `${e.next_event.name} · in ${e.minutes_to_event! >= 60 ? `${(e.minutes_to_event! / 60).toFixed(1)}h` : `${e.minutes_to_event}m`}` : "none scheduled"}</b></div>
            <div className="risk-item"><span className="dim">Risk multiplier</span> <b>{Math.round(e.risk_multiplier * 100)}%</b></div>
            <div className="risk-item"><span className="dim">Stop multiplier</span> <b>{e.stop_multiplier}×</b></div>
            <div className="risk-item"><span className="dim">New entries</span> <Badge text={e.halt_new_entries ? "halted" : "allowed"} tone={e.halt_new_entries ? "red" : "green"} /></div>
          </div>
          {e.actions.length > 0 && (
            <div className="card" style={{ marginTop: 8, borderColor: "var(--gold)", background: "rgba(234,181,79,0.08)" }}>
              <b className="amber"><Icon name="shield" size={13} /> Protective actions</b>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.5 }}>{e.actions.map((a, i) => <li key={i}>{a}</li>)}</ul>
            </div>
          )}
          {!e.connected && <p className="dim" style={{ fontSize: 11, marginTop: 8 }}><Icon name="info" size={12} /> {e.note}</p>}
        </>
      )}
    </Card>
  );
}

function AlertsPanel() {
  const app = useApp();
  const ch = useLive<{ channels: AlertChannels }>("/alerts/channels", 8000);
  const live = useLive<{ alerts: AlertEvent[] }>("/alerts/check", 10000);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const c = ch.data?.channels;

  const save = async () => {
    try { const r = await apiPostJson<any>("/alerts/channels", keys); if (r?.error || r?.detail) app.toast(r.error || r.detail, "error"); else { app.toast("Alert channels saved", "success"); setKeys({}); ch.refetch(); } }
    catch { app.toast("Saving needs the webhook secret", "error"); }
  };
  const test = async () => {
    try { await apiPost("/alerts/test"); app.toast("Test alert sent to connected channels", "success"); }
    catch { app.toast("Test needs the webhook secret", "error"); }
  };
  const sev = (s: string) => (s === "critical" ? "red" : s === "warning" ? "amber" : "blue");
  const chip = (name: string, st?: { connected: boolean; note: string }) => (
    <div className="risk-item"><span className="dim">{name}</span>
      <Badge text={st?.connected ? "Connected" : "Not connected"} tone={st?.connected ? "green" : "default"} /></div>
  );

  return (
    <Card title="Alerts" subtitle="trade / risk / sentiment alerts to Telegram, Discord, Email"
      right={<div className="row-actions" style={{ gap: 6 }}><button className="btn btn-soft" onClick={test}><Icon name="bell" size={13} /> Test</button></div>}>
      <div className="grid-2-eq">
        <div>
          <div className="card-subtitle" style={{ marginBottom: 6 }}>Channels</div>
          <div className="risk-list">
            {chip("Telegram", c?.telegram)}
            {chip("Discord", c?.discord)}
            {chip("Email", c?.email)}
          </div>
          <div className="form-grid-2" style={{ marginTop: 8 }}>
            <label className="field"><span className="field-label">Discord webhook</span>
              <input type="password" placeholder={c?.discord?.connected ? "•••• connected" : "webhook URL"} value={keys.discord_webhook ?? ""} onChange={(e) => setKeys((k) => ({ ...k, discord_webhook: e.target.value }))} /></label>
            <label className="field"><span className="field-label">Alert email</span>
              <input placeholder="you@example.com" value={keys.email_to ?? ""} onChange={(e) => setKeys((k) => ({ ...k, email_to: e.target.value }))} /></label>
            <label className="field"><span className="field-label">SMTP host</span>
              <input placeholder="smtp.gmail.com" value={keys.smtp_host ?? ""} onChange={(e) => setKeys((k) => ({ ...k, smtp_host: e.target.value }))} /></label>
            <label className="field"><span className="field-label">SMTP user / pass</span>
              <input type="password" placeholder="user:pass via two fields" value={keys.smtp_user ?? ""} onChange={(e) => setKeys((k) => ({ ...k, smtp_user: e.target.value }))} /></label>
          </div>
          <button className="btn btn-primary" style={{ marginTop: 8 }} onClick={save}><Icon name="check" size={13} /> Save Channels</button>
          <p className="dim" style={{ fontSize: 11, marginTop: 6 }}>Missing channels show “Not connected” — never faked. Telegram uses the env token.</p>
        </div>
        <div>
          <div className="card-subtitle" style={{ marginBottom: 6 }}>Live alerts now</div>
          {(live.data?.alerts?.length ?? 0) === 0 ? <div className="dim" style={{ fontSize: 13 }}>No alert conditions firing right now.</div> : (
            <div className="alert-stack">
              {live.data!.alerts.map((a, i) => (
                <div key={i} className="risk-item" style={{ alignItems: "flex-start", flexDirection: "column", gap: 2 }}>
                  <span className="row-actions" style={{ gap: 6 }}><Badge text={a.severity} tone={sev(a.severity) as any} /> <b>{a.title}</b></span>
                  <span className="dim" style={{ fontSize: 12 }}>{a.detail}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
