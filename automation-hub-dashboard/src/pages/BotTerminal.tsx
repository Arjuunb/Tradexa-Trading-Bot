import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import CandleChart, { type ChartToggles } from "../components/replay/CandleChart";
import { Badge, StatCard } from "../components/common/ui";
import { useApp } from "../app-context";
import {
  apiGet, useLive,
  type ReplayData, type ReplayTrade, type AIAnalysis, type EngineStatus, type RiskSummary,
} from "../lib/api";

/** Paper Trading Bot Terminal — a developer-grade observation lab, not a
 *  manual trading UI. Everything shown is real: the chart + trades + timeline
 *  come from a no-lookahead run of the real strategy over real candles (the
 *  replay analyses every candle exactly like live trading), the Decision
 *  Engine panel from /ai/analyze, and status from the live engine. */

const TFS = ["15m", "1h", "4h"];
const SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "AAPL", "SPY", "EURUSD", "XAUUSD"];
const SPEEDS = [1, 2, 5, 10, 50, 100];
const TOGGLES: ChartToggles = {
  ema8: true, ema20: false, ema30: true, ema50: false,
  sma20: false, sma50: false, vwap: true, bb: false,
  volume: true, structure: true, zones: true, osc: "none",
};
const CONF_TONE: Record<string, string> = { "Very High": "green", High: "green", Medium: "amber", Low: "red", "Very Low": "red" };
const EVT_ICON: Record<string, string> = { entry: "play", exit: "target", trade: "check", signal: "chart",
  setup: "chart", scan: "search", veto: "warning", blocked: "warning", stop: "close", info: "info" };
const hhmm = (t?: string) => (t ? t.slice(11, 16) || t.slice(0, 5) : "");
const hhmmss = (t?: string) => (t ? t.slice(11, 19) || t.slice(0, 8) : "");

