import { useEffect, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Field, PageHeader } from "../components/common/ui";
import { useApp } from "../app-context";
import { apiPostJson, useLive, type BotSettings } from "../lib/api";

// Real configuration. Editable risk params persist on the backend (survive
// restart). Everything else is env-configured and shown read-only — no fakes.
export default function SettingsPage() {
  const app = useApp();
  const { data, error, refetch } = useLive<BotSettings>("/settings", 8000);
  const [risk, setRisk] = useState("");
  const [exposure, setExposure] = useState("");
  const [drawdown, setDrawdown] = useState("");
  const [saving, setSaving] = useState(false);

  // Seed the inputs once from the backend (as percentages).
  useEffect(() => {
    if (data && risk === "") {
      setRisk((data.editable.risk_per_trade_pct * 100).toString());
      setExposure((data.editable.exposure_limit_pct * 100).toString());
      setDrawdown((data.editable.max_drawdown_pct * 100).toString());
    }
  }, [data, risk]);

  const save = async () => {
    setSaving(true);
    try {
      await apiPostJson("/settings", {
        risk_per_trade_pct: Number(risk) / 100,
        exposure_limit_pct: Number(exposure) / 100,
        max_drawdown_pct: Number(drawdown) / 100,
      });
      app.toast("Settings saved (persisted on backend)", "success");
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
        actions={<button className="btn btn-primary" disabled={saving || !data} onClick={save}><Icon name="check" size={14} /> {saving ? "Saving…" : "Save Risk Settings"}</button>}
      />

      {error && !data && (
        <div className="card" style={{ borderColor: "#ef4444" }}>
          <Icon name="warning" size={15} className="neg" /> Backend not reachable — settings unavailable.
        </div>
      )}

      <div className="grid-2-eq">
        <Card title="Risk Settings" subtitle="editable · applied live + persisted">
          <div className="form-grid-2">
            <Field label="Risk per trade (%)"><input value={risk} onChange={(e) => setRisk(e.target.value)} inputMode="decimal" /></Field>
            <Field label="Exposure limit (% of equity)"><input value={exposure} onChange={(e) => setExposure(e.target.value)} inputMode="decimal" /></Field>
            <Field label="Max drawdown halt (%)"><input value={drawdown} onChange={(e) => setDrawdown(e.target.value)} inputMode="decimal" /></Field>
          </div>
          <p className="dim" style={{ marginTop: 8 }}>
            Changes apply immediately to the running engine and are saved to disk (survive restart).
            The drawdown limit auto-halts new entries when breached.
          </p>
        </Card>

        <Card title="Engine Configuration" subtitle="env-configured · read-only">
          {ro ? (
            <div className="risk-list">
              <Ro k="Mode" v={`${ro.mode} (simulation)`} />
              <Ro k="Strategy" v={`${ro.strategy} (${ro.strategy_key})`} />
              <Ro k="Timeframe" v={ro.timeframe} />
              <Ro k="Symbols" v={ro.symbols.join(", ")} />
              <Ro k="Data source" v={ro.data_source} />
              <Ro k="Broker" v={ro.broker_connected ? "connected" : "not connected"} />
              <Ro k="Starting balance" v={`$${ro.starting_cash.toLocaleString()}`} />
              <Ro k="Max open positions" v={String(ro.max_open_positions)} />
              <Ro k="Duplicate window" v={`${ro.dedup_window_s}s`} />
              <Ro k="Webhook secret" v={ro.webhook_secret_set ? "configured" : "not set"} />
            </div>
          ) : <div className="dim">Loading…</div>}
          <p className="dim" style={{ marginTop: 8 }}>
            Strategy, symbols, timeframe and live-data are set via environment variables
            (HUB_AUTO_STRATEGY, HUB_AUTO_SYMBOLS, HUB_AUTO_TIMEFRAME, HUB_USE_LIVE_DATA) and
            require an engine restart.
          </p>
        </Card>
      </div>
    </>
  );
}

function Ro({ k, v }: { k: string; v: string }) {
  return <div className="risk-item"><div className="risk-head"><span className="dim">{k}</span><b>{v}</b></div></div>;
}
