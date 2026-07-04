import { useState } from "react";
import Card from "../components/common/Card";
import ProgressBar from "../components/common/ProgressBar";
import Icon from "../components/common/Icon";
import { Badge, PageHeader } from "../components/common/ui";
import { useApp } from "../app-context";
import {
  apiPost, apiPostJson, apiGet, useLive, hhmmss,
  type AlertRow, type RiskSummary, type PositionSizeResult, type CorrelationData, type PortfolioRisk,
  type Recovery, type HealthCard,
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

      <PortfolioRiskPanel />

      <div className="grid-2-eq">
        <DrawdownRecovery />
        <StrategyHealthCard />
      </div>

      <div className="grid-2-eq">
        <PositionSizer />
        <CorrelationMatrix />
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

const money = (n: number | null | undefined) => `$${(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

function PortfolioRiskPanel() {
  const pf = useLive<PortfolioRisk>("/risk/portfolio", 4000);
  const r = pf.data;
  const lvlTone = r?.risk_level === "high" ? "red" : r?.risk_level === "elevated" ? "amber" : "green";
  const cells: [string, string, string][] = r ? [
    ["Total Exposure", money(r.total_exposure), `${r.exposure_pct}% of equity`],
    ["Long / Short", `${money(r.long_exposure)} / ${money(r.short_exposure)}`, `net ${money(r.net_exposure)}`],
    ["Portfolio Heat", `${r.portfolio_heat_pct}%`, "open risk / equity"],
    ["Value at Risk (1d)", r.value_at_risk_pct != null ? `${r.value_at_risk_pct}%` : "—", r.value_at_risk != null ? `${money(r.value_at_risk)} · ${Math.round(r.var_confidence * 100)}%` : "needs data"],
    ["Daily Risk Used", `${r.daily_risk_used_pct}%`, ""],
    ["Open Positions", String(r.open_positions ?? 0), ""],
  ] : [];
  return (
    <Card title="Portfolio Risk Engine" subtitle="exposure · heat · parametric VaR from real covariance"
      right={r && <Badge text={`${r.risk_level} risk`} tone={lvlTone as any} />}>
      <div className="perf-grid">
        {cells.map(([l, v, s]) => (
          <div className="perf-item" key={l}>
            <span className="perf-label">{l}</span>
            <div className="perf-value-row"><span className="perf-value">{v}</span></div>
            {s && <span className="perf-label" style={{ fontSize: 10 }}>{s}</span>}
          </div>
        ))}
      </div>
      {(r?.warnings?.length ?? 0) > 0 && r!.warnings.map((w, i) => (
        <div key={i} className="card" style={{ marginTop: 8, borderColor: "var(--gold)", background: "rgba(234,181,79,0.08)" }}>
          <Icon name="warning" size={14} className="amber" /> {w}
        </div>
      ))}
      {r && (r.warnings ?? []).length === 0 && <p className="dim" style={{ marginTop: 8 }}>Within all portfolio risk limits.</p>}
    </Card>
  );
}

const SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"];
const METHODS = [["percent", "% risk"], ["fixed", "Fixed $"], ["atr", "ATR"], ["vol_adjusted", "Vol-adjusted"]];

function PositionSizer() {
  const [equity, setEquity] = useState(10000);
  const [entry, setEntry] = useState(100);
  const [stop, setStop] = useState(95);
  const [side, setSide] = useState("long");
  const [method, setMethod] = useState("percent");
  const [riskPct, setRiskPct] = useState(1);
  const [atr, setAtr] = useState(2);
  const [leverage, setLeverage] = useState(10);
  const [res, setRes] = useState<PositionSizeResult | null>(null);

  const calc = async () => {
    const body: any = { equity, entry, side, method, risk_pct: riskPct / 100, leverage };
    if (method === "atr" || method === "vol_adjusted") body.atr = atr;
    if (method !== "atr") body.stop = stop;
    try { setRes(await apiPostJson<PositionSizeResult>("/risk/position-size", body)); }
    catch { setRes({ error: "request failed" } as any); }
  };

  return (
    <Card title="Position Sizing Calculator" subtitle="fixed / % / ATR / volatility-adjusted">
      <div className="form-grid-2">
        <Num label="Account equity ($)" value={equity} step={100} onChange={setEquity} />
        <label className="field"><span className="field-label">Method</span>
          <select value={method} onChange={(e) => setMethod(e.target.value)}>{METHODS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <Num label="Entry price" value={entry} step={0.1} onChange={setEntry} />
        {method === "atr" || method === "vol_adjusted"
          ? <Num label="ATR" value={atr} step={0.1} onChange={setAtr} />
          : <Num label="Stop price" value={stop} step={0.1} onChange={setStop} />}
        <Num label="Risk %" value={riskPct} step={0.1} onChange={setRiskPct} />
        <Num label="Leverage" value={leverage} step={1} onChange={setLeverage} />
        <label className="field"><span className="field-label">Side</span>
          <select value={side} onChange={(e) => setSide(e.target.value)}><option value="long">Long</option><option value="short">Short</option></select></label>
      </div>
      <button className="btn btn-primary" style={{ marginTop: 10 }} onClick={calc}><Icon name="target" size={14} /> Calculate</button>
      {res && (res.error
        ? <p className="neg" style={{ marginTop: 8 }}><Icon name="warning" size={13} /> {res.error}</p>
        : <div className="risk-list" style={{ marginTop: 10 }}>
            <div className="risk-item"><span className="dim">Position size</span> <b>{res.position_size} units</b></div>
            <div className="risk-item"><span className="dim">Notional</span> <b>{money(res.notional)}</b></div>
            <div className="risk-item"><span className="dim">Dollar risk</span> <b className="neg">{money(res.dollar_risk)} ({res.risk_pct_of_equity}%)</b></div>
            <div className="risk-item"><span className="dim">Margin required</span> <b>{money(res.margin_required)} @ {res.leverage}×</b></div>
            <div className="risk-item"><span className="dim">Stop</span> <b>{res.stop} ({res.stop_distance} away)</b></div>
            <div className="risk-item"><span className="dim">Liquidation est.</span> <b className="amber">{res.liquidation_estimate}</b></div>
          </div>)}
    </Card>
  );
}

function CorrelationMatrix() {
  const [tf, setTf] = useState("1d");
  const [data, setData] = useState<CorrelationData | null>(null);
  const [loading, setLoading] = useState(false);
  const load = async () => {
    setLoading(true);
    try { setData(await apiGet<CorrelationData>(`/risk/correlation?symbols=${SYMS.join(",")}&timeframe=${tf}&lookback=200`)); }
    catch { /* leave */ } finally { setLoading(false); }
  };
  const cell = (c: number | null) => {
    if (c === null) return { bg: "transparent", txt: "var(--dim-2)" };
    const a = Math.abs(c);
    const col = c >= 0 ? "34,197,94" : "239,68,68";
    return { bg: `rgba(${col},${(a * 0.5).toFixed(2)})`, txt: a > 0.6 ? "#fff" : "var(--dim)" };
  };
  return (
    <Card title="Correlation Matrix" subtitle="log-return correlation · prevents stacking correlated trades"
      right={<div className="row-actions" style={{ gap: 6 }}>
        <select value={tf} onChange={(e) => setTf(e.target.value)}>{["4h", "1d", "1w"].map((t) => <option key={t}>{t}</option>)}</select>
        <button className="btn btn-soft" disabled={loading} onClick={load}><Icon name="refresh" size={13} /> {loading ? "…" : data ? "Refresh" : "Load"}</button>
      </div>}>
      {!data ? <div className="dim ta-center" style={{ padding: 18 }}>Load the correlation matrix from the real candle store.</div> : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table" style={{ textAlign: "center" }}>
              <thead><tr><th></th>{(data?.symbols ?? []).map((s) => <th key={s} style={{ textAlign: "center" }}>{s.replace("USDT", "")}</th>)}</tr></thead>
              <tbody>
                {(data?.symbols ?? []).map((a) => (
                  <tr key={a}>
                    <td><b>{a.replace("USDT", "")}</b></td>
                    {(data?.symbols ?? []).map((b) => {
                      const c = data.matrix[a]?.[b] ?? null; const st = cell(c);
                      return <td key={b} style={{ background: st.bg, color: st.txt, fontWeight: 600 }}>{c === null ? "—" : c.toFixed(2)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.pairs[0] && Math.abs(data.pairs[0].correlation) >= 0.8 && (
            <div className="card" style={{ marginTop: 8, borderColor: "var(--gold)", background: "rgba(234,181,79,0.08)" }}>
              <Icon name="warning" size={13} className="amber" /> {data.pairs[0].a.replace("USDT", "")}/{data.pairs[0].b.replace("USDT", "")} are {data.pairs[0].correlation.toFixed(2)} correlated — avoid opening both at once.
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function Num({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (v: number) => void }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <input type="number" value={value} step={step} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

const HEALTH_SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"];
const HEALTH_STRATS = ["Decision Brain", "Trend Following", "Supply/Demand", "EMA 8/30", "EMA 20/50", "Liquidity Sweep"];
const modeTone = (m: string) => (m === "normal" ? "green" : m === "caution" ? "amber" : "red");

function DrawdownRecovery() {
  const rec = useLive<Recovery>("/risk/recovery", 5000);
  const r = rec.data;
  return (
    <Card title="Drawdown Recovery" subtitle="auto risk-down as drawdown deepens"
      right={r && <Badge text={r.mode} tone={modeTone(r.mode) as any} />}>
      {!r ? <div className="dim">—</div> : (
        <>
          <div className="risk-list">
            <div className="risk-item"><span className="dim">Drawdown</span> <b className={r.drawdown_pct > 0 ? "neg" : ""}>{r.drawdown_pct}%</b></div>
            <div className="risk-item"><span className="dim">Risk multiplier</span> <b>{Math.round(r.risk_multiplier * 100)}%</b></div>
            <div className="risk-item"><span className="dim">Max trades</span> <b>{Math.round(r.max_trades_factor * 100)}%</b></div>
            <div className="risk-item"><span className="dim">Equity / peak</span> <b>${(r.equity ?? 0).toLocaleString()} / ${(r.peak_equity ?? 0).toLocaleString()}</b></div>
          </div>
          {r.recovery_active ? (
            <div className="card" style={{ marginTop: 8, borderColor: "var(--gold)", background: "rgba(234,181,79,0.08)" }}>
              <b className="amber"><Icon name="shield" size={13} /> Recovery actions</b>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.5 }}>{(r.actions ?? []).map((a, i) => <li key={i}>{a}</li>)}</ul>
            </div>
          ) : <p className="dim" style={{ marginTop: 8 }}>Within the safe band — full risk allowed.</p>}
        </>
      )}
    </Card>
  );
}

function StrategyHealthCard() {
  const [strategy, setStrategy] = useState("Decision Brain");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [card, setCard] = useState<HealthCard | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setCard(await apiGet<HealthCard>(`/health/scorecard?symbol=${symbol}&strategy=${encodeURIComponent(strategy)}&timeframe=15m&limit=800`)); }
    catch { setCard({ available: false, error: "request failed" } as any); }
    finally { setBusy(false); }
  };
  const ring = (label: string, val: number) => (
    <div className="perf-item"><span className="perf-label">{label}</span>
      <div className="perf-value-row"><span className={`perf-value ${val >= 60 ? "pos" : val >= 35 ? "amber" : "neg"}`}>{val}</span></div></div>
  );
  return (
    <Card title="Strategy Health" subtitle="win/PF/drawdown + stability & confidence — auto-flagged"
      right={<div className="row-actions" style={{ gap: 6 }}>
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>{HEALTH_STRATS.map((s) => <option key={s}>{s}</option>)}</select>
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>{HEALTH_SYMS.map((s) => <option key={s}>{s}</option>)}</select>
        <button className="btn btn-primary" disabled={busy} onClick={run}>{busy ? "…" : "Check"}</button>
      </div>}>
      {!card ? <div className="dim ta-center" style={{ padding: 14 }}>Run a health check on a strategy.</div>
        : card.available === false ? <p className="neg"><Icon name="warning" size={13} /> {card.error}</p>
        : (
        <>
          <div className="row-actions" style={{ justifyContent: "space-between" }}>
            <Badge text={card.classification ?? card.status} tone={(card.classification ?? card.status) === "Healthy" ? "green" : (card.classification ?? card.status) === "Warning" ? "amber" : "red"} />
            {card.health_score != null && <span className="dim" style={{ fontSize: 12 }}>health {card.health_score}/100</span>}
          </div>
          <div className="perf-grid" style={{ marginTop: 8 }}>
            {ring("Stability", card.stability_score)}
            {ring("Confidence", card.confidence_score)}
            {ring("Drawdown", card.drawdown_score ?? 0)}
            <div className="perf-item"><span className="perf-label">Win rate</span><div className="perf-value-row"><span className="perf-value">{card.win_rate}%</span></div></div>
            <div className="perf-item"><span className="perf-label">Profit factor</span><div className="perf-value-row"><span className={`perf-value ${card.profit_factor >= 1 ? "pos" : "neg"}`}>{card.profit_factor}</span></div></div>
            <div className="perf-item"><span className="perf-label">Trades</span><div className="perf-value-row"><span className="perf-value">{card.trades}</span></div></div>
          </div>
          {(card.reasons?.length ?? 0) > 0 && (
            <p className="dim" style={{ fontSize: 11, marginTop: 6 }}>{card.reasons!.slice(0, 2).join(" · ")}</p>
          )}
          {card.warnings.length > 0 && card.warnings.map((w, i) => (
            <p key={i} className={w.severity === "critical" ? "neg" : "amber"} style={{ marginTop: 4, fontSize: 12 }}><Icon name="warning" size={12} /> {w.detail}</p>
          ))}
        </>
      )}
    </Card>
  );
}
