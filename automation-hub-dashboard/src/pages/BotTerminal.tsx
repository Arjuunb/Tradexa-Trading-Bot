import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import CandleChart, { type ChartToggles, type ExtraLine } from "../components/replay/CandleChart";
import { Badge, StatCard } from "../components/common/ui";
import EquityCurve from "../components/chart/EquityCurve";
import { useApp } from "../app-context";
import {
  apiGet, apiPostJson, useLive,
  type ReplayData, type ReplayTrade, type AIAnalysis, type EngineStatus, type RiskSummary,
  type LedgerPosition, type PaperTradeRow, type LogRow, type PaperAccount,
} from "../lib/api";

/** Paper Trading Bot Terminal — a developer-grade observation lab.
 *  LIVE mode: candles stream tick-by-tick from Binance's public WebSocket
 *  (straight into the browser, like TradingView), while the panels show the
 *  LIVE engine's real open position, real trades and real activity log.
 *  REPLAY mode: a no-lookahead run of the strategy over real candles with
 *  play/step/speed controls. Nothing on this page is fabricated. */

// Intraday-first: an automated strategy belongs on low timeframes (1–5m); the
// higher ones (1h/4h) suit manual swing trading and are kept for those who want it.
const TFS = ["1m", "3m", "5m", "15m", "1h", "4h"];
const SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "AAPL", "SPY", "EURUSD", "XAUUSD"];
const CRYPTO = new Set(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]);
const SPEEDS = [1, 2, 5, 10, 50, 100];
// Strategies the replay engine can visualize (each maps to a real entry engine).
const STRATS = ["Decision Brain", "Trend Following", "Supply/Demand", "EMA 8/30",
  "EMA 20/50", "Breakout Retest", "Support/Resistance Rejection", "Liquidity Sweep"];
// The live engine labels its strategy differently from the replay presets — map
// it so the terminal defaults to the strategy the engine is actually running.
const ENGINE_STRAT_MAP: Record<string, string> = {
  "Decision Brain": "Decision Brain", "Supertrend": "Trend Following",
  "SMC (Smart Money)": "Supply/Demand", "EMA Crossover": "EMA 8/30",
  "Donchian Breakout": "Decision Brain", "Confirmation Ensemble": "Decision Brain",
};
// The reverse: terminal presets that map to a real built-in engine strategy, so
// selecting them here can actually reconfigure the live bot. The other presets
// are chart-only replay views (no matching built-in engine strategy).
const STRAT_TO_ENGINE: Record<string, { key: string; label: string }> = {
  "Decision Brain": { key: "brain", label: "Decision Brain" },
  "Trend Following": { key: "supertrend", label: "Supertrend" },
  "Supply/Demand": { key: "smc", label: "SMC (Smart Money)" },
  "EMA 8/30": { key: "ema", label: "EMA Crossover" },
};
// Fallback only — used if the backend didn't send a viz spec. Normally the
// chart is driven entirely by data.meta.viz (the ACTIVE strategy's real inputs).
const FALLBACK_TOGGLES: ChartToggles = {
  ema8: false, ema20: false, ema30: false, ema50: false,
  sma20: false, sma50: false, vwap: false, bb: false,
  volume: true, structure: true, zones: true, osc: "none", supertrend: false, crossovers: false,
};
// Overlay keys the chart draws via its fixed toggles; anything else the strategy
// declares (e.g. a custom EMA period) is passed through as an extra line.
const KNOWN_OVERLAYS = new Set(["ema8", "ema20", "ema30", "ema50", "sma20", "sma50",
  "vwap", "bb_upper", "bb_mid", "bb_lower", "supertrend"]);
const EXTRA_COLORS = ["#22d3ee", "#a855f7", "#f59e0b", "#3b82f6", "#ec4899", "#10b981"];
const CONF_TONE: Record<string, string> = { "Very High": "green", High: "green", Medium: "amber", Low: "red", "Very Low": "red" };
const EVT_ICON: Record<string, string> = { entry: "play", exit: "target", trade: "check", signal: "chart",
  setup: "chart", scan: "search", veto: "warning", blocked: "warning", stop: "close", info: "info" };
const STAGE_ICON: Record<string, string> = { engine: "robot", execution: "play", brain: "bot", risk: "shield",
  controls: "settings", webhook: "external", account: "wallet", market: "globe", bots: "robot" };
const hhmm = (t?: string) => (t ? t.slice(11, 16) || t.slice(0, 5) : "");
const hhmmss = (t?: string) => (t ? t.slice(11, 19) || t.slice(0, 8) : "");

