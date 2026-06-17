import { useEffect, useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import AreaLine from "../chart/AreaLine";
import { Badge, Field } from "../common/ui";
import { useApp } from "../../app-context";
import {
  apiDelete, apiPostJson, useLive, hhmmss,
  type CustomRule, type CustomSpec, type SimResult,
} from "../../lib/api";

type FieldDef = [string, "num" | "sel", number | string[]];
const RULE_DEFS: Record<string, { label: string; fields: FieldDef[] }> = {
  ema_cross: { label: "EMA cross", fields: [["fast", "num", 20], ["slow", "num", 50], ["dir", "sel", ["above", "below"]]] },
  rsi: { label: "RSI threshold", fields: [["period", "num", 14], ["op", "sel", ["above", "below"]], ["value", "num", 50]] },
  sma_trend: { label: "SMA trend filter", fields: [["period", "num", 200], ["dir", "sel", ["above", "below"]]] },
  macd: { label: "MACD cross", fields: [["fast", "num", 12], ["slow", "num", 26], ["signal", "num", 9], ["dir", "sel", ["above", "below"]]] },
  breakout: { label: "Breakout (price action)", fields: [["lookback", "num", 20], ["dir", "sel", ["up", "down"]]] },
  volume: { label: "Volume vs average", fields: [["period", "num", 20], ["op", "sel", ["above", "below"]]] },
  atr_filter: { label: "Volatility (ATR) filter", fields: [["period", "num", 14], ["op", "sel", ["below", "above"]], ["value_pct", "num", 4]] },
};

function newRule(type: string): CustomRule {
  const r: CustomRule = { type };
  for (const [k, , def] of RULE_DEFS[type].fields) r[k] = Array.isArray(def) ? def[0] : def;
  return r;
}

const DEFAULT: CustomSpec = {
  name: "My Strategy", market: "crypto", symbol: "BTCUSDT", timeframe: "4h", side: "long",
  entry: { op: "AND", rules: [newRule("ema_cross"), newRule("rsi"), newRule("breakout")] },
  stop: { type: "atr", mult: 1.5, period: 14 }, target: { type: "rr", rr: 1.5 },
  risk_per_trade_pct: 0.01, max_trades_per_day: 0,
};

// Live plain-English preview (mirrors the backend describe()).
function describe(s: CustomSpec): string {
  const phrase = (r: any) => {
    const m: Record<string, string> = {
      ema_cross: `EMA${r.fast} is ${r.dir} EMA${r.slow}`,
      rsi: `RSI(${r.period}) is ${r.op} ${r.value}`,
      sma_trend: `price is ${r.dir} the ${r.period} SMA`,
      macd: `MACD is ${r.dir} its signal`,
      breakout: `price breaks the ${r.lookback}-bar ${r.dir === "up" ? "high" : "low"}`,
      volume: `volume is ${r.op} its ${r.period}-bar average`,
      atr_filter: `volatility is ${r.op} ${r.value_pct}%`,
    };
    return r.negate ? `NOT (${m[r.type] ?? r.type})` : m[r.type] ?? r.type;
  };
  const conds = s.entry.rules.length ? s.entry.rules.map(phrase).join(` ${s.entry.op} `) : "no entry conditions set";
  const stop = s.stop.type === "atr" ? `a ${s.stop.mult}× ATR stop` : `a ${s.stop.pct}% stop`;
  const tgt = s.target.type === "rr" ? `a ${s.target.rr} risk:reward target` : `a ${s.target.pct}% target`;
  return `Enters ${s.side} when ${conds}. Exits using ${stop} and ${tgt}, risking ${(s.risk_per_trade_pct * 100).toFixed(1)}% per trade.`;
}

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function CustomBuilder() {
  const app = useApp();
  const [spec, setSpec] = useState<CustomSpec>(DEFAULT);
  const [sim, setSim] = useState<SimResult | null>(null);
  const [running, setRunning] = useState(false);
  const saved = useLive<CustomSpec[]>("/strategy/custom", 6000);

  useEffect(() => { setSim(null); }, [spec.entry, spec.symbol, spec.timeframe, spec.side, spec.stop, spec.target]);

  const patch = (p: Partial<CustomSpec>) => setSpec((s) => ({ ...s, ...p }));
  const setRule = (i: number, r: CustomRule) => setSpec((s) => ({ ...s, entry: { ...s.entry, rules: s.entry.rules.map((x, j) => (j === i ? r : x)) } }));
  const addRule = () => setSpec((s) => ({ ...s, entry: { ...s.entry, rules: [...s.entry.rules, newRule("ema_cross")] } }));
  const delRule = (i: number) => setSpec((s) => ({ ...s, entry: { ...s.entry, rules: s.entry.rules.filter((_, j) => j !== i) } }));

  const runSim = async () => {
    setRunning(true);
    try { setSim(await apiPostJson<SimResult>("/strategy/custom/simulate", { spec, bars: 3000 })); }
    catch { app.toast("Simulation failed — backend unreachable?", "error"); }
    finally { setRunning(false); }
  };
  const save = async () => {
    try { const r = await apiPostJson<CustomSpec>("/strategy/custom", spec); setSpec(r); saved.refetch(); app.toast("Strategy saved", "success"); }
    catch { app.toast("Save failed", "error"); }
  };
  const load = (s: CustomSpec) => { setSpec(s); setSim(null); app.toast(`Loaded "${s.name}"`, "info"); };
  const duplicate = async (id: string) => { try { await apiPostJson(`/strategy/custom/${id}/duplicate`, {}); saved.refetch(); app.toast("Duplicated", "success"); } catch { app.toast("Failed", "error"); } };
  const remove = async (id: string) => { try { await apiDelete(`/strategy/custom/${id}`); saved.refetch(); app.toast("Deleted", "info"); } catch { app.toast("Failed", "error"); } };

  const r = sim?.results;
  const curve = (r?.equity_curve ?? []).map((p) => p.equity);
  const wTone = (l: string) => (l === "danger" ? "neg" : l === "warning" ? "amber" : l === "ok" ? "pos" : "dim");

  return (
    <>
      {/* meta */}
      <Card title="Strategy">
        <div className="form-grid-2">
          <Field label="Name"><input value={spec.name} onChange={(e) => patch({ name: e.target.value })} /></Field>
          <Field label="Market"><select value={spec.market} onChange={(e) => patch({ market: e.target.value })}><option>crypto</option><option>forex</option><option>stocks</option></select></Field>
          <Field label="Symbol / pair"><input value={spec.symbol} onChange={(e) => patch({ symbol: e.target.value.toUpperCase() })} /></Field>
          <Field label="Timeframe"><select value={spec.timeframe} onChange={(e) => patch({ timeframe: e.target.value })}>{["5m", "15m", "1h", "4h", "1d"].map((t) => <option key={t}>{t}</option>)}</select></Field>
          <Field label="Direction"><select value={spec.side} onChange={(e) => patch({ side: e.target.value as "long" | "short" })}><option value="long">Long</option><option value="short">Short</option></select></Field>
        </div>
      </Card>

      {/* entry rules */}
      <Card title="Entry Conditions" right={
        <select value={spec.entry.op} onChange={(e) => patch({ entry: { ...spec.entry, op: e.target.value as "AND" | "OR" } })} style={{ width: 90 }}>
          <option value="AND">ALL (AND)</option><option value="OR">ANY (OR)</option>
        </select>}>
        <div className="rule-list">
          {spec.entry.rules.map((rule, i) => (
            <div className="rule-row" key={i}>
              <button className={`chip-btn sm ${rule.negate ? "active" : ""}`} title="NOT" onClick={() => setRule(i, { ...rule, negate: !rule.negate })}>NOT</button>
              <select value={rule.type} onChange={(e) => setRule(i, newRule(e.target.value))}>
                {Object.entries(RULE_DEFS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
              {RULE_DEFS[rule.type].fields.map(([k, kind, def]) => (
                kind === "sel"
                  ? <select key={k} value={String(rule[k])} onChange={(e) => setRule(i, { ...rule, [k]: e.target.value })}>{(def as string[]).map((o) => <option key={o}>{o}</option>)}</select>
                  : <input key={k} className="rule-num" type="number" value={Number(rule[k])} onChange={(e) => setRule(i, { ...rule, [k]: Number(e.target.value) })} title={k} />
              ))}
              <button className="icon-btn sm neg" title="Remove" onClick={() => delRule(i)}><Icon name="close" size={14} /></button>
            </div>
          ))}
        </div>
        <button className="btn btn-soft" style={{ marginTop: 8 }} onClick={addRule}><Icon name="plus" size={14} /> Add condition</button>
      </Card>

      {/* exit / risk */}
      <Card title="Exit & Risk">
        <div className="form-grid-2">
          <Field label="Stop loss">
            <div className="row-actions" style={{ gap: 6 }}>
              <select value={spec.stop.type} onChange={(e) => patch({ stop: { ...spec.stop, type: e.target.value as "atr" | "pct" } })}><option value="atr">ATR ×</option><option value="pct">% of price</option></select>
              <input className="rule-num" type="number" step="0.1" value={spec.stop.type === "atr" ? (spec.stop.mult ?? 1.5) : (spec.stop.pct ?? 2)} onChange={(e) => patch({ stop: { ...spec.stop, [spec.stop.type === "atr" ? "mult" : "pct"]: Number(e.target.value) } })} />
            </div>
          </Field>
          <Field label="Take profit">
            <div className="row-actions" style={{ gap: 6 }}>
              <select value={spec.target.type} onChange={(e) => patch({ target: { ...spec.target, type: e.target.value as "rr" | "pct" } })}><option value="rr">Risk:Reward</option><option value="pct">% of price</option></select>
              <input className="rule-num" type="number" step="0.1" value={spec.target.type === "rr" ? (spec.target.rr ?? 1.5) : (spec.target.pct ?? 3)} onChange={(e) => patch({ target: { ...spec.target, [spec.target.type === "rr" ? "rr" : "pct"]: Number(e.target.value) } })} />
            </div>
          </Field>
          <Field label="Risk per trade (%)"><input type="number" step="0.1" value={spec.risk_per_trade_pct * 100} onChange={(e) => patch({ risk_per_trade_pct: Number(e.target.value) / 100 })} /></Field>
          <Field label="Max trades / day (0 = no limit)"><input type="number" value={spec.max_trades_per_day ?? 0} onChange={(e) => patch({ max_trades_per_day: Number(e.target.value) })} /></Field>
        </div>
      </Card>

      {/* logic preview + actions */}
      <Card title="Strategy Logic Preview">
        <p style={{ lineHeight: 1.5 }}>{describe(spec)}</p>
        <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, marginTop: 10 }}>
          <button className="btn btn-primary" disabled={running} onClick={runSim}><Icon name="play" size={14} /> {running ? "Simulating…" : "Run Simulation"}</button>
          <button className="btn btn-soft" onClick={save}><Icon name="check" size={14} /> Save Strategy</button>
        </div>
        <p className="dim" style={{ marginTop: 10 }}>
          <Icon name="info" size={13} /> Safety: custom strategies run in <b>simulation</b> first, then <b>paper</b>. Direct live trading from a new strategy is not allowed.
        </p>
      </Card>

      {/* results */}
      {r && (
        <>
          <Card title="Simulation Result" subtitle={`${sim!.data_source} · ${sim!.symbol} ${sim!.timeframe} · ${r.span_days}d`}
            right={<Badge text="SIMULATION" tone="amber" />}>
            <div className="perf-grid">
              {[
                ["Total Trades", String(r.total_trades), ""],
                ["Win Rate", `${r.win_rate}%`, ""],
                ["Profit Factor", r.profit_factor.toFixed(2), r.profit_factor >= 1 ? "pos" : "neg"],
                ["Net P&L", `${money(r.net_r)}R (${r.net_pct >= 0 ? "+" : ""}${r.net_pct}%)`, r.net_r >= 0 ? "pos" : "neg"],
                ["Max Drawdown", `${r.max_drawdown_pct}%`, "neg"],
                ["Avg R:R", r.avg_rr.toFixed(2), ""],
                ["Best Trade", `${money(r.best_r)}R`, "pos"],
                ["Worst Trade", `${money(r.worst_r)}R`, "neg"],
                ["Win Streak", String(r.max_consecutive_wins), ""],
                ["Loss Streak", String(r.max_consecutive_losses), ""],
              ].map(([l, v, tone]) => (
                <div className="perf-item" key={l}><span className="perf-label">{l}</span><div className="perf-value-row"><span className={`perf-value ${tone}`}>{v}</span></div></div>
              ))}
            </div>
            {curve.length > 1 && <div className="chart-md" style={{ marginTop: 12 }}><AreaLine labels={curve.map((_, i) => String(i))} series={[{ name: "Equity", data: curve, color: "#8b5cf6" }]} valueFormatter={(x) => `$${x.toLocaleString()}`} /></div>}
          </Card>

          {sim!.warnings.length > 0 && (
            <Card title="Validation">
              {sim!.warnings.map((w, i) => (
                <div key={i} className="risk-item" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                  <Icon name={w.level === "ok" ? "check" : "warning"} size={15} className={wTone(w.level)} />
                  <span className={wTone(w.level)}>{w.message}</span>
                </div>
              ))}
            </Card>
          )}

          <Card title="Trade List" subtitle={`${r.trades.length} shown · entry / exit / SL / TP / reason`}>
            <div className="tablewrap">
              <table className="data-table">
                <thead><tr><th>Time</th><th>Side</th><th>Entry</th><th>Exit</th><th>Stop</th><th>Target</th><th>R</th><th>Result</th><th>Reason</th></tr></thead>
                <tbody>
                  {r.trades.slice().reverse().map((t, i) => (
                    <tr key={i}>
                      <td className="dim mono">{hhmmss(t.exit_time)}</td>
                      <td><Badge text={t.side} tone={t.side === "long" ? "green" : "red"} /></td>
                      <td>{t.entry}</td><td>{t.exit}</td><td className="dim">{t.stop}</td><td className="dim">{t.target}</td>
                      <td className={t.r >= 0 ? "pos" : "neg"}>{t.r >= 0 ? "+" : ""}{t.r}R</td>
                      <td><Badge text={t.result} tone={t.result === "win" ? "green" : "red"} /></td>
                      <td className="dim">{t.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {/* saved strategies */}
      <Card title="Saved Strategies" subtitle={`${saved.data?.length ?? 0} saved`}>
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Name</th><th>Market</th><th>Symbol</th><th>TF</th><th>Side</th><th>Updated</th><th className="ta-right">Actions</th></tr></thead>
            <tbody>
              {(saved.data ?? []).map((s) => (
                <tr key={s.id}>
                  <td><b>{s.name}</b></td><td className="dim">{s.market}</td><td>{s.symbol}</td>
                  <td className="dim">{s.timeframe}</td><td>{s.side}</td><td className="dim mono">{(s.updated_at ?? "").slice(0, 10)}</td>
                  <td><div className="row-actions">
                    <button className="icon-btn sm" title="Load / edit" onClick={() => load(s)}><Icon name="settings" size={14} /></button>
                    <button className="icon-btn sm" title="Duplicate" onClick={() => duplicate(s.id!)}><Icon name="layers" size={14} /></button>
                    <button className="icon-btn sm neg" title="Delete" onClick={() => remove(s.id!)}><Icon name="close" size={14} /></button>
                  </div></td>
                </tr>
              ))}
              {(saved.data?.length ?? 0) === 0 && <tr><td colSpan={7} className="dim ta-center" style={{ padding: 16 }}>No saved strategies yet — build one above and Save.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
