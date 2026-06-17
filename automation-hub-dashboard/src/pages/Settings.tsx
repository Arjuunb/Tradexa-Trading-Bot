import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, Field, PageHeader } from "../components/common/ui";
import { useApp } from "../app-context";
import { apiPostJson, useLive, type BotSettings } from "../lib/api";

// Real configuration. Risk/position params are editable, applied live, and
// persisted on the backend (survive restart). Everything else is env-set and
// shown read-only with real values — no fake fields.
export default function SettingsPage() {
  const app = useApp();
  const { data, error, refetch } = useLive<BotSettings>("/settings", 8000);
  const [f, setF] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data && Object.keys(f).length === 0) {
      setF({
        risk: (data.editable.risk_per_trade_pct * 100).toString(),
        exposure: (data.editable.exposure_limit_pct * 100).toString(),
        drawdown: (data.editable.max_drawdown_pct * 100).toString(),
        maxpos: String(data.editable.max_open_positions),
        dedup: String(data.editable.dedup_window_s),
        daily: (data.editable.max_daily_loss_pct * 100).toString(),
        sstart: String(data.editable.session_start),
        send: String(data.editable.session_end),
      });
    }
  }, [data, f]);

  const set = (k: string) => (e: ChangeEvent<HTMLInputElement>) => setF((p) => ({ ...p, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      await apiPostJson("/settings", {
        risk_per_trade_pct: Number(f.risk) / 100,
        exposure_limit_pct: Number(f.exposure) / 100,
        max_drawdown_pct: Number(f.drawdown) / 100,
        max_open_positions: Math.round(Number(f.maxpos)),
        dedup_window_s: Math.round(Number(f.dedup)),
        max_daily_loss_pct: Number(f.daily) / 100,
        session_start: Math.round(Number(f.sstart)),
        session_end: Math.round(Number(f.send)),
      });
      app.toast("Settings saved & applied (persisted on backend)", "success");
      refetch();
    } catch {
      app.toast("Save failed — backend unreachable or invalid value", "error");
    } finally {
      setSaving(false);
    }
  };

  const ro = data?.readonly;

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="real configuration · risk values persist across restarts"
        actions={<button className="btn btn-primary" disabled={saving || !data} onClick={save}><Icon name="check" size={14} /> {saving ? "Saving…" : "Save Settings"}</button>}
      />

      {error && !data && (
        <div className="card" style={{ borderColor: "#ef4444" }}>
          <Icon name="warning" size={15} className="neg" /> Backend not reachable — settings unavailable.
        </div>
      )}

      <div className="grid-2-eq">
        <Card title="Risk Management" subtitle="editable · applied live + persisted">
          <div className="form-grid-2">
            <Field label="Risk per trade (%)"><input value={f.risk ?? ""} onChange={set("risk")} inputMode="decimal" /></Field>
            <Field label="Max exposure (% equity)"><input value={f.exposure ?? ""} onChange={set("exposure")} inputMode="decimal" /></Field>
            <Field label="Max drawdown halt (%)"><input value={f.drawdown ?? ""} onChange={set("drawdown")} inputMode="decimal" /></Field>
          </div>
          <p className="dim" style={{ marginTop: 8 }}>
            The drawdown breaker auto-halts new entries when realized drawdown is breached. Exits are never blocked.
          </p>
        </Card>

        <Card title="Position & Execution" subtitle="editable · applied live + persisted">
          <div className="form-grid-2">
            <Field label="Max open positions"><input value={f.maxpos ?? ""} onChange={set("maxpos")} inputMode="numeric" /></Field>
            <Field label="Duplicate window (s)" hint="reject repeat alert_id within this window"><input value={f.dedup ?? ""} onChange={set("dedup")} inputMode="numeric" /></Field>
          </div>
        </Card>
      </div>

      <div className="grid-2-eq">
        <Card title="Daily Loss Limit" subtitle="editable · auto-resets each UTC day">
          <div className="form-grid-2">
            <Field label="Max daily loss (%)" hint="0 = disabled; halts new entries for the day"><input value={f.daily ?? ""} onChange={set("daily")} inputMode="decimal" /></Field>
          </div>
          <p className="dim" style={{ marginTop: 8 }}>When today's realized loss exceeds this, new entries are blocked until the next UTC day. Open positions still exit.</p>
        </Card>

        <Card title="Trading Session (UTC)" subtitle="editable · entries only inside the window">
          <div className="form-grid-2">
            <Field label="Session start (hour)"><input value={f.sstart ?? ""} onChange={set("sstart")} inputMode="numeric" /></Field>
            <Field label="Session end (hour)"><input value={f.send ?? ""} onChange={set("send")} inputMode="numeric" /></Field>
          </div>
          <p className="dim" style={{ marginTop: 8 }}>0 to 24 = trade all day. Entries outside the window are skipped; exits are never blocked.</p>
        </Card>
      </div>

      <div className="grid-2-eq">
        <Card title="Engine Configuration" subtitle="env-configured · read-only">
          {ro ? (
            <div className="risk-list">
              <Ro k="Mode" v={`${ro.mode} (simulation)`} badge={<Badge text="PAPER" tone="blue" />} />
              <Ro k="Strategy" v={`${ro.strategy} (${ro.strategy_key})`} />
              <Ro k="Timeframe" v={ro.timeframe} />
              <Ro k="Symbols" v={ro.symbols.join(", ")} />
              <Ro k="Starting balance" v={`$${ro.starting_cash.toLocaleString()}`} />
            </div>
          ) : <div className="dim">Loading…</div>}
          <p className="dim" style={{ marginTop: 8 }}>
            Set via env: HUB_AUTO_STRATEGY, HUB_AUTO_SYMBOLS, HUB_AUTO_TIMEFRAME (restart to change).
          </p>
        </Card>

        <Card title="Data & Connections" subtitle="read-only">
          {ro ? (
            <div className="risk-list">
              <Ro k="Market data" v={ro.data_source} />
              {ro.poll_seconds != null && <Ro k="Poll interval" v={`${ro.poll_seconds}s`} />}
              <Ro k="Broker" v={ro.broker_connected ? "connected" : "not connected"} badge={<Badge text={ro.broker_connected ? "LIVE" : "NONE"} tone={ro.broker_connected ? "green" : "default"} />} />
              <Ro k="Webhook secret" v={ro.webhook_secret_set ? "configured" : "not set"} />
              <Ro k="Telegram alerts" v={ro.telegram_configured ? "configured" : "not configured"} />
            </div>
          ) : <div className="dim">Loading…</div>}
          <p className="dim" style={{ marginTop: 8 }}>
            Live data: HUB_USE_LIVE_DATA=1 (ccxt). Notifications: TELEGRAM_BOT_TOKEN.
          </p>
        </Card>
      </div>
    </>
  );
}

function Ro({ k, v, badge }: { k: string; v: string; badge?: ReactNode }) {
  return (
    <div className="risk-item"><div className="risk-head">
      <span className="dim">{k}</span>
      <b style={{ display: "flex", alignItems: "center", gap: 6 }}>{v}{badge}</b>
    </div></div>
  );
}
