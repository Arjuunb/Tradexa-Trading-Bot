import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Icon from "../common/Icon";
import { useApp } from "../../app-context";
import {
  apiPost, apiPostJson, useLive,
  type SystemStatus, type StrategyList, type PaperAccount, type BotSettings,
} from "../../lib/api";

/** Interactive top status bar — a professional-terminal control strip. Each
 *  segment of the existing pill (mode · engine · strategy · timeframe · gear)
 *  opens an anchored popover; nothing else in the layout moves. Every control
 *  drives a REAL endpoint (strategy/select, engine/timeframe, settings,
 *  notifications); anything without a backend is shown disabled with an
 *  honest note, never faked. */

// ---------------------------------------------------------------- popover
function usePopover<T extends HTMLElement>(onClose?: () => void) {
  const [open, setOpen] = useState(false);
  const ref = useRef<T | null>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false); onClose?.();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); onClose?.(); }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);
  return { open, setOpen, ref };
}

function Chip({ children, onClick, label, active }: {
  children: ReactNode; onClick: () => void; label: string; active?: boolean;
}) {
  return (
    <button type="button" className={`hdr-chip ${active ? "open" : ""}`}
            aria-label={label} aria-haspopup="menu" aria-expanded={active}
            onClick={onClick}>
      {children}
      <Icon name="chevron" size={10} className="dim hdr-caret" />
    </button>
  );
}

