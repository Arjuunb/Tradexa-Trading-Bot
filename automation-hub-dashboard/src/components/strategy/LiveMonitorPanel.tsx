import { useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { apiPost, useLive, type MonitorStatus, type MonitorFinding } from "../../lib/api";

/**
 * The monitoring agent's LIVE state — what the background loop last concluded
 * about the deployed strategy.
 *
 * This polls a status endpoint that returns the last evaluation without
 * recomputing it. Re-running a one-year backtest on every dashboard poll would
 * be absurd, so the reading carries its own timestamp instead and a stale one
 * is shown as stale rather than passed off as current.
 */
const STATUS: Record<string, { text: string; tone: "green" | "amber" | "red" | "default" }> = {
  in_line: { text: "Tracking backtest", tone: "green" },
  info: { text: "Note", tone: "default" },
  warning: { text: "Deviation", tone: "amber" },
  critical: { text: "Action needed", tone: "red" },
  warming_up: { text: "Warming up", tone: "default" },
  no_baseline: { text: "No baseline", tone: "default" },
  no_strategy: { text: "Nothing deployed", tone: "default" },
};

const SEV: Record<MonitorFinding["severity"], "red" | "amber" | "default"> = {
  critical: "red", warning: "amber", info: "default",
};

const ago = (iso?: string | null) => {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
};

export default function LiveMonitorPanel() {
  const st = useLive<MonitorStatus>("/strategy/monitor/status", 30000);
  const [busy, setBusy] = useState(false);
  const d = st.data;
  const res = d?.result;
  const badge = res ? STATUS[res.status] ?? STATUS.info : null;

  const recheck = async () => {
    setBusy(true);
    try { await apiPost("/strategy/monitor/check"); st.refetch(); }
    catch { /* the status line already shows the last good reading */ }
    finally { setBusy(false); }
  };

  return (
    <Card title="AI Monitoring Agent"
          subtitle="watches the deployed strategy against a backtest of that same spec"
          right={
            <div className="toolbar" style={{ gap: 6 }}>
              {badge && <Badge text={badge.text} tone={badge.tone} />}
              <button className="btn btn-soft btn-sm" disabled={busy} onClick={recheck}>
                <Icon name="refresh" size={12} /> {busy ? "Checking…" : "Check now"}
              </button>
            </div>
          }>
      <div className="dim" style={{ fontSize: 11.5 }}>
        {d?.running ? `Checking every ${Math.round((d.interval_s || 0) / 60)} min` : "Loop not running"}
        {" · last check "}{ago(d?.last_check)}
        {res?.baseline_cached && res.baseline_computed_at &&
          <> · baseline from {ago(res.baseline_computed_at)}</>}
        {res?.strategy && <> · {res.strategy}</>}
      </div>

      {res?.timeframe_warning && (
        <div className="dim" style={{ marginTop: 8, fontSize: 11.5 }}>
          <Icon name="warning" size={11} /> {res.timeframe_warning}
        </div>
      )}

      {res?.note && (
        <div className="dim" style={{ marginTop: 8, fontSize: 12.5, padding: 8,
          borderRadius: 7, border: "1px solid rgba(255,255,255,.08)" }}>
          {res.note}
        </div>
      )}

      {!!res?.findings?.length && res.findings.map((f) => (
        <div key={f.key} className="builder-rule" style={{ marginTop: 8, padding: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <b style={{ fontSize: 13 }}>{f.title}</b>
            <Badge text={f.severity} tone={SEV[f.severity]} />
          </div>
          <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{f.detail}</div>
          <div className="dim" style={{ fontSize: 11.5, marginTop: 4 }}>
            {f.evidence.map((e) => `${e.stat}: ${e.value}`).join(" · ")}
          </div>
          <div className="dim" style={{ fontSize: 11.5, marginTop: 4 }}>
            <b>What to do:</b> {f.recommendation}
          </div>
        </div>
      ))}

      <div className="dim" style={{ fontSize: 11, marginTop: 10 }}>
        Deviations are also raised as alerts, at most once an hour per finding.
        The agent only reports — it never edits a strategy, changes risk, or stops a bot.
      </div>
    </Card>
  );
}
