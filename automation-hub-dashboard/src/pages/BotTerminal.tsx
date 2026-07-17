import { useEffect, useMemo, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import CandleChart, { type ChartToggles } from "../components/replay/CandleChart";
import { Badge, StatCard } from "../components/common/ui";
import { useApp } from "../app-context";
import {
  apiGet, useLive,
  type ReplayData, type ReplayTrade, type AIAnalysis, type EngineStatus, type RiskSummary,
} from "../lib/api";

/** Paper Trading Bot Terminal — a premium observation deck, not a manual
 *  trading UI. Everything shown is real: the chart + trades + timeline come
 *  from a no-lookahead run of the real strategy over real candles, the
 *  Decision Engine panel from /ai/analyze, and risk config from the live
 *  engine. The Developer view exposes the per-candle brain state. */

const TFS = ["15m", "1h", "4h"];
const SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"];
const TOGGLES: ChartToggles = {
  ema8: true, ema20: false, ema30: true, ema50: false,
  sma20: false, sma50: false, vwap: false, bb: false,
  volume: true, structure: true, zones: true, osc: "none",
};
const CONF_TONE: Record<string, string> = { "Very High": "green", High: "green", Medium: "amber", Low: "red", "Very Low": "red" };
const hhmmss = (t?: string) => (t ? t.slice(11, 19) || t.slice(0, 8) : "");
const money = (n?: number | null) => (n == null ? "—" : `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`);

export default function BotTerminalPage() {
  const { toast } = useApp();
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [tf, setTf] = useState("1h");
  const [dev, setDev] = useState(false);
  const [data, setData] = useState<ReplayData | null>(null);
  const [idx, setIdx] = useState(0);
  const [sel, setSel] = useState<ReplayTrade | null>(null);
  const [loading, setLoading] = useState(false);

  const { data: eng } = useLive<EngineStatus>("/engine/status", 10000);
  const { data: risk } = useLive<RiskSummary>("/risk/summary", 10000);
  const { data: ai } = useLive<AIAnalysis>(`/ai/analyze?symbol=${symbol}&timeframe=${tf}`, 30000);

  useEffect(() => {
    let dead = false;
    setLoading(true); setSel(null);
    apiGet<ReplayData>(`/replay/run?symbol=${symbol}&timeframe=${tf}&limit=500&strategy=Decision Brain&source=binance`)
      .then((d) => { if (!dead) { setData(d?.candles?.length ? d : null); setIdx(Math.max(0, (d?.candles?.length ?? 1) - 1)); } })
      .catch(() => !dead && toast("Could not load the bot run", "error"))
      .finally(() => !dead && setLoading(false));
    return () => { dead = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, tf]);

  const frame = data?.frames?.[idx];
  const events = useMemo(() => (data?.events ?? []).slice(-60).reverse(), [data]);
  const trades = useMemo(() => [...(data?.trades ?? [])].reverse(), [data]);
  const rejections = useMemo(() => {
    const out: { idx: number; reason: string }[] = [];
    (data?.frames ?? []).forEach((f, i) => { if (f?.blocked && f.reason) out.push({ idx: i, reason: f.reason }); });
    return out.slice(-8).reverse();
  }, [data]);
  const live = data ? idx >= data.candles.length - 1 : true;
  const signal = ai?.decision === "BUY" ? "LONG" : ai?.decision === "SELL" ? "SHORT" : ai?.decision ?? "—";

  const focusTrade = (t: ReplayTrade) => { setSel(t); setIdx(t.exit_idx ?? t.entry_idx); };

  return (
    <div className="terminal">
      {/* ── header strip ─────────────────────────────────────────── */}
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <h1 className="pagehead-title" style={{ margin: 0, fontSize: 19 }}>Paper Trading Bot Terminal</h1>
          <span className="dim" style={{ fontSize: 11.5 }}>observation deck · every value is a real engine read</span>
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
        <Card title="" >
          <div className="toolbar" style={{ marginBottom: 6 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 12.5 }}>
              <b>{symbol}</b><span className="dim">{tf} · {data?.meta?.data_source_label ?? data?.meta?.data_source ?? ""}</span>
              <Badge text={eng?.running ? "engine live" : "engine stopped"} tone={eng?.running ? "green" : "default"} />
            </div>
            <div className="chips">
              {!live && <button className="chip-btn" onClick={() => { setSel(null); setIdx((data?.candles.length ?? 1) - 1); }}>↦ Latest</button>}
              <span className="dim" style={{ fontSize: 11 }}>EMA8 · EMA30 · structure · zones</span>
            </div>
          </div>
          {loading || !data?.candles?.length ? (
            <div className="dim ta-center" style={{ padding: 120 }}>{loading ? "Running the bot over real candles…" : "No data."}</div>
          ) : (
            <CandleChart data={data} index={idx} toggles={TOGGLES} height={500} />
          )}
        </Card>

        {/* right panel: Bot Decision Engine / Developer view */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
          {!dev ? (
            <Card title="Bot Decision Engine" subtitle="live read of the current candle">
              <div className="risk-list" style={{ fontSize: 12.5 }}>
                <div className="risk-item"><span className="dim">Market</span><b>{symbol.replace("USDT", "/USDT")}</b></div>
                <div className="risk-item"><span className="dim">Strategy</span><b>{data?.meta?.strategy ?? eng?.strategy ?? "Decision Brain"}</b></div>
                <div className="risk-item"><span className="dim">Market Bias</span>
                  <Badge text={ai?.market_analysis?.bias ?? "—"} tone={ai?.market_analysis?.bias === "Bullish" ? "green" : ai?.market_analysis?.bias === "Bearish" ? "red" : "default"} /></div>
                <div className="risk-item"><span className="dim">Trade Signal</span>
                  <Badge text={signal} tone={signal === "LONG" ? "green" : signal === "SHORT" ? "red" : "amber"} /></div>
                <div className="risk-item"><span className="dim">Confidence</span>
                  <b className={CONF_TONE[ai?.confidence_level ?? ""] === "green" ? "pos" : CONF_TONE[ai?.confidence_level ?? ""] === "red" ? "neg" : ""}>
                    {ai ? `${ai.confidence_pct}% · ${ai.confidence_level}` : "—"}</b></div>
              </div>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "12px 0 4px" }}>Reason for entry</div>
              <ul style={{ margin: 0, paddingLeft: 4, listStyle: "none", fontSize: 12.5, lineHeight: 1.75 }}>
                {(ai?.reasons ?? []).slice(0, 5).map((r, i) => <li key={i}><span className="pos">✓</span> {r}</li>)}
                {!ai?.reasons?.length && <li className="dim">No qualifying setup on this candle.</li>}
              </ul>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "12px 0 4px" }}>Risk management</div>
              <div className="risk-list" style={{ fontSize: 12.5 }}>
                <div className="risk-item"><span className="dim">Account risk</span><b>{risk?.risk_per_trade_pct != null ? `${(risk.risk_per_trade_pct * 100).toFixed(1)}%` : "—"}</b></div>
                <div className="risk-item"><span className="dim">Position size</span><b>{money(ai?.risk_analysis?.notional)}</b></div>
                <div className="risk-item"><span className="dim">Leverage</span><b>{ai?.risk_analysis ? `${ai.risk_analysis.leverage}x` : "1x (spot paper)"}</b></div>
                <div className="risk-item"><span className="dim">Order type</span><b style={{ textTransform: "capitalize" }}>{eng?.entry_mode ?? "limit"} order</b></div>
              </div>
            </Card>
          ) : (
            <Card title="Developer View" subtitle={`brain state @ candle ${idx + 1}${data ? ` / ${data.candles.length}` : ""}`}>
              <div className="risk-list" style={{ fontSize: 12.5 }}>
                <div className="risk-item"><span className="dim">Strategy score</span>
                  <b className={(frame?.score ?? 0) >= 60 ? "pos" : "neg"}>{frame ? `${frame.score}/100` : "—"}</b></div>
                <div className="risk-item"><span className="dim">Regime</span><b>{frame?.regime ?? "—"}</b></div>
                <div className="risk-item"><span className="dim">Trigger</span><b>{frame?.trigger || "none"}</b></div>
                <div className="risk-item"><span className="dim">Vol ratio</span><b>{frame?.vol_ratio ?? "—"}</b></div>
                <div className="risk-item"><span className="dim">Model confidence</span><b>{ai ? `${ai.engine_score ?? ai.confidence_pct}/100` : "—"}</b></div>
              </div>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "10px 0 4px" }}>Indicator / condition status</div>
              {frame?.breakdown ? Object.entries(frame.breakdown).map(([k, v]) => (
                <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span className="dim" style={{ width: 110, fontSize: 11.5 }}>{k}</span>
                  <div style={{ flex: 1, height: 5, borderRadius: 4, background: "rgba(255,255,255,0.06)" }}>
                    <div style={{ width: `${Math.min(100, Math.max(0, v * 4))}%`, height: "100%", borderRadius: 4, background: v > 0 ? "var(--green)" : "var(--red)" }} />
                  </div>
                  <span className="mono" style={{ fontSize: 11 }}>{v}</span>
                </div>
              )) : (ai?.checklist ?? []).slice(0, 8).map((c) => (
                <div key={c.name} style={{ display: "flex", gap: 8, fontSize: 12, marginBottom: 3 }}>
                  <span className={c.status === "PASS" ? "pos" : c.status === "FAIL" ? "neg" : "dim"}>{c.status === "PASS" ? "✓" : c.status === "FAIL" ? "✗" : "·"}</span>
                  <span className="dim">{c.name}</span>
                </div>
              ))}
              {frame?.blocked && <div className="banner" style={{ marginTop: 8, fontSize: 12 }}><Icon name="warning" size={12} /> Blocked: {frame.reason}</div>}
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "10px 0 4px" }}>Recent rejected trades</div>
              {rejections.length === 0 && <div className="dim" style={{ fontSize: 12 }}>None in this run.</div>}
              {rejections.map((r) => (
                <button key={r.idx} className="dev-reject" onClick={() => { setIdx(r.idx); setSel(null); }}>
                  <span className="mono dim">{hhmmss(data?.candles[r.idx]?.t)}</span> <span className="neg">✗</span> {r.reason}
                </button>
              ))}
            </Card>
          )}

          {/* selected-trade analysis */}
          {sel && (
            <Card title={`Trade #${sel.id} — ${sel.side.toUpperCase()}`} subtitle={`click ↦ Latest to return · score ${sel.score}/100`}>
              <div className="risk-list" style={{ fontSize: 12.5 }}>
                <div className="risk-item"><span className="dim">Result</span>
                  <Badge text={sel.result || sel.status || "open"} tone={(sel.rr ?? 0) > 0 ? "green" : sel.exit_idx == null ? "amber" : "red"} /></div>
                <div className="risk-item"><span className="dim">Entry → Exit</span><b>{sel.entry} → {sel.exit ?? "…"}</b></div>
                <div className="risk-item"><span className="dim">SL / TP</span><b>{sel.sl} / {sel.tp}</b></div>
                <div className="risk-item"><span className="dim">R multiple</span>
                  <b className={(sel.rr ?? 0) >= 0 ? "pos" : "neg"}>{sel.rr != null ? `${sel.rr >= 0 ? "+" : ""}${sel.rr}R` : "—"}</b></div>
                <div className="risk-item"><span className="dim">Exit reason</span><b>{sel.exit_reason ?? "—"}</b></div>
              </div>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "10px 0 4px" }}>Why it entered</div>
              <ul style={{ margin: 0, paddingLeft: 4, listStyle: "none", fontSize: 12, lineHeight: 1.7 }}>
                {(sel.entry_reasons ?? []).map((r, i) => <li key={i}><span className="pos">✓</span> {r}</li>)}
              </ul>
              {sel.loss_analysis && <div className="banner" style={{ marginTop: 8, fontSize: 12 }}><Icon name="info" size={12} /> {sel.loss_analysis}</div>}
            </Card>
          )}
        </div>
      </div>

      {/* ── bottom: timeline · trade log · performance ───────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1.3fr 1fr", gap: 12, marginTop: 12 }} className="terminal-bottom">
        <Card title="Bot Activity Timeline" subtitle="what the bot did, candle by candle">
          <div style={{ maxHeight: 250, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
            {events.map((e, i) => (
              <button key={i} className="tl-row" onClick={() => { setIdx(e.idx); setSel(null); }}>
                <span className="mono dim" style={{ fontSize: 11, width: 62, flexShrink: 0 }}>{hhmmss(data?.candles[e.idx]?.t)}</span>
                <span className={`tl-dot ${e.kind}`} />
                <span style={{ fontSize: 12.5 }}>{e.text}</span>
              </button>
            ))}
            {events.length === 0 && <div className="dim" style={{ padding: 10 }}>No activity in this run.</div>}
          </div>
        </Card>

        <Card title="Trade History" subtitle={`${data?.trades?.length ?? 0} trades · click a trade to open its analysis`}>
          <div style={{ maxHeight: 250, overflowY: "auto" }}>
            <table className="data-table" style={{ fontSize: 12 }}>
              <thead><tr><th>#</th><th>Side</th><th>Entry</th><th>Exit</th><th>R</th><th>Result</th></tr></thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id} style={{ cursor: "pointer" }} className={sel?.id === t.id ? "active-row" : ""} onClick={() => focusTrade(t)}>
                    <td className="dim">{t.id}</td>
                    <td><Badge text={t.side.toUpperCase()} tone={t.side === "long" ? "green" : "red"} /></td>
                    <td className="mono">{t.entry}</td>
                    <td className="mono dim">{t.exit ?? "open"}</td>
                    <td className={(t.rr ?? 0) >= 0 ? "pos" : "neg"}>{t.rr != null ? `${t.rr >= 0 ? "+" : ""}${t.rr}` : "—"}</td>
                    <td className={t.result === "win" ? "pos" : t.result === "loss" ? "neg" : "dim"}>{t.result || t.status || "open"}</td>
                  </tr>
                ))}
                {trades.length === 0 && <tr><td colSpan={6} className="dim ta-center" style={{ padding: 14 }}>No trades this run — the bot was selective.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Strategy Performance" subtitle="this run, real candles">
          <div className="stat-row" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <StatCard label="Win Rate" value={data?.stats ? `${data.stats.win_rate}%` : "—"} tone={(data?.stats.win_rate ?? 0) >= 50 ? "green" : "amber"} />
            <StatCard label="Net R" value={data?.stats ? `${data.stats.net_r >= 0 ? "+" : ""}${data.stats.net_r}` : "—"} tone={(data?.stats.net_r ?? 0) >= 0 ? "green" : "red"} />
            <StatCard label="Profit Factor" value={data?.stats ? String(data.stats.profit_factor) : "—"} tone={(data?.stats.profit_factor ?? 0) >= 1 ? "green" : "red"} />
            <StatCard label="Avg R" value={data?.stats ? `${data.stats.avg_rr}` : "—"} sub={data?.stats ? `${data.stats.trades} trades` : ""} />
          </div>
        </Card>
      </div>
    </div>
  );
}
