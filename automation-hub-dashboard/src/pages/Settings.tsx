import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, Field, PageHeader } from "../components/common/ui";
import { useApp } from "../app-context";
import { API_BASE, apiPost, apiPostJson, useLive, type BotSettings, type EngineStatus, type NotifStatus } from "../lib/api";

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SESSIONS: Record<string, [number, number]> = { London: [7, 16], "New York": [12, 21], Asia: [0, 9], "24h": [0, 24] };

// Real configuration. Risk/position params are editable, applied live, and
// persisted on the backend (survive restart). Everything else is env-set and
// shown read-only with real values — no fake fields.
export default function SettingsPage() {
  const app = useApp();
  const { data, error, refetch } = useLive<BotSettings>("/settings", 8000);
  const engine = useLive<EngineStatus>("/engine/status", 5000);
  const [f, setF] = useState<Record<string, string>>({});
  const [days, setDays] = useState<boolean[]>([]);
  const [symbols, setSymbols] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data && days.length === 0) {
      const m = data.editable.trading_days_mask;
      setDays(Array.from({ length: 7 }, (_, i) => !!((m >> i) & 1)));
    }
  }, [data, days]);
  useEffect(() => { if (engine.data && symbols === "") setSymbols(engine.data.symbols.join(", ")); }, [engine.data, symbols]);

  const applySymbols = async () => {
    const list = symbols.split(",").map((s) => s.trim()).filter(Boolean);
    try { await apiPostJson("/market/symbols", { symbols: list }); app.toast(`Watchlist applied: ${list.join(", ")}`, "success"); }
    catch { app.toast("Apply failed", "error"); }
  };
  const preset = (name: string) => { const [s, e] = SESSIONS[name]; setF((p) => ({ ...p, sstart: String(s), send: String(e) })); };

  const notif = useLive<NotifStatus>("/notifications/status", 6000);
  const toggleNotif = async (key: "notify_trades" | "notify_risk") => {
    const cur = notif.data; if (!cur) return;
    try { await apiPostJson("/notifications", { [key]: !cur[key] }); notif.refetch(); }
    catch { app.toast("Update failed", "error"); }
  };
  const testNotif = async () => {
    try { const r = await apiPost<{ sent: boolean; configured: boolean }>("/notifications/test"); app.toast(r.sent ? "Telegram test sent ✅" : (r.configured ? "Send failed (network?)" : "Telegram not configured"), r.sent ? "success" : "error"); }
    catch { app.toast("Test failed", "error"); }
  };

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
        weekly: (data.editable.max_weekly_loss_pct * 100).toString(),
        maxday: String(data.editable.max_trades_per_day),
        consec: String(data.editable.max_consecutive_losses),
        cooldown: String(data.editable.cooldown_after_loss_min),
        entrymode: data.editable.entry_mode ?? "limit",
        reporthour: String(data.editable.daily_report_hour ?? 8),
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
        max_weekly_loss_pct: Number(f.weekly) / 100,
        max_trades_per_day: Math.round(Number(f.maxday)),
        max_consecutive_losses: Math.round(Number(f.consec)),
        cooldown_after_loss_min: Math.round(Number(f.cooldown)),
        trading_days_mask: days.reduce((acc, on, i) => (on ? acc | (1 << i) : acc), 0),
        entry_mode: f.entrymode === "market" ? "market" : "limit",
        daily_report_hour: Math.round(Number(f.reporthour)),
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

      <AccountCard />

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
            <Field label="Entry mode" hint="limit = maker entries (measured better); market = immediate">
              <select value={f.entrymode ?? "limit"} onChange={(e) => setF((prev) => ({ ...prev, entrymode: e.target.value }))}>
                <option value="limit">limit (maker)</option>
                <option value="market">market (taker)</option>
              </select>
            </Field>
            <Field label="Daily report hour (UTC)" hint="-1 disables the Telegram morning report">
              <input value={f.reporthour ?? ""} onChange={set("reporthour")} inputMode="numeric" />
            </Field>
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
          <div className="row-actions" style={{ justifyContent: "flex-start", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
            {Object.keys(SESSIONS).map((s) => <button key={s} className="chip-btn" onClick={() => preset(s)}>{s}</button>)}
          </div>
          <div className="form-grid-2">
            <Field label="Session start (hour)"><input value={f.sstart ?? ""} onChange={set("sstart")} inputMode="numeric" /></Field>
            <Field label="Session end (hour)"><input value={f.send ?? ""} onChange={set("send")} inputMode="numeric" /></Field>
          </div>
          <p className="dim" style={{ marginTop: 8 }}>Presets are UTC; 0 to 24 = all day. Entries outside the window are skipped; exits are never blocked.</p>
        </Card>
      </div>

      <div className="grid-2-eq">
        <Card title="Market — Watchlist (Symbols)" subtitle="editable · restarts the engine">
          <Field label="Traded symbols (comma-separated)"><input value={symbols} onChange={(e) => setSymbols(e.target.value.toUpperCase())} /></Field>
          <button className="btn btn-soft" style={{ marginTop: 8 }} onClick={applySymbols}><Icon name="check" size={14} /> Apply watchlist</button>
          <p className="dim" style={{ marginTop: 8 }}>Sets which symbols the engine trades (paper). Restart-to-persist via HUB_AUTO_SYMBOLS.</p>
        </Card>

        <Card title="Allowed Trading Days (UTC)" subtitle="editable · entries only on enabled days">
          <div className="row-actions" style={{ justifyContent: "flex-start", gap: 6, flexWrap: "wrap" }}>
            {DAY_NAMES.map((d, i) => (
              <button key={d} className={`chip-btn ${days[i] ? "active" : ""}`} onClick={() => setDays((p) => p.map((v, j) => (j === i ? !v : v)))}>{d}</button>
            ))}
          </div>
          <p className="dim" style={{ marginTop: 8 }}>Click to toggle. Disabled days block new entries (exits still run). Saved with the risk settings.</p>
        </Card>
      </div>

      <div className="grid-2-eq">
        <Card title="Loss Limits & Circuit Breakers" subtitle="editable · 0 = disabled">
          <div className="form-grid-2">
            <Field label="Weekly loss limit (%)" hint="resets each ISO week"><input value={f.weekly ?? ""} onChange={set("weekly")} inputMode="decimal" /></Field>
            <Field label="Max trades / day"><input value={f.maxday ?? ""} onChange={set("maxday")} inputMode="numeric" /></Field>
            <Field label="Stop after N consecutive losses" hint="auto-halts until Resume"><input value={f.consec ?? ""} onChange={set("consec")} inputMode="numeric" /></Field>
            <Field label="Cooldown after loss (min)"><input value={f.cooldown ?? ""} onChange={set("cooldown")} inputMode="numeric" /></Field>
          </div>
          <p className="dim" style={{ marginTop: 8 }}>These block NEW entries only; open positions always exit. Consecutive-loss halt requires a manual Resume.</p>
        </Card>

        <Card title="Account Protection — Progression" subtitle="enforced order">
          <div className="risk-list">
            <Ro k="1. Backtest" v="any strategy (historical, isolated)" />
            <Ro k="2. Simulation" v="real historical data · labelled SIMULATION" />
            <Ro k="3. Paper trading" v="live engine · paper only" badge={<Badge text="ACTIVE" tone="blue" />} />
            <Ro k="4. Live trading" v="requires a live broker (not connected)" badge={<Badge text="LOCKED" tone="red" />} />
          </div>
          <p className="dim" style={{ marginTop: 8 }}>A new strategy can never trade live directly. Live execution is disabled until a broker is wired.</p>
        </Card>
      </div>

      <div className="grid-2-eq">
        <Card title="Notifications" subtitle="Telegram · editable" right={<button className="btn btn-soft" onClick={testNotif}><Icon name="external" size={14} /> Send test</button>}>
          <div className="risk-list">
            <Ro k="Telegram" v={notif.data?.telegram_configured ? "configured" : "not configured"} badge={<Badge text={notif.data?.telegram_configured ? "ON" : "OFF"} tone={notif.data?.telegram_configured ? "green" : "default"} />} />
            <Ro k="Email" v={notif.data?.email ?? "—"} />
            <Ro k="Discord" v={notif.data?.discord ?? "—"} />
          </div>
          <div className="row-actions" style={{ justifyContent: "flex-start", gap: 6, marginTop: 10 }}>
            <button className={`chip-btn ${notif.data?.notify_trades ? "active" : ""}`} onClick={() => toggleNotif("notify_trades")}>Trade alerts</button>
            <button className={`chip-btn ${notif.data?.notify_risk ? "active" : ""}`} onClick={() => toggleNotif("notify_risk")}>Risk alerts</button>
          </div>
          <p className="dim" style={{ marginTop: 8 }}>Telegram needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (env). In-app alerts are always on (Alert Center). Email/Discord need extra credentials.</p>
        </Card>

        <Card title="Audit & Logs" subtitle="export the full trail">
          <p className="dim">Every settings change, strategy edit, deploy and engine event is recorded to the decision log.</p>
          <div className="row-actions" style={{ justifyContent: "flex-start", gap: 6, marginTop: 10 }}>
            <a className="btn btn-soft" href={`${API_BASE}/ledger/logs/export?fmt=csv`} target="_blank" rel="noreferrer"><Icon name="external" size={14} /> Logs CSV</a>
            <a className="btn btn-soft" href={`${API_BASE}/paper/trades/export?fmt=csv`} target="_blank" rel="noreferrer"><Icon name="external" size={14} /> Trades CSV</a>
          </div>
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

function AccountCard() {
  const app = useApp();
  const auth = useLive<{ authenticated: boolean; user: string | null; signup_open: boolean }>("/auth/status", 30000);
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);

  const logout = async () => {
    try { await fetch(`${API_BASE}/auth/logout`, { method: "POST" }); } catch { /* ignore */ }
    window.location.href = "/login";
  };
  const changePw = async () => {
    if (pw.next.length < 8) { app.toast("New password must be 8+ characters", "error"); return; }
    if (pw.next !== pw.confirm) { app.toast("Passwords do not match", "error"); return; }
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/auth/change-password`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current: pw.current, new: pw.next }),
      });
      const body = await res.json();
      if (!res.ok || body.error) app.toast(body.error ?? "Change failed", "error");
      else { app.toast("Password changed ✅", "success"); setPw({ current: "", next: "", confirm: "" }); }
    } catch { app.toast("Change failed — backend unreachable?", "error"); }
    finally { setBusy(false); }
  };

  return (
    <Card title="Tradexa Account" subtitle="who is signed in · change password · sign out"
      right={<button className="btn btn-danger" onClick={logout}><Icon name="close" size={13} /> Log out</button>}>
      <div className="risk-list" style={{ marginBottom: 10 }}>
        <div className="risk-item"><span className="dim">Signed in as</span>
          <b>{auth.data?.user ?? (auth.data?.authenticated === false ? "not signed in" : "…")}</b></div>
        <div className="risk-item"><span className="dim">Sessions</span>
          <span className="dim" style={{ fontSize: 12 }}>signed cookies · valid 7 days · survive restarts</span></div>
      </div>
      <div className="form-grid-2">
        <Field label="Current password"><input type="password" value={pw.current}
          onChange={(e) => setPw((s) => ({ ...s, current: e.target.value }))} /></Field>
        <Field label="New password (8+)"><input type="password" value={pw.next}
          onChange={(e) => setPw((s) => ({ ...s, next: e.target.value }))} /></Field>
        <Field label="Confirm new password"><input type="password" value={pw.confirm}
          onChange={(e) => setPw((s) => ({ ...s, confirm: e.target.value }))} /></Field>
      </div>
      <div className="row-actions" style={{ justifyContent: "flex-start", marginTop: 8 }}>
        <button className="btn btn-soft" disabled={busy} onClick={changePw}>
          {busy ? "Changing…" : "Change password"}</button>
      </div>
    </Card>
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