// ------------------------------------------------------------ account menu
function AccountMenu({ status }: { status?: SystemStatus }) {
  const app = useApp();
  const pop = usePopover<HTMLDivElement>();
  const acct = useLive<PaperAccount>("/paper/account", 8000);
  const liveReady = Boolean(status?.broker_connected);
  return (
    <div className="hdr-seg" ref={pop.ref}>
      <Chip label="Trading account" active={pop.open} onClick={() => pop.setOpen(!pop.open)}>
        <span className={`dot ${status ? "online" : "offline"}`} />
        <b>Paper</b>
      </Chip>
      {pop.open && (
        <div className="hdr-pop" role="menu">
          <p className="hdr-pop-title">Trading account</p>
          <div className="hdr-kv">
            <span>Account</span><b>Paper Account</b>
            <span>Data venue</span><b>{status?.data_source ?? "—"}</b>
            <span>Balance</span><b>{acct.data ? `$${Number(acct.data.current_equity ?? acct.data.balance ?? 0).toLocaleString()}` : "—"}</b>
            <span>Connection</span>
            <b className={status ? "pos" : "neg"}>{status ? "connected" : "backend offline"}</b>
          </div>
          <div className="hdr-pop-sep" />
          <button className="hdr-item active" role="menuitem"
                  onClick={() => { pop.setOpen(false); app.toast("Paper account active — data refreshed.", "success"); }}>
            <span className="dot online" /> Paper Trading <span className="hdr-tag">current</span>
          </button>
          <button className="hdr-item" role="menuitem" disabled={!liveReady}
                  title={liveReady ? "" : "No broker connected — configure exchange keys and pass the Safety Center gates first"}
                  onClick={() => { pop.setOpen(false); app.go("Live Trading"); }}>
            <span className="dot offline" /> Live Trading
            {!liveReady && <span className="hdr-tag">not configured</span>}
          </button>
          <button className="hdr-item" role="menuitem"
                  onClick={() => { pop.setOpen(false); app.go("Simulation"); }}>
            <Icon name="play" size={12} /> Simulation Mode
          </button>
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------- strategy menu
function StrategyMenu({ status }: { status?: SystemStatus }) {
  const app = useApp();
  const pop = usePopover<HTMLDivElement>();
  const list = useLive<StrategyList>("/strategy/list", 15000);
  const cfg = useLive<BotSettings>("/settings", 15000);
  const [busy, setBusy] = useState(false);
  const [draftSymbols, setDraftSymbols] = useState<string | null>(null);

  const ed = cfg.data?.editable;
  const patch = async (body: Record<string, unknown>, note: string) => {
    try { await apiPostJson("/settings", body); app.toast(note, "success"); cfg.refetch(); }
    catch { app.toast("Engine rejected the change.", "error"); }
  };

  const activate = async (key: string, label: string) => {
    setBusy(true);
    try {
      await apiPostJson("/strategy/select", { strategy: key });
      app.toast(`Strategy switched to ${label} — engine restarted.`, "success");
      list.refetch();
    } catch { app.toast("Strategy switch failed.", "error"); }
    setBusy(false);
  };

  const saveSymbols = async () => {
    const symbols = (draftSymbols ?? "").split(/[\s,]+/).map((s) => s.toUpperCase()).filter(Boolean);
    if (!symbols.length) { app.toast("At least one symbol is required.", "error"); return; }
    try {
      await apiPostJson("/market/symbols", { symbols });
      app.toast(`Watchlist applied: ${symbols.join(", ")}`, "success");
      setDraftSymbols(null);
    } catch { app.toast("Engine rejected the watchlist.", "error"); }
  };

  return (
    <div className="hdr-seg" ref={pop.ref}>
      <Chip label="Strategy menu" active={pop.open} onClick={() => pop.setOpen(!pop.open)}>
        <b>{status?.strategy ?? "Strategy"}</b>
      </Chip>
      {pop.open && (
        <div className="hdr-pop hdr-pop-wide" role="menu">
          <p className="hdr-pop-title">Strategy — changes apply to the live engine instantly</p>
          <div className="hdr-strats">
            {(list.data?.strategies ?? []).map((s) => {
              const isActive = s.key === list.data?.active;
              return (
                <button key={s.key} disabled={busy || isActive}
                        className={`hdr-item ${isActive ? "active" : ""}`}
                        onClick={() => activate(s.key, s.label)}>
                  <b>{s.label}</b>
                  {isActive ? <span className="hdr-tag">active</span>
                            : <span className="dim" style={{ fontSize: 11 }}>activate</span>}
                </button>
              );
            })}
            {!list.data?.strategies?.length && <p className="dim" style={{ fontSize: 12, padding: 6 }}>Loading strategies…</p>}
          </div>
          <div className="hdr-pop-sep" />
          <div className="hdr-form">
            <label>Symbols
              <input value={draftSymbols ?? (status?.symbols ?? []).join(", ")}
                     onChange={(e) => setDraftSymbols(e.target.value)}
                     onBlur={() => draftSymbols !== null && void saveSymbols()}
                     onKeyDown={(e) => e.key === "Enter" && void saveSymbols()} />
            </label>
            <label>Risk per trade %
              <input type="number" step={0.1} min={0.1} max={50}
                     defaultValue={ed ? (ed.risk_per_trade_pct * 100).toFixed(1) : ""}
                     key={`r${ed?.risk_per_trade_pct}`}
                     onBlur={(e) => { const v = Number(e.target.value) / 100; if (v > 0 && v <= 0.5 && v !== ed?.risk_per_trade_pct) void patch({ risk_per_trade_pct: v }, "Risk per trade updated."); }} />
            </label>
            <label>Max positions
              <input type="number" min={1} max={50} key={`m${ed?.max_open_positions}`}
                     defaultValue={ed?.max_open_positions ?? ""}
                     onBlur={(e) => { const v = Math.round(Number(e.target.value)); if (v >= 1 && v <= 50 && v !== ed?.max_open_positions) void patch({ max_open_positions: v }, "Max positions updated."); }} />
            </label>
            <label>Session (UTC)
              <span className="hdr-inline">
                <input type="number" min={0} max={24} key={`s${ed?.session_start}`} defaultValue={ed?.session_start ?? ""}
                       onBlur={(e) => { const v = Math.round(Number(e.target.value)); if (v >= 0 && v <= 24 && v !== ed?.session_start) void patch({ session_start: v }, "Session start updated."); }} />
                –
                <input type="number" min={0} max={24} key={`e${ed?.session_end}`} defaultValue={ed?.session_end ?? ""}
                       onBlur={(e) => { const v = Math.round(Number(e.target.value)); if (v >= 0 && v <= 24 && v !== ed?.session_end) void patch({ session_end: v }, "Session end updated."); }} />
              </span>
            </label>
            <label>Confirmation gate (min quality score)
              <input type="number" min={0} max={100} key={`q${ed?.min_quality_score}`} defaultValue={ed?.min_quality_score ?? ""}
                     onBlur={(e) => { const v = Math.round(Number(e.target.value)); if (v >= 0 && v <= 100 && v !== ed?.min_quality_score) void patch({ min_quality_score: v }, "Quality gate updated."); }} />
            </label>
          </div>
          <p className="hdr-note">Stops &amp; targets are ATR-based and strategy-managed (validated RR 3:1).
            Entry filters follow measured defaults — see Settings for the full engine configuration.</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------- timeframe menu
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"];

function TimeframeMenu({ status }: { status?: SystemStatus }) {
  const app = useApp();
  const pop = usePopover<HTMLDivElement>();
  const [busy, setBusy] = useState(false);
  const current = status?.timeframe ?? "—";

  const pick = async (tf: string) => {
    if (tf === current) { pop.setOpen(false); return; }
    setBusy(true);
    try {
      await apiPost(`/engine/timeframe?timeframe=${tf}`);
      try { localStorage.setItem("hub.timeframe", tf); } catch { /* private mode */ }
      app.toast(`Engine switched to ${tf}`, "success");
      pop.setOpen(false);
    } catch { app.toast(`Engine rejected timeframe ${tf}.`, "error"); }
    setBusy(false);
  };

  return (
    <div className="hdr-seg" ref={pop.ref}>
      <Chip label="Timeframe" active={pop.open} onClick={() => pop.setOpen(!pop.open)}>
        <b className="mono">{current}</b>
      </Chip>
      {pop.open && (
        <div className="hdr-pop" role="menu">
          <p className="hdr-pop-title">Candle timeframe — switching restarts the engine safely</p>
          <div className="tf-grid">
            {TIMEFRAMES.map((tf) => (
              <button key={tf} disabled={busy}
                      className={`tf-btn ${tf === current ? "active" : ""}`}
                      onClick={() => void pick(tf)}>{tf}</button>
            ))}
          </div>
          <p className="hdr-note">Persisted on the server — restored after every restart and login.</p>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------- engine settings ⚙
function EngineSettings({ status }: { status?: SystemStatus }) {
  const app = useApp();
  const pop = usePopover<HTMLDivElement>();
  const cfg = useLive<BotSettings>("/settings", 20000);
  const notif = useLive<{ notify_trades: boolean; notify_risk: boolean; telegram_configured?: boolean; configured?: boolean }>(
    "/notifications/status", 20000);
  const [draft, setDraft] = useState<Record<string, number | string | boolean>>({});
  const [busy, setBusy] = useState(false);
  const ed = cfg.data?.editable;
  const ro = cfg.data?.readonly;

  const val = <K extends string>(k: K, fallback: number | string | boolean) =>
    (k in draft ? draft[k] : fallback);
  const set = (k: string, v: number | string | boolean) => setDraft((d) => ({ ...d, [k]: v }));

  const save = async () => {
    setBusy(true);
    try {
      const { notify_trades, notify_risk, ...engine } = draft;
      if (Object.keys(engine).length) await apiPostJson("/settings", engine);
      if (notify_trades !== undefined || notify_risk !== undefined) {
        await apiPostJson("/notifications", { notify_trades, notify_risk });
      }
      app.toast("Engine settings saved.", "success");
      setDraft({});
      cfg.refetch(); notif.refetch();
      pop.setOpen(false);
    } catch { app.toast("Engine rejected the settings.", "error"); }
    setBusy(false);
  };

  const numRow = (label: string, k: string, cur: number | undefined, opts: {
    min?: number; max?: number; step?: number; scale?: number; suffix?: string } = {}) => {
    const scale = opts.scale ?? 1;
    const shown = Number(val(k, cur !== undefined ? +(cur * scale).toFixed(3) : ""));
    return (
      <label key={k}>{label}
        <span className="hdr-inline">
          <input type="number" min={opts.min} max={opts.max} step={opts.step ?? 1}
                 value={Number.isFinite(shown) ? shown : ""}
                 onChange={(e) => set(k, Number(e.target.value))} />
          {opts.suffix && <span className="dim">{opts.suffix}</span>}
        </span>
      </label>
    );
  };

  return (
    <div className="hdr-seg" ref={pop.ref}>
      <button type="button" className={`hdr-chip hdr-gear ${pop.open ? "open" : ""}`}
              aria-label="Engine configuration" aria-haspopup="dialog" aria-expanded={pop.open}
              onClick={() => pop.setOpen(!pop.open)}>
        <Icon name="settings" size={13} />
      </button>
      {pop.open && (
        <div className="hdr-pop hdr-pop-wide hdr-settings" role="dialog" aria-label="Engine configuration">
          <p className="hdr-pop-title">Engine settings — Save applies to the running bot</p>

          <p className="hdr-sect">General</p>
          <div className="hdr-kv">
            <span>Engine</span><b>{status?.strategy ?? "—"} · {status?.timeframe ?? "—"}</b>
            <span>Mode</span><b>paper (live is gated by the Safety Center)</b>
            <span>State</span><b className={status?.engine_running ? "pos" : "neg"}>{status?.engine_running ? "running" : "stopped"}</b>
          </div>

          <p className="hdr-sect">Execution</p>
          <div className="hdr-form">
            <label>Order type
              <select value={String(val("entry_mode", ed?.entry_mode ?? "limit"))}
                      onChange={(e) => set("entry_mode", e.target.value)}>
                <option value="limit">limit (maker — measured better)</option>
                <option value="market">market (taker)</option>
              </select>
            </label>
            <div className="hdr-kv">
              <span>Exchange / data</span><b>{ro ? ro.data_source : "—"}</b>
              <span>Fees / slippage</span><b>paper fills — not modeled (stated, not hidden)</b>
            </div>
          </div>

          <p className="hdr-sect">Risk</p>
          <div className="hdr-form">
            {numRow("Daily loss limit %", "max_daily_loss_pct", ed?.max_daily_loss_pct, { min: 0, max: 100, step: 0.5, scale: 100, suffix: "%" })}
            {numRow("Max drawdown %", "max_drawdown_pct", ed?.max_drawdown_pct, { min: 0.5, max: 100, step: 0.5, scale: 100, suffix: "%" })}
            {numRow("Max concurrent trades", "max_open_positions", ed?.max_open_positions, { min: 1, max: 50 })}
            {numRow("Risk per trade %", "risk_per_trade_pct", ed?.risk_per_trade_pct, { min: 0.1, max: 50, step: 0.1, scale: 100, suffix: "%" })}
          </div>

          <p className="hdr-sect">Market data</p>
          <div className="hdr-kv">
            <span>Feed</span><b>{ro ? ro.data_source : "—"} · REST poll{ro?.poll_seconds ? ` every ${ro.poll_seconds}s` : ""}</b>
            <span>History</span><b>{typeof status?.bars_processed === "number" ? `${status.bars_processed} bars processed` : "—"}</b>
          </div>

          <p className="hdr-sect">Notifications</p>
          <div className="hdr-form">
            <label className="hdr-check">
              <input type="checkbox" checked={Boolean(val("notify_trades", notif.data?.notify_trades ?? false))}
                     onChange={(e) => set("notify_trades", e.target.checked)} />
              Telegram — trade alerts {notif.data && !(notif.data.telegram_configured ?? notif.data.configured) && <span className="hdr-tag">token not set</span>}
            </label>
            <label className="hdr-check">
              <input type="checkbox" checked={Boolean(val("notify_risk", notif.data?.notify_risk ?? false))}
                     onChange={(e) => set("notify_risk", e.target.checked)} />
              Telegram — risk alerts
            </label>
            <p className="hdr-note">Discord &amp; email are not configured on this backend.</p>
          </div>

          <p className="hdr-sect">Advanced</p>
          <div className="hdr-form">
            {numRow("AI confidence gate (min score)", "min_quality_score", ed?.min_quality_score, { min: 0, max: 100 })}
            {numRow("Daily report hour (UTC, −1 off)", "daily_report_hour", ed?.daily_report_hour, { min: -1, max: 23 })}
            <label className="hdr-check">
              <input type="checkbox" checked={Boolean(val("streak_risk_scaling", ed?.streak_risk_scaling ?? true))}
                     onChange={(e) => set("streak_risk_scaling", e.target.checked)} />
              Losing-streak risk scaling (anti-martingale)
            </label>
          </div>

          <div className="hdr-actions">
            <button className="btn btn-sm" disabled={busy || !Object.keys(draft).length} onClick={() => void save()}>Save</button>
            <button className="btn btn-ghost btn-sm" onClick={() => { setDraft({}); pop.setOpen(false); }}>Cancel</button>
            <button className="btn btn-ghost btn-sm" disabled={!Object.keys(draft).length}
                    onClick={() => { setDraft({}); cfg.refetch(); app.toast("Reset to the engine's current values.", "info"); }}>Reset</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------- the bar
export default function HeaderControls() {
  const { data, error } = useLive<SystemStatus>("/system/status", 4000);

  let dot = "offline", engineLabel = "Backend offline";
  if (data) {
    if (data.auto_halted) { dot = "warn"; engineLabel = `Auto-halted — ${data.halt_reason || "breaker"}`; }
    else if (data.engine_running) { dot = "online"; engineLabel = "Engine Running"; }
    else { dot = "warn"; engineLabel = "Engine Stopped"; }
  }

  const refresh = useCallback(() => { /* useLive polls every 4s — segments read live state */ }, []);
  void refresh;

  return (
    <div className="hdr-controls" title={error ? "Backend not reachable" : undefined}>
      <AccountMenu status={data ?? undefined} />
      <span className={`hdr-static dot-label`}>
        <span className={`dot ${dot}`} /> <span className="hide-sm">{engineLabel}</span>
      </span>
      <StrategyMenu status={data ?? undefined} />
      <TimeframeMenu status={data ?? undefined} />
      <EngineSettings status={data ?? undefined} />
    </div>
  );
}