export default function BotTerminalPage() {
  const { toast } = useApp();
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [tf, setTf] = useState("5m");
  const [strategy, setStrategy] = useState("Decision Brain");
  const [mode, setMode] = useState<"live" | "replay">("live");
  const [dev, setDev] = useState(false);
  const [data, setData] = useState<ReplayData | null>(null);
  const [idx, setIdx] = useState(0);
  const [sel, setSel] = useState<ReplayTrade | null>(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const [full, setFull] = useState(false);
  const [wsOk, setWsOk] = useState(false);
  const [closing, setClosing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [dockTab, setDockTab] = useState<"positions" | "history" | "orders" | "activity" | "performance" | "equity">("positions");
  const timer = useRef<number | null>(null);

  const liveMode = mode === "live";
  const { data: eng, refetch: refetchEng } = useLive<EngineStatus>("/engine/status", liveMode ? 5000 : 10000);
  const { data: risk } = useLive<RiskSummary>("/risk/summary", 10000);
  const { data: acct } = useLive<PaperAccount>("/paper/account", liveMode ? 8000 : 30000);
  const { data: ai } = useLive<AIAnalysis>(`/ai/analyze?symbol=${symbol}&timeframe=${tf}`, 30000);
  // the LIVE engine's real state (only polled fast in live mode)
  const { data: positions } = useLive<LedgerPosition[]>("/paper/positions", liveMode ? 5000 : 30000);
  const { data: liveTrades } = useLive<PaperTradeRow[]>("/paper/trades", liveMode ? 8000 : 60000);
  const { data: logs } = useLive<LogRow[]>("/ledger/logs?limit=40", liveMode ? 8000 : 60000);

  // base run: real candles up to NOW + the strategy's no-lookahead read of them.
  // In live mode this refreshes every 2 min; the WebSocket fills the gap between
  // refreshes with tick-by-tick updates of the current candle.
  const loadRun = (silent = false) => {
    if (!silent) { setLoading(true); setSel(null); setPlaying(false); }
    return apiGet<ReplayData>(`/replay/run?symbol=${symbol}&timeframe=${tf}&limit=500&strategy=${encodeURIComponent(strategy)}&source=binance`)
      .then((d) => { if (d?.candles?.length) { setData(d); setIdx(d.candles.length - 1); } else if (!silent) setData(null); })
      .catch(() => { if (!silent) toast("Could not load the bot run", "error"); })
      .finally(() => { if (!silent) setLoading(false); });
  };
  useEffect(() => { loadRun(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [symbol, tf, strategy]);
  useEffect(() => {
    if (!liveMode) return;
    const id = window.setInterval(() => loadRun(true), 120_000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveMode, symbol, tf, strategy]);
  // Keep the chart on the strategy the LIVE ENGINE is actually running, so the
  // "Bot is watching" strip always mirrors the real bot — not a stale default.
  // Follows the engine whenever ITS strategy changes; a manual pick is a
  // temporary override that's released the next time the engine strategy moves.
  const engStratRef = useRef<string | null>(null);
  const userOverrodeStrat = useRef(false);
  useEffect(() => {
    const label = eng?.strategy;
    if (!label) return;
    const mapped = ENGINE_STRAT_MAP[label] ?? "Decision Brain";
    if (mapped !== engStratRef.current) {     // engine strategy changed (or first load)
      engStratRef.current = mapped;
      userOverrodeStrat.current = false;
      if (STRATS.includes(mapped)) setStrategy(mapped);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eng?.strategy]);

  // LIVE candle stream — Binance public kline WebSocket, straight from the
  // browser (no key). Updates the current candle in place and appends on close.
  useEffect(() => {
    if (!liveMode || !CRYPTO.has(symbol)) { setWsOk(false); return; }
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`wss://stream.binance.com:9443/ws/${symbol.toLowerCase()}@kline_${tf}`);
    } catch { setWsOk(false); return; }
    ws.onopen = () => setWsOk(true);
    ws.onerror = () => setWsOk(false);
    ws.onclose = () => setWsOk(false);
    ws.onmessage = (ev) => {
      try {
        const k = JSON.parse(ev.data)?.k;
        if (!k) return;
        const t = new Date(k.t).toISOString().slice(0, 19);
        const bar = { t, o: +k.o, h: +k.h, l: +k.l, c: +k.c, v: +k.v };
        setData((d) => {
          if (!d?.candles?.length) return d;
          const cs = d.candles;
          const last = cs[cs.length - 1];
          const next = last.t.slice(0, 16) === t.slice(0, 16)
            ? [...cs.slice(0, -1), bar]                    // update the forming candle
            : [...cs, bar];                                 // a new candle opened
          return { ...d, candles: next };
        });
        setIdx((i) => i);   // keep cursor; the follow effect below pins to latest
      } catch { /* malformed frame — ignore */ }
    };
    return () => { try { ws?.close(); } catch { /* noop */ } };
  }, [liveMode, symbol, tf]);
  // in live mode the cursor always follows the newest candle
  useEffect(() => {
    if (liveMode && data?.candles?.length) setIdx(data.candles.length - 1);
  }, [liveMode, data]);

  // replay playback (replay mode only)
  useEffect(() => {
    if (!playing || !data || liveMode) return;
    timer.current = window.setInterval(() => {
      setIdx((i) => { if (i >= data.candles.length - 1) { setPlaying(false); return i; } return i + 1; });
    }, Math.max(8, 900 / speed));
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [playing, speed, data, liveMode]);

  const frame = data?.frames?.[Math.min(idx, (data?.frames?.length ?? 1) - 1)];
  const candle = data?.candles?.[idx];
  const runEvents = useMemo(() => (data?.events ?? []).filter((e) => e.idx <= idx).slice(-60).reverse(), [data, idx]);
  const runTrades = useMemo(() => [...(data?.trades ?? [])].reverse(), [data]);
  const rejections = useMemo(() => {
    const out: { idx: number; reason: string }[] = [];
    (data?.frames ?? []).forEach((f, i) => { if (f?.blocked && f.reason && i <= idx) out.push({ idx: i, reason: f.reason }); });
    return out.slice(-8).reverse();
  }, [data, idx]);
  const openPos = useMemo(() => (positions ?? []).find((p) => p.symbol === symbol), [positions, symbol]);
  const inRunTrade = useMemo(() => (data?.trades ?? []).find((t) => t.entry_idx <= idx && (t.exit_idx == null || t.exit_idx > idx)), [data, idx]);
  const atLatest = data ? idx >= data.candles.length - 1 : true;
  const signal = ai?.decision === "BUY" ? "LONG" : ai?.decision === "SELL" ? "SHORT" : ai?.decision ?? "—";
  const ma = ai?.market_analysis;
  const checks = (ai?.checklist ?? []).filter((c) => c.status !== "N/A");

  // ── item #1: the chart shows ONLY what the ACTIVE strategy uses ──
  // driven entirely by the engine-declared viz spec, never hardcoded here.
  const viz = data?.meta?.viz;
  const chartToggles = useMemo<ChartToggles>(() => {
    if (!viz) return FALLBACK_TOGGLES;
    const ov = new Set(viz.overlays ?? []);
    return {
      ema8: ov.has("ema8"), ema20: ov.has("ema20"), ema30: ov.has("ema30"), ema50: ov.has("ema50"),
      sma20: ov.has("sma20"), sma50: ov.has("sma50"), vwap: ov.has("vwap"),
      bb: ov.has("bb_upper") || ov.has("bb"),
      volume: viz.volume ?? true, structure: !!viz.structure, zones: !!viz.zones,
      osc: viz.osc ?? "none", supertrend: !!viz.supertrend, crossovers: !!viz.crossovers,
    };
  }, [viz]);
  const extraLines = useMemo<ExtraLine[]>(() => {
    const out: ExtraLine[] = [];
    (viz?.overlays ?? []).forEach((k, i) => {
      if (KNOWN_OVERLAYS.has(k)) return;
      const name = k.replace(/^ema/, "EMA ").replace(/^sma/, "SMA ").toUpperCase();
      out.push({ key: k, name, color: EXTRA_COLORS[i % EXTRA_COLORS.length], dashed: k.startsWith("sma") });
    });
    return out;
  }, [viz]);
  const liveUPnl = openPos && candle ? (openPos.side === "long" ? candle.c - openPos.entry : openPos.entry - candle.c) * openPos.size : null;
  // in live mode, flag when the chart's strategy differs from the engine's real one
  const engineStrat = eng?.strategy ? ENGINE_STRAT_MAP[eng.strategy] : null;
  const engineTf = eng?.timeframe;
  // Make the terminal the control surface: when a DEPLOYABLE strategy or the
  // timeframe differs from what the live engine runs, offer to reconfigure it.
  const deployTarget = STRAT_TO_ENGINE[strategy];
  const stratNeedsApply = liveMode && !!deployTarget && !!eng?.strategy && eng.strategy !== deployTarget.label;
  const tfNeedsApply = liveMode && !!engineTf && tf !== engineTf;
  const canApplyToBot = !!deployTarget && (stratNeedsApply || tfNeedsApply);
  // non-deployable preset shown against a different live engine strategy
  const chartOnlyMismatch = liveMode && !deployTarget && engineStrat != null && engineStrat !== strategy;
  const applyToBot = async () => {
    if (applying) return;
    const parts = [stratNeedsApply ? deployTarget!.label : null, tfNeedsApply ? tf : null].filter(Boolean);
    const confirmMsg = openPos
      ? `Reconfigure the live engine to ${parts.join(" · ")}? This restarts the engine; your open ${openPos.symbol} position stays open and is re-adopted.`
      : `Reconfigure the live engine to ${parts.join(" · ")}?`;
    if (!window.confirm(confirmMsg)) return;
    setApplying(true);
    try {
      if (stratNeedsApply) await apiPostJson("/strategy/select", { strategy: deployTarget!.key });
      if (tfNeedsApply) await apiPostJson("/engine/timeframe", { timeframe: tf });
      toast(`Live engine now running ${parts.join(" · ")}`, "success");
      refetchEng?.();
    } catch {
      toast("Could not reconfigure the engine — is the backend reachable?", "error");
    } finally {
      setApplying(false);
    }
  };
  // real order blotter — each paper trade is an entry fill (+ an exit fill when
  // closed). These are the actual MARKET orders the engine placed, not invented.
  const orders = useMemo(() => {
    const rows: { t: string | null; symbol: string; side: string; size: number; price: number; status: string }[] = [];
    for (const tr of liveTrades ?? []) {
      rows.push({ t: tr.opened_at, symbol: tr.symbol, side: tr.side === "long" ? "BUY" : "SELL", size: tr.size, price: tr.entry, status: "FILLED" });
      if (tr.closed_at && tr.exit != null)
        rows.push({ t: tr.closed_at, symbol: tr.symbol, side: tr.side === "long" ? "SELL" : "BUY", size: tr.size, price: tr.exit, status: "FILLED" });
    }
    return rows.sort((a, b) => ((a.t ?? "") < (b.t ?? "") ? 1 : -1)).slice(0, 60);
  }, [liveTrades]);
  const tstamp = (s?: string | null) => (s ? s.replace("T", " ").slice(5, 16) : "—");
  const state = liveMode
    ? (openPos ? `Managing a live ${openPos.side.toUpperCase()}` : eng?.running ? "Scanning live market" : "Engine stopped")
    : (inRunTrade ? `Managing an open ${inRunTrade.side.toUpperCase()}` : frame?.blocked ? "Setup rejected" : frame?.trigger ? "Confirmation received" : "Scanning");
  const waiting = liveMode
    ? (openPos ? "stop / target / exit rule" : eng?.running ? `next ${eng?.timeframe ?? tf} candle close` : "engine start")
    : (inRunTrade ? "stop / target / exit rule" : frame?.blocked ? frame.reason : frame?.trigger ? "entry execution" : "a qualifying setup");

  const focusTrade = (t: ReplayTrade) => { setSel(t); setPlaying(false); setMode("replay"); setIdx(t.exit_idx ?? t.entry_idx); };
  // ── "watch how it trades" — step trade-to-trade and see the basis for each ──
  const tradesByEntry = useMemo(() => [...(data?.trades ?? [])].sort((a, b) => a.entry_idx - b.entry_idx), [data]);
  const jumpTrade = (dir: 1 | -1) => {
    if (!tradesByEntry.length) return;
    setMode("replay"); setPlaying(false);
    const found = dir === 1
      ? tradesByEntry.find((t) => t.entry_idx > idx)
      : [...tradesByEntry].reverse().find((t) => t.entry_idx < idx);
    const t = found ?? (dir === 1 ? tradesByEntry[0] : tradesByEntry[tradesByEntry.length - 1]);
    setSel(t); setIdx(t.entry_idx);        // land on the ENTRY candle so the "why" shows
  };
  // one click: drop into replay a few bars before the first entry and play it
  // out at speed — you literally watch the bot take a real trade and why.
  const watchATrade = () => {
    setMode("replay");
    if (!tradesByEntry.length) {
      toast("No qualifying trades in this run — try a lower timeframe (15m) or another symbol.", "info");
      return;
    }
    const t = tradesByEntry[0];
    setSel(t); setSpeed(10); setIdx(Math.max(0, t.entry_idx - 5)); setPlaying(true);
  };
  // item #6: close an open PAPER position through the real execution engine.
  const closePosition = async (po: LedgerPosition) => {
    if (closing) return;
    if (!window.confirm(`Close the ${po.side.toUpperCase()} ${po.symbol} paper position at market?`)) return;
    setClosing(true);
    try {
      const r = await apiPostJson<{ pnl: number; exit_price: number }>("/paper/close",
        { symbol: po.symbol, price: candle?.c });
      toast(`Closed ${po.symbol} @ ${r.exit_price} · ${r.pnl >= 0 ? "+" : ""}${r.pnl} realized`,
        r.pnl >= 0 ? "success" : "info");
    } catch {
      toast("Could not close the position — is the backend reachable?", "error");
    } finally {
      setClosing(false);
    }
  };
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
          <div className="seg-toggle">
            <button className={liveMode ? "on" : ""} onClick={() => setMode("live")}>Live</button>
            <button className={!liveMode ? "on" : ""} onClick={() => { setMode("replay"); setPlaying(false); }}>Replay</button>
          </div>
          <select className="rule-num" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {SYMS.map((s) => <option key={s}>{s}</option>)}
          </select>
          <select className="rule-num" value={strategy} title="Strategy the chart visualizes (follows the live engine by default)"
            onChange={(e) => { setStrategy(e.target.value); userOverrodeStrat.current = true; }}>
            {STRATS.map((s) => <option key={s}>{s}</option>)}
          </select>
          {TFS.map((t) => <button key={t} className={`chip-btn ${tf === t ? "active" : ""}`} onClick={() => setTf(t)}>{t}</button>)}
          <span style={{ width: 10 }} />
          <div className="seg-toggle">
            <button className={!dev ? "on" : ""} onClick={() => setDev(false)}>Normal</button>
            <button className={dev ? "on" : ""} onClick={() => setDev(true)}>Developer</button>
          </div>
        </div>
      </div>

      {/* account bar — real paper-account values */}
      <div className="stat-row" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: 12 }}>
        <StatCard label="Account Balance" value={acct ? `$${acct.current_equity.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : "—"}
          sub={acct ? `initial $${acct.initial_capital.toLocaleString()}` : ""} />
        <StatCard label="Unrealized PnL" value={acct ? `${acct.unrealized_pnl >= 0 ? "+" : "−"}$${Math.abs(acct.unrealized_pnl).toFixed(2)}` : "—"}
          tone={(acct?.unrealized_pnl ?? 0) >= 0 ? "green" : "red"} sub={openPos ? `${openPos.side} ${openPos.symbol}` : "no open position"} />
        <StatCard label="Total Return" value={acct ? `${((acct.current_equity - acct.initial_capital) / acct.initial_capital * 100).toFixed(2)}%`
          : "—"} tone={(acct ? acct.current_equity - acct.initial_capital : 0) >= 0 ? "green" : "red"}
          sub={acct ? `${acct.realized_pnl >= 0 ? "+" : "−"}$${Math.abs(acct.realized_pnl).toFixed(2)} realized` : ""} />
        <StatCard label="Risk / Trade" value={risk?.risk_per_trade_pct != null ? `${(risk.risk_per_trade_pct * 100).toFixed(1)}%` : "—"}
          sub={`${risk?.open_positions ?? 0} of ${risk?.max_open_positions ?? "—"} positions`} />
      </div>

      {data?.meta?.data_warning && (
        <div className="banner" style={{ marginBottom: 10 }}><Icon name="warning" size={14} /> {data.meta.data_warning}</div>
      )}
      {liveMode && !CRYPTO.has(symbol) && (
        <div className="banner" style={{ marginBottom: 10 }}><Icon name="info" size={14} />
          No public stream for {symbol} — live view refreshes from Yahoo every 2 minutes instead of tick-by-tick.</div>
      )}
      {/* live is quiet by design — offer the way to actually SEE a trade + its basis */}
      {liveMode && !openPos && (
        <div className="banner" style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <Icon name="info" size={14} />
          <span style={{ fontSize: 12.5 }}>
            The engine is <b>selective</b> — on {tf} it may not enter for a while, so live can look quiet.
            To watch exactly how <b>{strategy}</b> enters and <b>why</b>, replay it on real candles.
          </span>
          <button className="btn btn-primary btn-sm" style={{ marginLeft: "auto", flexShrink: 0 }} onClick={watchATrade}>
            <Icon name="play" size={12} /> Watch it take a trade</button>
        </div>
      )}

      {/* ── main: chart (70%) + decision engine ─────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 330px", gap: 12 }} className="terminal-main">
        <div className={full ? "chart-full" : ""}>
        <Card title="">
          <div className="toolbar" style={{ marginBottom: 6 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 12.5 }}>
              <b>{symbol}</b><span className="dim">{tf} · {data?.meta?.data_source_label ?? data?.meta?.data_source ?? ""}</span>
              {liveMode && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <span className={`pulse-dot ${wsOk ? "green" : "gold"}`} />
                  <b style={{ fontSize: 11.5, color: wsOk ? "var(--green)" : "var(--gold)" }}>
                    {wsOk ? "LIVE · streaming" : "LIVE · polling"}</b>
                </span>
              )}
              <Badge text={eng?.running ? "engine live" : "engine stopped"} tone={eng?.running ? "green" : "default"} />
              {liveMode && openPos && <Badge text={`live ${openPos.side} open`} tone={openPos.side === "long" ? "green" : "red"} />}
              {!liveMode && inRunTrade && <Badge text={`in ${inRunTrade.side} trade`} tone={inRunTrade.side === "long" ? "green" : "red"} />}
            </div>
            <div className="chips">
              {candle && <b className="mono" style={{ fontSize: 13 }}>{candle.c.toLocaleString()}</b>}
              <span className="dim" style={{ fontSize: 11 }}>{viz?.title ?? "strategy view"} · scroll to zoom</span>
              <button className="chip-btn" title="Fullscreen" onClick={() => setFull((f) => !f)}>
                <Icon name="external" size={12} /> {full ? "Exit" : "Full"}</button>
            </div>
          </div>
          {/* item #1: exactly what the ACTIVE strategy is watching — engine-declared */}
          {viz && (viz.used?.length ?? 0) > 0 && (
            <div className="viz-strip" title={viz.explain}>
              <span className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6 }}>
                <Icon name="chart" size={11} /> {strategy} uses</span>
              {viz.used.map((u) => (
                <span key={u.label} className="viz-chip" title={u.detail}><b>{u.label}</b></span>
              ))}
            </div>
          )}
          {canApplyToBot && (
            <div className="banner" style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <Icon name="info" size={12} />
              <span style={{ fontSize: 11.5 }}>
                You're viewing <b>{strategy}{tfNeedsApply ? ` · ${tf}` : ""}</b>. The live engine is running
                <b> {engineStrat ?? eng?.strategy}{engineTf ? ` · ${engineTf}` : ""}</b>.
              </span>
              <button className="btn btn-primary btn-sm" style={{ marginLeft: "auto", flexShrink: 0 }}
                disabled={applying} onClick={applyToBot}>
                <Icon name="play" size={12} /> {applying ? "Applying…" : "Run this on the bot"}</button>
            </div>
          )}
          {chartOnlyMismatch && (
            <div className="banner" style={{ marginBottom: 8, fontSize: 11.5 }}><Icon name="info" size={12} />
              Chart shows a <b>{strategy}</b> read for comparison — the live engine is running <b>{engineStrat}</b>.
              This preset is a chart-only view; pick a built-in strategy (Decision Brain, Trend Following,
              Supply/Demand or EMA 8/30) to run it on the bot.</div>
          )}
          {loading || !data?.candles?.length ? (
            <div className="dim ta-center" style={{ padding: 120 }}>{loading ? "Loading real candles…" : "No data."}</div>
          ) : (
            <CandleChart data={data} index={idx} toggles={chartToggles} extraLines={extraLines} height={full ? Math.max(420, window.innerHeight - 220) : 548} />
          )}
          {/* replay controls (replay mode) / live info line */}
          {data && !liveMode && (
            <div className="row-actions" style={{ gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
              <button className="btn btn-soft" onClick={() => { setPlaying(false); setIdx(0); }} title="Restart"><Icon name="refresh" size={13} /></button>
              <button className="btn btn-soft" onClick={() => { setPlaying(false); setIdx((i) => Math.max(0, i - 1)); }} title="Step back"><Icon name="skipBack" size={13} /></button>
              <button className="btn btn-primary" onClick={() => setPlaying((p) => !p)}>
                <Icon name={playing ? "pause" : "play"} size={13} /> {playing ? "Pause" : "Replay"}</button>
              <button className="btn btn-soft" onClick={() => { setPlaying(false); setIdx((i) => Math.min((data.candles.length - 1), i + 1)); }} title="Step forward"><Icon name="skipForward" size={13} /></button>
              <span style={{ width: 6 }} />
              <button className="btn btn-soft" disabled={!tradesByEntry.length} onClick={() => jumpTrade(-1)} title="Jump to previous trade">◀ Trade</button>
              <button className="btn btn-soft" disabled={!tradesByEntry.length} onClick={() => jumpTrade(1)} title="Jump to next trade — land on the entry and see why">Trade ▶</button>
              <span className="dim" style={{ fontSize: 11 }}>{tradesByEntry.length} trades</span>
              <span style={{ width: 6 }} />
              <span className="dim" style={{ fontSize: 11 }}>Speed</span>
              {SPEEDS.map((s) => <button key={s} className={`chip-btn ${speed === s ? "active" : ""}`} onClick={() => setSpeed(s)}>{s}x</button>)}
              {!atLatest && <button className="chip-btn" onClick={() => { setSel(null); setPlaying(false); setIdx(data.candles.length - 1); }}>↦ Latest</button>}
              <span className="dim mono" style={{ marginLeft: "auto", fontSize: 11 }}>
                {idx + 1} / {data.candles.length} · {(candle?.t ?? "").replace("T", " ").slice(0, 16)}</span>
            </div>
          )}
          {data && !liveMode && (
            <input type="range" min={0} max={data.candles.length - 1} value={idx}
              onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} style={{ width: "100%", marginTop: 6 }} />
          )}
          {data && liveMode && (
            <div className="row-actions" style={{ gap: 10, alignItems: "center", marginTop: 8, fontSize: 11.5 }}>
              <span className="dim">Watching the live market — the engine acts when a {tf} candle closes.</span>
              <span className="dim mono" style={{ marginLeft: "auto" }}>
                last update {hhmmss(candle?.t)} · {data.candles.length} bars</span>
            </div>
          )}
        </Card>
        </div>

        {/* right panel: Bot Decision Engine / Developer view */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
          {!dev ? (
            <Card title="Bot Decision Engine" subtitle={liveMode ? "live AI reasoning on the current market" : "AI reasoning at the replay cursor"}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span className={`pulse-dot ${openPos || inRunTrade ? "green" : frame?.blocked && !liveMode ? "red" : "gold"}`} />
                <b style={{ fontSize: 13 }}>{state}</b>
                <span className="dim" style={{ fontSize: 11.5, marginLeft: "auto" }}>waiting for: {waiting}</span>
              </div>
              {/* trade signal banner + confidence gauge */}
              <div className={`signal-banner ${signal === "LONG" ? "long" : signal === "SHORT" ? "short" : "wait"}`}>
                <span>TRADE SIGNAL</span><b>{signal}</b>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 14, margin: "10px 0 6px" }}>
                <svg viewBox="0 0 64 64" width="72" height="72">
                  <circle cx="32" cy="32" r="26" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="6" />
                  <circle cx="32" cy="32" r="26" fill="none"
                    stroke={CONF_TONE[ai?.confidence_level ?? ""] === "green" ? "var(--green)" : CONF_TONE[ai?.confidence_level ?? ""] === "red" ? "var(--red)" : "var(--gold)"}
                    strokeWidth="6" strokeLinecap="round" pathLength={100}
                    strokeDasharray={`${ai?.confidence_pct ?? 0} 100`} transform="rotate(-90 32 32)"
                    style={{ transition: "stroke-dasharray 0.6s" }} />
                  <text x="32" y="36" textAnchor="middle" fill="#fff" fontSize="13" fontWeight="700">{ai ? `${ai.confidence_pct}%` : "—"}</text>
                </svg>
                <div style={{ fontSize: 11.5 }} className="dim">Confidence score<br /><b style={{ color: "var(--text)" }}>{ai?.confidence_level ?? "—"}</b></div>
              </div>
              <div className="risk-list" style={{ fontSize: 12.5 }}>
                {kv("Strategy", data?.meta?.strategy ?? eng?.strategy ?? "Decision Brain")}
                {kv("Market Bias", <Badge text={ma?.bias ?? "—"} tone={ma?.bias === "Bullish" ? "green" : ma?.bias === "Bearish" ? "red" : "default"} />)}
                {kv("Trend", `${ma?.trend?.strength_label ?? "—"}`)}
                {kv("Structure", ma?.structure?.state ?? "—")}
                {kv("HTF Bias", frame?.trends ? Object.entries(frame.trends).map(([k, v]) => `${k}:${v}`).join(" ") : "—")}
                {kv("Volatility", ma?.volatility?.label ?? "—")}
                {kv("Liquidity", String(ma?.liquidity?.sweep ?? "—"))}
                {kv("Trade Quality", <span className={(frame?.score ?? 0) >= 60 ? "pos" : "neg"}>{frame ? `${frame.score}/100` : "—"}</span>)}
                {kv("Confidence", <span className={CONF_TONE[ai?.confidence_level ?? ""] === "green" ? "pos" : CONF_TONE[ai?.confidence_level ?? ""] === "red" ? "neg" : ""}>
                  {ai ? `${ai.confidence_pct}% · ${ai.confidence_level}` : "—"}</span>)}
                {kv("Decision", <Badge text={signal} tone={signal === "LONG" ? "green" : signal === "SHORT" ? "red" : "amber"} />)}
              </div>
              {liveMode && openPos && (
                <>
                  <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "12px 0 4px" }}>Live position (real)</div>
                  <div className="risk-list" style={{ fontSize: 12.5 }}>
                    {kv("Side / size", `${openPos.side.toUpperCase()} · ${openPos.size}`)}
                    {kv("Entry", openPos.entry)}
                    {kv("Stop", openPos.stop ?? "—")}
                    {kv("Unrealized", <span className={(liveUPnl ?? 0) >= 0 ? "pos" : "neg"}>
                      {liveUPnl != null ? `${liveUPnl >= 0 ? "+" : "−"}$${Math.abs(liveUPnl).toFixed(2)}` : "—"}</span>)}
                  </div>
                </>
              )}
              {(openPos || ai?.setup) && (
                <>
                  <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "12px 0 4px" }}>Trade details</div>
                  <div className="risk-list" style={{ fontSize: 12.5 }}>
                    {openPos ? (
                      <>
                        {kv("Direction", <Badge text={openPos.side.toUpperCase()} tone={openPos.side === "long" ? "green" : "red"} />)}
                        {kv("Entry", openPos.entry)}
                        {kv("Stop Loss", openPos.stop != null ? `${openPos.stop} (${(((openPos.stop - openPos.entry) / openPos.entry) * 100).toFixed(2)}%)` : "—")}
                        {kv("Position Size", `${openPos.size} ${openPos.symbol.replace(/USDT?$/, "")}`)}
                        {kv("Unrealized", <span className={(liveUPnl ?? 0) >= 0 ? "pos" : "neg"}>
                          {liveUPnl != null ? `${liveUPnl >= 0 ? "+" : "−"}$${Math.abs(liveUPnl).toFixed(2)}` : "—"}</span>)}
                        {kv("Status", <Badge text="OPEN" tone="green" />)}
                        <button className="btn btn-warn btn-sm" style={{ marginTop: 8, width: "100%" }}
                          disabled={closing} onClick={() => closePosition(openPos)}>
                          <Icon name="close" size={13} /> {closing ? "Closing…" : "Close Position"}</button>
                      </>
                    ) : ai?.setup ? (
                      <>
                        {kv("Entry", ai.setup.entry)}
                        {kv("Stop Loss", `${ai.setup.stop} (${(((ai.setup.stop - ai.setup.entry) / ai.setup.entry) * 100).toFixed(2)}%)`)}
                        {kv("Take Profit", `${ai.setup.target} (${(((ai.setup.target - ai.setup.entry) / ai.setup.entry) * 100).toFixed(2)}%)`)}
                        {kv("Risk / Reward", ai.risk_analysis ? `1 : ${ai.risk_analysis.risk_reward}` : "—")}
                        {kv("Status", <Badge text={ai.allowed ? "PROPOSED" : "NOT QUALIFIED"} tone={ai.allowed ? "amber" : "default"} />)}
                      </>
                    ) : null}
                  </div>
                </>
              )}
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "12px 0 4px" }}>Reasoning</div>
              <ul style={{ margin: 0, paddingLeft: 4, listStyle: "none", fontSize: 12.5, lineHeight: 1.7 }}>
                {checks.slice(0, 7).map((c) => (
                  <li key={c.name}><span className={c.status === "PASS" ? "pos" : "neg"}>{c.status === "PASS" ? "✔" : "✘"}</span> {c.name}</li>
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
                <button key={r.idx} className="dev-reject" onClick={() => { setPlaying(false); setMode("replay"); setIdx(r.idx); setSel(null); }}>
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
                {kv("Duration", durationOf(sel))}
                {kv("Exit reason", sel.exit_reason ?? "—")}
                {kv("Risk / trade", risk?.risk_per_trade_pct != null ? `${(risk.risk_per_trade_pct * 100).toFixed(1)}%` : "—")}
              </div>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "10px 0 4px" }}>Why it entered</div>
              <ul style={{ margin: 0, paddingLeft: 4, listStyle: "none", fontSize: 12, lineHeight: 1.7 }}>
                {(sel.entry_reasons ?? []).map((r, i) => <li key={i}><span className="pos">✔</span> {r}</li>)}
              </ul>
              {sel.loss_analysis && <div className="banner" style={{ marginTop: 8, fontSize: 12 }}><Icon name="info" size={12} /> {sel.loss_analysis}</div>}
            </Card>
          )}
        </div>
      </div>

      {/* ── bottom dock: tabbed blotter (positions · history · orders · activity · performance · equity) ── */}
      <div className="dock" style={{ marginTop: 12 }}>
        <div className="dock-tabs">
          {([
            ["positions", "Open Positions", (positions ?? []).length],
            ["history", "Trade History", (liveMode ? (liveTrades ?? []).length : runTrades.length)],
            ["orders", "Orders", orders.length],
            ["activity", "Activity", 0],
            ["performance", "Performance", 0],
            ["equity", "Equity Curve", 0],
          ] as const).map(([k, label, count]) => (
            <button key={k} className={`dock-tab ${dockTab === k ? "on" : ""}`} onClick={() => setDockTab(k)}>
              {label}{count ? <span className="dock-count">{count}</span> : null}
            </button>
          ))}
        </div>
        <div className="dock-body">
          {/* ── Open Positions ── */}
          {dockTab === "positions" && (
            (positions ?? []).length ? (
              <table className="data-table" style={{ fontSize: 12 }}>
                <thead><tr><th>Symbol</th><th>Dir</th><th>Size</th><th>Entry</th><th>Stop</th><th>uPnL</th><th>Status</th><th></th></tr></thead>
                <tbody>
                  {(positions ?? []).map((po) => {
                    const up = po.symbol === symbol && candle ? (po.side === "long" ? candle.c - po.entry : po.entry - candle.c) * po.size : null;
                    return (
                      <tr key={po.id}>
                        <td className="mono">{po.symbol}</td>
                        <td><Badge text={po.side.toUpperCase()} tone={po.side === "long" ? "green" : "red"} /></td>
                        <td className="mono dim">{po.size}</td>
                        <td className="mono">{po.entry}</td>
                        <td className="mono dim">{po.stop ?? "—"}</td>
                        <td className={up == null ? "dim" : up >= 0 ? "pos" : "neg"}>{up == null ? "—" : `${up >= 0 ? "+" : "−"}$${Math.abs(up).toFixed(2)}`}</td>
                        <td><Badge text="OPEN" tone="green" /></td>
                        <td><button className="btn btn-warn btn-sm" disabled={closing} onClick={() => closePosition(po)}>
                          <Icon name="close" size={12} /> Close</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : <div className="dim ta-center" style={{ padding: 26 }}>No open positions — the engine holds nothing right now.</div>
          )}

          {/* ── Trade History ── */}
          {dockTab === "history" && (liveMode ? (
            <table className="data-table" style={{ fontSize: 12 }}>
              <thead><tr><th>Opened</th><th>Symbol</th><th>Dir</th><th>Size</th><th>Entry</th><th>Exit</th><th>PnL</th><th>R</th><th>Status</th></tr></thead>
              <tbody>
                {[...(liveTrades ?? [])].reverse().slice(0, 60).map((t) => (
                  <tr key={t.id}>
                    <td className="mono dim">{tstamp(t.opened_at)}</td>
                    <td className="mono">{t.symbol}</td>
                    <td><Badge text={t.side === "long" ? "LONG" : "SHORT"} tone={t.side === "long" ? "green" : "red"} /></td>
                    <td className="mono dim">{t.size}</td>
                    <td className="mono">{t.entry}</td>
                    <td className="mono dim">{t.exit ?? "open"}</td>
                    <td className={(t.pnl ?? 0) >= 0 ? "pos" : "neg"}>{t.pnl != null ? `${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}` : "—"}</td>
                    <td className={(t.rr ?? 0) >= 0 ? "pos" : "neg"}>{t.rr ?? "—"}</td>
                    <td className={t.status === "closed" ? "dim" : "pos"}>{t.status}</td>
                  </tr>
                ))}
                {!(liveTrades ?? []).length && <tr><td colSpan={9} className="dim ta-center" style={{ padding: 26 }}>
                  No live trades yet — the engine is selective; watch Activity while it scans.</td></tr>}
              </tbody>
            </table>
          ) : (
            <table className="data-table" style={{ fontSize: 12 }}>
              <thead><tr><th>#</th><th>Dir</th><th>Entry</th><th>Exit</th><th>R</th><th>Score</th><th>Duration</th><th>Status</th></tr></thead>
              <tbody>
                {runTrades.map((t) => (
                  <tr key={t.id} style={{ cursor: "pointer" }} className={sel?.id === t.id ? "active-row" : ""} onClick={() => focusTrade(t)}>
                    <td className="dim">{t.id}</td>
                    <td><Badge text={t.side === "long" ? "LONG" : "SHORT"} tone={t.side === "long" ? "green" : "red"} /></td>
                    <td className="mono">{t.entry}</td>
                    <td className="mono dim">{t.exit ?? "open"}</td>
                    <td className={(t.rr ?? 0) >= 0 ? "pos" : "neg"}>{t.rr != null ? `${t.rr >= 0 ? "+" : ""}${t.rr}` : "—"}</td>
                    <td className="dim">{t.score}</td>
                    <td className="dim">{durationOf(t)}</td>
                    <td className={t.result === "win" ? "pos" : t.result === "loss" ? "neg" : "dim"}>{t.result || t.status || "open"}</td>
                  </tr>
                ))}
                {runTrades.length === 0 && <tr><td colSpan={8} className="dim ta-center" style={{ padding: 26 }}>No trades this run — the bot was selective.</td></tr>}
              </tbody>
            </table>
          ))}

          {/* ── Orders (real fills the engine placed) ── */}
          {dockTab === "orders" && (
            orders.length ? (
              <table className="data-table" style={{ fontSize: 12 }}>
                <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Type</th><th>Size</th><th>Fill price</th><th>Status</th></tr></thead>
                <tbody>
                  {orders.map((o, i) => (
                    <tr key={i}>
                      <td className="mono dim">{tstamp(o.t)}</td>
                      <td className="mono">{o.symbol}</td>
                      <td><Badge text={o.side} tone={o.side === "BUY" ? "green" : "red"} /></td>
                      <td className="dim">{"MARKET"}</td>
                      <td className="mono dim">{o.size}</td>
                      <td className="mono">{o.price}</td>
                      <td className="pos">{o.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="dim ta-center" style={{ padding: 26 }}>No orders yet — the engine places a market order on each entry and exit.</div>
          )}

          {/* ── Activity (real engine log / replay timeline) ── */}
          {dockTab === "activity" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {liveMode ? (
                (logs ?? []).length ? (logs ?? []).map((l, i) => (
                  <div key={l.id ?? i} className="tl-row" style={{ cursor: "default" }}>
                    <span className="mono dim" style={{ fontSize: 11, width: 58, flexShrink: 0 }}>{hhmmss(l.ts)}</span>
                    <span className={`tl-dot ${l.level === "error" ? "veto" : l.level === "warning" ? "signal" : "entry"}`} />
                    <Icon name={STAGE_ICON[l.stage] ?? "info"} size={12} className="dim" />
                    <span style={{ fontSize: 12.5 }}>{l.message}</span>
                  </div>
                )) : <div className="dim ta-center" style={{ padding: 26 }}>No live engine activity yet — start the engine from Paper Trading.</div>
              ) : (
                runEvents.length ? runEvents.map((e, i) => (
                  <button key={i} className="tl-row" onClick={() => { setPlaying(false); setIdx(e.idx); setSel(null); }}>
                    <span className="mono dim" style={{ fontSize: 11, width: 44, flexShrink: 0 }}>{hhmm(data?.candles[e.idx]?.t)}</span>
                    <span className={`tl-dot ${e.kind}`} />
                    <Icon name={EVT_ICON[e.kind] ?? "info"} size={12} className="dim" />
                    <span style={{ fontSize: 12.5 }}>{e.text}</span>
                  </button>
                )) : <div className="dim ta-center" style={{ padding: 26 }}>No activity up to this candle.</div>
              )}
            </div>
          )}

          {/* ── Performance (this run) ── */}
          {dockTab === "performance" && (
            <div className="stat-row" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
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
          )}

          {/* ── Equity Curve (real realized paper equity) ── */}
          {dockTab === "equity" && (
            <div>
              <div className="dim" style={{ fontSize: 11.5, marginBottom: 6 }}>
                {acct ? `balance $${acct.current_equity.toLocaleString(undefined, { maximumFractionDigits: 2 })} · ${((acct.current_equity - acct.initial_capital) / acct.initial_capital * 100).toFixed(2)}% total return` : "realized paper equity"}
              </div>
              <EquityCurve />
            </div>
          )}
        </div>
      </div>

      {/* ── live status bar (real fields only — nothing invented) ── */}
      <div className="term-status">
        <span><span className="dim">Mode</span> {liveMode ? (wsOk ? "LIVE · WS stream" : "LIVE · REST poll") : "replay"}</span>
        <span><span className="dim">Data</span> {data?.meta?.data_source_label ?? data?.meta?.data_source ?? "—"}</span>
        <span><span className="dim">Feed</span> <span className={eng?.running ? "pos" : "dim"}>{(eng as any)?.feed_status ?? (eng?.running ? "running" : "stopped")}</span></span>
        <span><span className="dim">Bars</span> {data?.candles?.length ?? 0}</span>
        <span><span className="dim">Last candle</span> {hhmmss(data?.candles?.[data.candles.length - 1]?.t) || "—"}</span>
        <span><span className="dim">Strategy</span> {data?.meta?.debug?.strategy_id ?? data?.meta?.strategy ?? "—"}</span>
        <span style={{ marginLeft: "auto" }}><span className={`pulse-dot ${eng?.running ? "green" : "dim"}`} /> {eng?.running ? "engine analysing" : "engine idle"}</span>
      </div>
    </div>
  );
}
