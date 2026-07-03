import { useEffect, useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { useApp } from "../../app-context";
import { apiGet, apiPost, apiPostJson,
  type ControlOptions, type ControlTuning, type ControlSimResult, type ControlCompare,
  type ControlAutoTune } from "../../lib/api";

type Cfg = { strategy: string; symbol: string; timeframe: string; mode: string;
  macro: string; confirm: string; entry: string; tuning: ControlTuning };

const DEFAULT_TUNING: ControlTuning = {
  min_score: 60, rr: 2.0, trend_filter: true, volume_filter: false,
  regime_filter: true, session_filter: false, max_trades_per_day: 0, cooldown_after_loss: 0,
  max_consecutive_losses: 0,
};

/** Real bot control center: switch strategy/symbol/timeframe/mode + tune the
 *  brain, then rerun a REAL simulation and compare. Calls back with the result. */
export default function ControlBar({ onResult }: { onResult: (r: ControlSimResult) => void }) {
  const app = useApp();
  const [opt, setOpt] = useState<ControlOptions | null>(null);
  const [cfg, setCfg] = useState<Cfg>({
    strategy: "Decision Brain", symbol: "BTCUSDT", timeframe: "4h", mode: "Simulation",
    macro: "4h", confirm: "15m", entry: "5m", tuning: DEFAULT_TUNING,
  });
  const [showTune, setShowTune] = useState(false);
  const [busy, setBusy] = useState(false);
  const [realistic, setRealistic] = useState(false);
  const [last, setLast] = useState<ControlSimResult | null>(null);
  const [cmp, setCmp] = useState<ControlCompare | null>(null);
  const [tune, setTune2] = useState<ControlAutoTune | null>(null);
  const [cmpStrat, setCmpStrat] = useState("Supply/Demand");
  const [cmpTf, setCmpTf] = useState("15m");
  const [loadingData, setLoadingData] = useState(false);
  const [loadProgress, setLoadProgress] = useState("");

  useEffect(() => {
    apiGet<ControlOptions>("/control/options").then((o) => {
      setOpt(o); setCfg((c) => ({ ...c, tuning: o.default_tuning }));
    }).catch(() => {});
  }, []);

  const body = () => ({ strategy: cfg.strategy, symbol: cfg.symbol, timeframe: cfg.entry,
    tuning: cfg.tuning, bars: 4000, macro: cfg.macro, confirmation: cfg.confirm, realistic });

  const apply = async () => {
    setBusy(true); setCmp(null);
    try {
      const r = await apiPostJson<ControlSimResult>("/control/simulate", body());
      setLast(r); onResult(r);
      if (!r.available) app.toast(r.error || "Historical data not available", "error");
      else if (r.warning) app.toast("Strategy warning — see the banner", "info");
      else app.toast("Simulation updated", "success");
    } catch { app.toast("Simulation failed — backend reachable?", "error"); }
    finally { setBusy(false); }
  };

  // one-click fix for "Historical data not available": kick the background
  // backfill (real Binance candles, every sim timeframe), show progress, and
  // rerun the simulation automatically when the data lands.
  const loadData = async () => {
    setLoadingData(true); setLoadProgress("starting…");
    try {
      await apiPost("/data/backfill?candles=6000&timeframes=5m,15m,30m,1h,4h,1d");
      const poll = window.setInterval(async () => {
        try {
          const st = await apiGet<any>("/data/backfill/status");
          setLoadProgress(`${st.done}/${st.total}${st.current ? ` — ${st.current}` : ""}`
            + (st.current_candles ? ` (${st.current_candles})` : ""));
          if (!st.running) {
            window.clearInterval(poll);
            setLoadingData(false);
            if (st.failed > 0 && st.succeeded === 0) {
              app.toast("Data load failed — is the exchange reachable from the server?", "error");
            } else {
              app.toast(`Real data loaded (${st.succeeded} series) — rerunning simulation`, "success");
              apply();
            }
          }
        } catch { /* keep polling */ }
      }, 3000);
    } catch {
      setLoadingData(false);
      app.toast("Could not start the data load — backend reachable?", "error");
    }
  };

  const compare = async () => {
    setBusy(true);
    try {
      const r = await apiPostJson<ControlCompare>("/control/compare", {
        a: { strategy: cfg.strategy, symbol: cfg.symbol, timeframe: cfg.entry, tuning: cfg.tuning,
             macro: cfg.macro, confirmation: cfg.confirm },
        b: { strategy: cmpStrat, symbol: cfg.symbol, timeframe: cmpTf, tuning: cfg.tuning,
             macro: cfg.macro, confirmation: cfg.confirm }, bars: 4000,
      });
      setCmp(r);
      if (r.error) app.toast(r.error, "error");
    } catch { app.toast("Compare failed", "error"); }
    finally { setBusy(false); }
  };

  const autoTune = async () => {
    setBusy(true); setTune2(null);
    try {
      const r = await apiPostJson<ControlAutoTune>("/control/auto-tune", body());
      if (!r.available) { app.toast(r.error || "Historical data not available", "error"); return; }
      setTune2(r);
      if (r.verdict === "improvement") {
        setTune({ ...cfg.tuning, min_score: r.best_tuning.min_score, rr: r.best_tuning.rr });
        app.toast(`Auto-tune: improvement — applied min score ${r.best_tuning.min_score}, RR ${r.best_tuning.rr}. Click Apply to run it.`, "success");
      } else {
        app.toast(`Auto-tune: ${r.verdict.replace("_", " ")} — kept current settings`, "info");
      }
    } catch { app.toast("Auto-tune failed", "error"); }
    finally { setBusy(false); }
  };

  const saveVersion = async () => {
    try {
      const v = await apiPostJson<any>("/control/save-version", body());
      if (v?.error || v?.detail) app.toast(v.error || v.detail, "error");
      else app.toast(`Saved ${v.label}`, "success");
    } catch { app.toast("Save needs the webhook secret", "error"); }
  };

  const set = (p: Partial<Cfg>) => setCfg((c) => ({ ...c, ...p }));
  const setTune = (p: Partial<ControlTuning>) => setCfg((c) => ({ ...c, tuning: { ...c.tuning, ...p } }));
  const s = last?.results;

  return (
    <Card title="Bot Control Center" subtitle="switch strategy / symbol / timeframe and rerun real simulation"
      right={<Badge text={cfg.mode} tone={cfg.mode.includes("Live") ? "red" : "purple"} />}>
      {/* row 1: selectors */}
      <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, flexWrap: "wrap" }}>
        <Select label="Mode" value={cfg.mode} opts={opt?.modes ?? ["Simulation"]} disabledVal="Live Trading (locked)"
          onChange={(v) => set({ mode: v })} />
        <Select label="Strategy" value={cfg.strategy} opts={opt?.strategies ?? [cfg.strategy]} onChange={(v) => set({ strategy: v })} />
        <Select label="Symbol" value={cfg.symbol} opts={opt?.symbols ?? [cfg.symbol]} onChange={(v) => set({ symbol: v })} />
        <Select label="Entry TF" value={cfg.entry} opts={opt?.timeframes ?? [cfg.entry]} onChange={(v) => set({ entry: v })} />
      </div>

      {/* row 2: multi-timeframe setup */}
      <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
        <span className="dim" style={{ fontSize: 12 }}>Multi-timeframe:</span>
        <Select label="Macro" value={cfg.macro} opts={opt?.timeframes ?? [cfg.macro]} onChange={(v) => set({ macro: v })} />
        <Select label="Confirmation" value={cfg.confirm} opts={opt?.timeframes ?? [cfg.confirm]} onChange={(v) => set({ confirm: v })} />
        <Select label="Trigger" value={cfg.entry} opts={opt?.timeframes ?? [cfg.entry]} onChange={(v) => set({ entry: v })} />
      </div>

      {/* row 3: actions */}
      <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        <button className="btn btn-primary" disabled={busy} onClick={apply}><Icon name="play" size={14} /> {busy ? "Running…" : "Apply & Simulate"}</button>
        <button className={`chip-btn ${realistic ? "active" : ""}`} onClick={() => setRealistic((x) => !x)}
          title="Charge spread + slippage + latency (same fill model as the paper engine)">Realistic fills</button>
        <button className="btn btn-soft" onClick={() => setShowTune((x) => !x)}><Icon name="settings" size={14} /> Brain Tuning</button>
        <button className="btn btn-soft" disabled={busy} onClick={autoTune} title="Search the brain-tuning space on real data (train/test split) and apply the best, validated config">
          <Icon name="bot" size={14} /> Auto-Tune
        </button>
        <button className="btn btn-soft" disabled={busy} onClick={compare}><Icon name="chart" size={14} /> Compare</button>
        <button className="btn btn-soft" onClick={saveVersion}><Icon name="layers" size={14} /> Save Version</button>
      </div>

      {tune && (
        <div className="card" style={{ marginTop: 10, borderColor: tune.verdict === "improvement" ? "#22c55e" : tune.verdict === "overfit" ? "#ef4444" : "#5b6478", background: "#131a2c" }}>
          <div className="row-actions" style={{ justifyContent: "space-between" }}>
            <b><Icon name="bot" size={14} /> Auto-Tune — best: min score {tune.best_tuning.min_score}, RR {tune.best_tuning.rr}</b>
            <Badge text={tune.verdict.replace("_", " ")} tone={tune.verdict === "improvement" ? "green" : tune.verdict === "overfit" ? "red" : "default"} />
          </div>
          <p className="dim" style={{ marginTop: 6 }}>{tune.note}</p>
          <div className="dim mono" style={{ fontSize: 12 }}>
            Out-of-sample net R: baseline {tune.baseline_test?.net_r} → tuned {tune.validation?.net_r}
            {" · "}PF {tune.validation?.profit_factor} · {tune.validation?.trades} trades
          </div>
        </div>
      )}

      {/* brain tuning panel */}
      {showTune && (
        <div className="card" style={{ marginTop: 10, background: "#131a2c" }}>
          <div className="form-grid-2">
            <Num label="Min trade score" value={cfg.tuning.min_score} min={0} max={95} step={5} onChange={(v) => setTune({ min_score: v })} />
            <Num label="Risk/Reward target" value={cfg.tuning.rr} min={1} max={5} step={0.1} onChange={(v) => setTune({ rr: v })} />
            <Num label="Max trades / day (0 = ∞)" value={cfg.tuning.max_trades_per_day} min={0} max={50} step={1} onChange={(v) => setTune({ max_trades_per_day: v })} />
            <Num label="Cooldown after loss (min)" value={cfg.tuning.cooldown_after_loss} min={0} max={240} step={5} onChange={(v) => setTune({ cooldown_after_loss: v })} />
            <Num label="Max consecutive losses (0 = ∞)" value={cfg.tuning.max_consecutive_losses} min={0} max={20} step={1} onChange={(v) => setTune({ max_consecutive_losses: v })} />
          </div>
          <div className="row-actions" style={{ justifyContent: "flex-start", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
            <Chk label="Trend filter" on={cfg.tuning.trend_filter} onChange={(v) => setTune({ trend_filter: v })} />
            <Chk label="Volume filter" on={cfg.tuning.volume_filter} onChange={(v) => setTune({ volume_filter: v })} />
            <Chk label="Market-regime filter" on={cfg.tuning.regime_filter} onChange={(v) => setTune({ regime_filter: v })} />
            <Chk label="Session filter" on={cfg.tuning.session_filter} onChange={(v) => setTune({ session_filter: v })} />
          </div>
        </div>
      )}

      {/* strategy health + warning */}
      {last && !last.available && (
        <div className="card" style={{ marginTop: 10, borderColor: "#ef4444" }}>
          <Icon name="warning" size={14} className="neg" /> {last.error}
          {String(last.error ?? "").toLowerCase().includes("data") && (
            <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, marginTop: 8 }}>
              <button className="btn btn-primary" disabled={loadingData} onClick={loadData}>
                <Icon name="play" size={13} /> {loadingData ? `Loading real data… ${loadProgress}` : "Load real Binance data now"}
              </button>
              {!loadingData && <span className="dim" style={{ fontSize: 12 }}>
                fetches 6,000 real candles per symbol × timeframe — enough for every simulation (background, a few minutes)
              </span>}
            </div>
          )}
        </div>
      )}
      {last?.available && (
        <p className="dim" style={{ marginTop: 8, fontSize: 12 }}>
          <Icon name="layers" size={12} /> Source: {last.data_source} ·
          MTF gate: {(last.mtf_gate?.length ? last.mtf_gate.join(" + ") : "none")} ·
          {" "}{cfg.macro} macro / {cfg.confirm} confirmation / {cfg.entry} entry
        </p>
      )}
      {s && (
        <div className="perf-grid" style={{ marginTop: 12 }}>
          {[
            ["Win Rate", `${s.win_rate}%`, ""],
            ["Profit Factor", (s.profit_factor ?? 0).toFixed(2), (s.profit_factor ?? 0) >= 1 ? "pos" : "neg"],
            ["Net", `${(s.net_r ?? 0) >= 0 ? "+" : ""}${s.net_r}R`, (s.net_r ?? 0) >= 0 ? "pos" : "neg"],
            ["Max Drawdown", `${s.max_drawdown_pct}%`, ""],
            ["Total Trades", String(s.total_trades), ""],
            ["Expectancy", `${s.expectancy_r ?? 0}R`, (s.expectancy_r ?? 0) >= 0 ? "pos" : "neg"],
          ].map(([l, v, t]) => (
            <div className="perf-item" key={l}><span className="perf-label">{l}</span><div className="perf-value-row"><span className={`perf-value ${t}`}>{v}</span></div></div>
          ))}
        </div>
      )}
      {last?.warning && (
        <div className="card" style={{ marginTop: 10, borderColor: "#f59e0b", background: "#f59e0b14" }}>
          <Icon name="warning" size={14} className="amber" /> <b className="amber">Strategy warning:</b> {last.warning.message}
        </div>
      )}

      {/* compare panel */}
      <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <span className="dim" style={{ fontSize: 12 }}>Compare vs:</span>
        <Select label="Strategy" value={cmpStrat} opts={opt?.strategies ?? [cmpStrat]} onChange={setCmpStrat} />
        <Select label="TF" value={cmpTf} opts={opt?.timeframes ?? [cmpTf]} onChange={setCmpTf} />
      </div>
      {cmp && !cmp.error && (
        <div className="tablewrap" style={{ marginTop: 8 }}>
          <table className="data-table">
            <thead><tr><th>Config</th><th>Trades</th><th>Win%</th><th>PF</th><th>Net R</th><th>Max DD</th><th></th></tr></thead>
            <tbody>
              {[["A", cmp.a], ["B", cmp.b]].map(([k, r]: any) => (
                <tr key={k}>
                  <td><b>{r.strategy}</b> · {r.timeframe}</td>
                  <td>{r.results?.total_trades ?? 0}</td><td className="dim">{r.results?.win_rate ?? 0}%</td>
                  <td className={(r.results?.profit_factor ?? 0) >= 1 ? "pos" : "neg"}>{(r.results?.profit_factor ?? 0).toFixed(2)}</td>
                  <td className={(r.results?.net_r ?? 0) >= 0 ? "pos" : "neg"}>{r.results?.net_r ?? 0}R</td>
                  <td className="dim">{r.results?.max_drawdown_pct ?? 0}%</td>
                  <td>{cmp.winner === k && <Badge text="winner" tone="green" />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Select({ label, value, opts, onChange, disabledVal }: {
  label: string; value: string; opts: string[]; onChange: (v: string) => void; disabledVal?: string;
}) {
  return (
    <label className="row-actions" style={{ gap: 4 }}>
      <span className="dim" style={{ fontSize: 11 }}>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {opts.map((o) => <option key={o} value={o} disabled={o === disabledVal}>{o}</option>)}
      </select>
    </label>
  );
}

function Num({ label, value, min, max, step, onChange }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <input type="number" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function Chk({ label, on, onChange }: { label: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="row-actions" style={{ gap: 6, cursor: "pointer" }}>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} />
      <span style={{ fontSize: 13 }}>{label}</span>
    </label>
  );
}