export default function BotTerminalPage() {
  const { toast } = useApp();
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [tf, setTf] = useState("1h");
  const [dev, setDev] = useState(false);
  const [data, setData] = useState<ReplayData | null>(null);
  const [idx, setIdx] = useState(0);
  const [sel, setSel] = useState<ReplayTrade | null>(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const [full, setFull] = useState(false);
  const timer = useRef<number | null>(null);

  const { data: eng } = useLive<EngineStatus>("/engine/status", 10000);
  const { data: risk } = useLive<RiskSummary>("/risk/summary", 10000);
  const { data: ai } = useLive<AIAnalysis>(`/ai/analyze?symbol=${symbol}&timeframe=${tf}`, 30000);

  useEffect(() => {
    let dead = false;
    setLoading(true); setSel(null); setPlaying(false);
    apiGet<ReplayData>(`/replay/run?symbol=${symbol}&timeframe=${tf}&limit=500&strategy=Decision Brain&source=binance`)
      .then((d) => { if (!dead) { setData(d?.candles?.length ? d : null); setIdx(Math.max(0, (d?.candles?.length ?? 1) - 1)); } })
      .catch(() => !dead && toast("Could not load the bot run", "error"))
      .finally(() => !dead && setLoading(false));
    return () => { dead = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, tf]);

  // replay playback — the bot's per-candle frames are precomputed with no
  // lookahead, so stepping = watching the live decision loop candle by candle.
  useEffect(() => {
    if (!playing || !data) return;
    timer.current = window.setInterval(() => {
      setIdx((i) => {
        if (i >= data.candles.length - 1) { setPlaying(false); return i; }
        return i + 1;
      });
    }, Math.max(8, 900 / speed));
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [playing, speed, data]);

  const frame = data?.frames?.[idx];
  const candle = data?.candles?.[idx];
  const events = useMemo(() => (data?.events ?? []).filter((e) => e.idx <= idx).slice(-60).reverse(), [data, idx]);
  const trades = useMemo(() => [...(data?.trades ?? [])].reverse(), [data]);
  const rejections = useMemo(() => {
    const out: { idx: number; reason: string }[] = [];
    (data?.frames ?? []).forEach((f, i) => { if (f?.blocked && f.reason && i <= idx) out.push({ idx: i, reason: f.reason }); });
    return out.slice(-8).reverse();
  }, [data, idx]);
  const inTrade = useMemo(() => (data?.trades ?? []).find((t) => t.entry_idx <= idx && (t.exit_idx == null || t.exit_idx > idx)), [data, idx]);
  const live = data ? idx >= data.candles.length - 1 : true;
  const signal = ai?.decision === "BUY" ? "LONG" : ai?.decision === "SELL" ? "SHORT" : ai?.decision ?? "—";
  const ma = ai?.market_analysis;
  const checks = (ai?.checklist ?? []).filter((c) => c.status !== "N/A");
  // current state + what the bot is waiting for — derived from the real frame
  const state = inTrade ? `Managing an open ${inTrade.side.toUpperCase()}`
    : frame?.blocked ? "Setup rejected" : frame?.trigger ? "Confirmation received" : "Scanning";
  const waiting = inTrade ? "stop / target / exit rule"
    : frame?.blocked ? frame.reason : frame?.trigger ? "entry execution" : "a qualifying setup";

  const focusTrade = (t: ReplayTrade) => { setSel(t); setPlaying(false); setIdx(t.exit_idx ?? t.entry_idx); };
  const durationOf = (t: ReplayTrade) => {
    const a = data?.candles?.[t.entry_idx]?.t, b = t.exit_idx != null ? data?.candles?.[t.exit_idx]?.t : undefined;
    if (!a || !b) return t.bars_held != null ? `${t.bars_held} bars` : "—";
    const mins = Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60000);
    return mins >= 60 ? `${(mins / 60).toFixed(1)}h` : `${mins}m`;
  };

  const kv = (label: string, value: ReactNode) => (
    <div className="risk-item"><span className="dim">{label}</span><b>{value}</b></div>);

  return (
    <div className="terminal">
      {/* ── header strip ─────────────────────────────────────────── */}
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <h1 className="pagehead-title" style={{ margin: 0, fontSize: 19 }}>Paper Trading Bot Terminal</h1>
          <span className="dim" style={{ fontSize: 11.5 }}>observation lab · every value is a real engine read</span>
        </div>
        <div className="chips" style={{ alignItems: "center" }}>
          <select className="rule-num" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {SYMS.map((s) => <option key={s}>{s}</option>)}
          </select>
          {TFS.map((t) => <button key={t} className={`chip-btn ${tf === t ? "active" : ""}`} onClick={() => setTf(t)}>{t}</button>)}
          <span style={{ width: 10 }} />
          <div className="seg-toggle">
            <button className={!dev ? "on" : ""} onClick={() => setDev(false)}>Normal</button>
            <button className={dev ? "on" : ""} onClick={() => setDev(true)}>Developer</button>
          </div>
        </div>
      </div>

      {data?.meta?.data_warning && (
        <div className="banner" style={{ marginBottom: 10 }}><Icon name="warning" size={14} /> {data.meta.data_warning}</div>
      )}

      {/* ── main: chart (70%) + decision engine ─────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 330px", gap: 12 }} className="terminal-main">
        <div className={full ? "chart-full" : ""}>
        <Card title="">
          <div className="toolbar" style={{ marginBottom: 6 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 12.5 }}>
              <b>{symbol}</b><span className="dim">{tf} · {data?.meta?.data_source_label ?? data?.meta?.data_source ?? ""}</span>
              <Badge text={eng?.running ? "engine live" : "engine stopped"} tone={eng?.running ? "green" : "default"} />
              {inTrade && <Badge text={`in ${inTrade.side} trade`} tone={inTrade.side === "long" ? "green" : "red"} />}
            </div>
            <div className="chips">
              <span className="dim" style={{ fontSize: 11 }}>EMA8 · EMA30 · VWAP · structure · zones · scroll to zoom</span>
              <button className="chip-btn" title="Fullscreen" onClick={() => setFull((f) => !f)}>
                <Icon name="external" size={12} /> {full ? "Exit" : "Full"}</button>
            </div>
          </div>
          {loading || !data?.candles?.length ? (
            <div className="dim ta-center" style={{ padding: 120 }}>{loading ? "Running the bot over real candles…" : "No data."}</div>
          ) : (
            <CandleChart data={data} index={idx} toggles={TOGGLES} height={full ? Math.max(420, window.innerHeight - 220) : 470} />
          )}
          {/* replay controls — the bot re-analyses every candle exactly like live */}
          {data && (
            <div className="row-actions" style={{ gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
              <button className="btn btn-soft" onClick={() => { setPlaying(false); setIdx(0); }} title="Restart"><Icon name="refresh" size={13} /></button>
              <button className="btn btn-soft" onClick={() => { setPlaying(false); setIdx((i) => Math.max(0, i - 1)); }} title="Step back"><Icon name="skipBack" size={13} /></button>
              <button className="btn btn-primary" onClick={() => setPlaying((p) => !p)}>
                <Icon name={playing ? "pause" : "play"} size={13} /> {playing ? "Pause" : "Replay"}</button>
              <button className="btn btn-soft" onClick={() => { setPlaying(false); setIdx((i) => Math.min((data.candles.length - 1), i + 1)); }} title="Step forward"><Icon name="skipForward" size={13} /></button>
              <span className="dim" style={{ fontSize: 11 }}>Speed</span>
              {SPEEDS.map((s) => <button key={s} className={`chip-btn ${speed === s ? "active" : ""}`} onClick={() => setSpeed(s)}>{s}x</button>)}
              {!live && <button className="chip-btn" onClick={() => { setSel(null); setPlaying(false); setIdx(data.candles.length - 1); }}>↦ Latest</button>}
              <span className="dim mono" style={{ marginLeft: "auto", fontSize: 11 }}>
                {idx + 1} / {data.candles.length} · {(candle?.t ?? "").replace("T", " ").slice(0, 16)}</span>
            </div>
          )}
          {data && (
            <input type="range" min={0} max={data.candles.length - 1} value={idx}
              onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} style={{ width: "100%", marginTop: 6 }} />
          )}
        </Card>
        </div>

        {/* right panel: Bot Decision Engine / Developer view */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
          {!dev ? (
            <Card title="Bot Decision Engine" subtitle="live AI reasoning on the current candle">
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span className={`pulse-dot ${inTrade ? "green" : frame?.blocked ? "red" : "gold"}`} />
                <b style={{ fontSize: 13 }}>{state}</b>
                <span className="dim" style={{ fontSize: 11.5, marginLeft: "auto" }}>waiting for: {waiting}</span>
              </div>
              <div className="risk-list" style={{ fontSize: 12.5 }}>
                {kv("Strategy", data?.meta?.strategy ?? eng?.strategy ?? "Decision Brain")}
                {kv("Market Bias", <Badge text={ma?.bias ?? "—"} tone={ma?.bias === "Bullish" ? "green" : ma?.bias === "Bearish" ? "red" : "default"} />)}
                {kv("Trend", `${ma?.trend?.strength_label ?? "—"}`)}
                {kv("Structure", ma?.structure?.state ?? "—")}
                {kv("HTF Bias", frame?.trends ? Object.entries(frame.trends).map(([k, v]) => `${k}:${v}`).join(" ") : "—")}
                {kv("Volatility", ma?.volatility?.label ?? "—")}
                {kv("Liquidity", String(ma?.liquidity?.sweep ?? "—"))}
                {kv("Momentum (vol ratio)", frame?.vol_ratio != null ? `×${frame.vol_ratio}` : "—")}
                {kv("Trade Quality", <span className={(frame?.score ?? 0) >= 60 ? "pos" : "neg"}>{frame ? `${frame.score}/100` : "—"}</span>)}
                {kv("Confidence", <span className={CONF_TONE[ai?.confidence_level ?? ""] === "green" ? "pos" : CONF_TONE[ai?.confidence_level ?? ""] === "red" ? "neg" : ""}>
                  {ai ? `${ai.confidence_pct}% · ${ai.confidence_level}` : "—"}</span>)}
                {kv("Decision", <Badge text={signal} tone={signal === "LONG" ? "green" : signal === "SHORT" ? "red" : "amber"} />)}
              </div>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "12px 0 4px" }}>Reasoning</div>
              <ul style={{ margin: 0, paddingLeft: 4, listStyle: "none", fontSize: 12.5, lineHeight: 1.7 }}>
                {checks.slice(0, 7).map((c) => (
                  <li key={c.name}>
                    <span className={c.status === "PASS" ? "pos" : "neg"}>{c.status === "PASS" ? "✔" : "✘"}</span> {c.name}
                  </li>
                ))}
                {!checks.length && <li className="dim">Analysing…</li>}
              </ul>
            </Card>
          ) : (
            <Card title="Developer View" subtitle={`brain state @ candle ${idx + 1}${data ? ` / ${data.candles.length}` : ""}`}>
              <div className="risk-list" style={{ fontSize: 12.5 }}>
                {kv("Strategy score", <span className={(frame?.score ?? 0) >= 60 ? "pos" : "neg"}>{frame ? `${frame.score}/100` : "—"}</span>)}
                {kv("Regime", frame?.regime ?? "—")}
                {kv("Trigger", frame?.trigger || "none")}
                {kv("Vol ratio", frame?.vol_ratio != null ? `×${frame.vol_ratio}` : "—")}
                {kv("Model confidence", ai ? `${ai.engine_score ?? ai.confidence_pct}/100` : "—")}
                {kv("Entry gate", frame?.blocked ? <span className="neg">FAIL</span> : <span className="pos">PASS</span>)}
              </div>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "10px 0 4px" }}>Score components</div>
              {frame?.breakdown ? Object.entries(frame.breakdown).map(([k, v]) => (
                <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span className="dim" style={{ width: 110, fontSize: 11.5 }}>{k}</span>
                  <div style={{ flex: 1, height: 5, borderRadius: 4, background: "rgba(255,255,255,0.06)" }}>
                    <div style={{ width: `${Math.min(100, Math.max(0, v * 4))}%`, height: "100%", borderRadius: 4, background: v > 0 ? "var(--green)" : "var(--red)", transition: "width 0.3s" }} />
                  </div>
                  <span className="mono" style={{ fontSize: 11 }}>{v}</span>
                </div>
              )) : <div className="dim" style={{ fontSize: 12 }}>No scored setup on this candle.</div>}
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "10px 0 4px" }}>Filter status (live gate)</div>
              {checks.slice(0, 8).map((c) => (
                <div key={c.name} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
                  <span className="dim">{c.name}</span>
                  <b className={c.status === "PASS" ? "pos" : "neg"}>{c.status}</b>
                </div>
              ))}
              {frame?.blocked && <div className="banner" style={{ marginTop: 8, fontSize: 12 }}><Icon name="warning" size={12} /> Blocked: {frame.reason}</div>}
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "10px 0 4px" }}>Recent rejected trades</div>
              {rejections.length === 0 && <div className="dim" style={{ fontSize: 12 }}>None up to this candle.</div>}
              {rejections.map((r) => (
                <button key={r.idx} className="dev-reject" onClick={() => { setPlaying(false); setIdx(r.idx); setSel(null); }}>
                  <span className="mono dim">{hhmmss(data?.candles[r.idx]?.t)}</span> <span className="neg">✗</span> {r.reason}
                </button>
              ))}
            </Card>
          )}

          {/* selected-trade analysis */}
          {sel && (
            <Card title={`Trade #${sel.id} — ${sel.side.toUpperCase()}`} subtitle={`${symbol} · ${hhmm(data?.candles?.[sel.entry_idx]?.t)} UTC`}>
              <div className="risk-list" style={{ fontSize: 12.5 }}>
                {kv("Result", <Badge text={sel.result || sel.status || "open"} tone={(sel.rr ?? 0) > 0 ? "green" : sel.exit_idx == null ? "amber" : "red"} />)}
                {kv("Entry → Exit", `${sel.entry} → ${sel.exit ?? "…"}`)}
                {kv("SL / TP", `${sel.sl} / ${sel.tp}`)}
                {kv("R multiple", <span className={(sel.rr ?? 0) >= 0 ? "pos" : "neg"}>{sel.rr != null ? `${sel.rr >= 0 ? "+" : ""}${sel.rr}R` : "—"}</span>)}
                {kv("Setup score", `${sel.score}/100`)}
                {kv("Regime", sel.regime ?? frame?.regime ?? "—")}
                {kv("Duration", durationOf(sel))}
                {kv("Exit reason", sel.exit_reason ?? "—")}
                {kv("Risk / trade", risk?.risk_per_trade_pct != null ? `${(risk.risk_per_trade_pct * 100).toFixed(1)}%` : "—")}
              </div>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "10px 0 4px" }}>Why it entered</div>
              <ul style={{ margin: 0, paddingLeft: 4, listStyle: "none", fontSize: 12, lineHeight: 1.7 }}>
                {(sel.entry_reasons ?? []).map((r, i) => <li key={i}><span className="pos">✔</span> {r}</li>)}
              </ul>
              {sel.mtf?.reason && <div className="dim" style={{ fontSize: 11.5, marginTop: 6 }}>MTF: {sel.mtf.reason}</div>}
              {sel.loss_analysis && <div className="banner" style={{ marginTop: 8, fontSize: 12 }}><Icon name="info" size={12} /> {sel.loss_analysis}</div>}
              <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>Fees / slippage: not modeled in this run (R-based simulation).</div>
            </Card>
          )}
        </div>
      </div>

      {/* ── bottom: timeline · trade log · performance ───────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1.05fr 1.45fr 1fr", gap: 12, marginTop: 12 }} className="terminal-bottom">
        <Card title="Bot Activity Timeline" subtitle="what the bot did, candle by candle">
          <div style={{ maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 5 }}>
            {events.map((e, i) => (
              <button key={i} className="tl-row" onClick={() => { setPlaying(false); setIdx(e.idx); setSel(null); }}>
                <span className="mono dim" style={{ fontSize: 11, width: 44, flexShrink: 0 }}>{hhmm(data?.candles[e.idx]?.t)}</span>
                <span className={`tl-dot ${e.kind}`} />
                <Icon name={EVT_ICON[e.kind] ?? "info"} size={12} className="dim" />
                <span style={{ fontSize: 12.5 }}>{e.text}</span>
              </button>
            ))}
            {events.length === 0 && <div className="dim" style={{ padding: 10 }}>No activity up to this candle.</div>}
          </div>
        </Card>

        <Card title="Trade History" subtitle={`${data?.trades?.length ?? 0} trades · click a trade to open its analysis`}>
          <div style={{ maxHeight: 260, overflowY: "auto" }}>
            <table className="data-table" style={{ fontSize: 11.5 }}>
              <thead><tr><th>#</th><th>Strategy</th><th>Dir</th><th>Entry</th><th>Exit</th><th>R</th><th>Score</th><th>Duration</th><th>Regime</th><th>Status</th></tr></thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id} style={{ cursor: "pointer" }} className={sel?.id === t.id ? "active-row" : ""} onClick={() => focusTrade(t)}>
                    <td className="dim">{t.id}</td>
                    <td className="dim" style={{ maxWidth: 90, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{data?.meta?.strategy ?? "Brain"}</td>
                    <td><Badge text={t.side === "long" ? "LONG" : "SHORT"} tone={t.side === "long" ? "green" : "red"} /></td>
                    <td className="mono">{t.entry}</td>
                    <td className="mono dim">{t.exit ?? "open"}</td>
                    <td className={(t.rr ?? 0) >= 0 ? "pos" : "neg"}>{t.rr != null ? `${t.rr >= 0 ? "+" : ""}${t.rr}` : "—"}</td>
                    <td className="dim">{t.score}</td>
                    <td className="dim">{durationOf(t)}</td>
                    <td className="dim">{t.regime ?? "—"}</td>
                    <td className={t.result === "win" ? "pos" : t.result === "loss" ? "neg" : "dim"}>{t.result || t.status || "open"}</td>
                  </tr>
                ))}
                {trades.length === 0 && <tr><td colSpan={10} className="dim ta-center" style={{ padding: 14 }}>No trades this run — the bot was selective.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Strategy Performance" subtitle="this run, real candles">
          <div className="stat-row" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <StatCard label="Win Rate" value={data?.stats ? `${data.stats.win_rate}%` : "—"} tone={(data?.stats?.win_rate ?? 0) >= 50 ? "green" : "amber"} />
            <StatCard label="Net R" value={data?.stats ? `${data.stats.net_r >= 0 ? "+" : ""}${data.stats.net_r}` : "—"} tone={(data?.stats?.net_r ?? 0) >= 0 ? "green" : "red"} />
            <StatCard label="Profit Factor" value={data?.stats ? String(data.stats.profit_factor) : "—"} tone={(data?.stats?.profit_factor ?? 0) >= 1 ? "green" : "red"} />
            <StatCard label="Expectancy" value={data?.stats ? `${data.stats.expectancy_r >= 0 ? "+" : ""}${data.stats.expectancy_r}R` : "—"} tone={(data?.stats?.expectancy_r ?? 0) >= 0 ? "green" : "red"} />
            <StatCard label="Avg RR" value={data?.stats ? `${data.stats.avg_rr}` : "—"} sub={data?.stats ? `${data.stats.trades} trades` : ""} />
            <StatCard label="Max DD" value={data?.stats ? `${data.stats.max_drawdown_r}R` : "—"} tone="amber" />
            <StatCard label="Max Consec W / L" value={data?.stats ? `${data.stats.max_consecutive_wins} / ${data.stats.max_consecutive_losses}` : "—"} />
            <StatCard label="Streak" value={data?.stats ? `${data.stats.current_streak > 0 ? "+" : ""}${data.stats.current_streak}` : "—"}
              tone={(data?.stats?.current_streak ?? 0) >= 0 ? "green" : "red"} />
          </div>
        </Card>
      </div>

      {/* ── live status bar (real fields only — nothing invented) ── */}
      <div className="term-status">
        <span><span className="dim">Data</span> {data?.meta?.data_source_label ?? data?.meta?.data_source ?? "—"}</span>
        <span><span className="dim">Feed</span> <span className={eng?.running ? "pos" : "dim"}>{(eng as any)?.feed_status ?? (eng?.running ? "running" : "stopped")}</span></span>
        <span><span className="dim">Bars</span> {data?.candles?.length ?? 0}</span>
        <span><span className="dim">Last candle</span> {hhmmss(data?.candles?.[data.candles.length - 1]?.t) || "—"}</span>
        <span><span className="dim">Strategy</span> {data?.meta?.debug?.strategy_id ?? data?.meta?.strategy ?? "—"}</span>
        <span><span className="dim">Computed</span> {hhmmss(data?.meta?.debug?.computed_at) || "—"} UTC</span>
        <span style={{ marginLeft: "auto" }}><span className={`pulse-dot ${eng?.running ? "green" : "dim"}`} /> {eng?.running ? "engine analysing" : "engine idle"}</span>
      </div>
    </div>
  );
}
