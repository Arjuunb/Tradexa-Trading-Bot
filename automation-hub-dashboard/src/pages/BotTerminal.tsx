import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import CandleChart, { type ChartToggles, type ExtraLine, type GridLine } from "../components/replay/CandleChart";
import { Badge, StatCard } from "../components/common/ui";
import EquityCurve from "../components/chart/EquityCurve";
import { useApp } from "../app-context";
import {
  apiGet, apiPost, apiPostJson, useLive,
  type ReplayData, type AIAnalysis, type EngineStatus, type RiskSummary, type StrategyPerformance,
  type LedgerPosition, type PaperTradeRow, type LogRow, type PaperAccount, type SymbolRow,
} from "../lib/api";

/** Bot Terminal — a LIVE, crypto-first paper-trading observation lab.
 *  Candles stream tick-by-tick from Binance's public WebSocket (straight into
 *  the browser, like TradingView); the panels show the LIVE engine's real open
 *  position, real trades, real orders and real activity. No historical replay,
 *  no demo data — every value is a real engine / market read. */

// Intraday-first: an automated strategy belongs on low timeframes (1–5m); the
// higher ones (1h/4h) suit manual swing trading and are kept for those who want it.
const TFS = ["1m", "3m", "5m", "15m", "1h", "4h"];
const LIMIT = 500;   // live candles loaded for context (warmup fetched behind them)
// A Binance-streamable crypto pair (USDT/USDC/BUSD quote). Forex/commodity USD
// pairs (EURUSD, XAUUSD) end in a plain "USD" and are NOT streamed here.
const isCryptoStreamable = (s: string) => /(USDT|USDC|BUSD)$/i.test(s);
// Strategies the terminal can visualize (each maps to a real entry engine).
const STRATS = ["Decision Brain", "Trend Following", "Supply/Demand", "EMA 8/30",
  "EMA 20/50", "Breakout Retest", "Support/Resistance Rejection", "Liquidity Sweep"];
// The live engine labels its strategy differently from the presets — map it so
// the terminal defaults to the strategy the engine is actually running.
const ENGINE_STRAT_MAP: Record<string, string> = {
  "Decision Brain": "Decision Brain", "Supertrend": "Trend Following",
  "SMC (Smart Money)": "Supply/Demand", "EMA Crossover": "EMA 8/30",
  "Donchian Breakout": "Decision Brain", "Confirmation Ensemble": "Decision Brain",
};
// The reverse: presets that map to a real built-in engine strategy, so selecting
// them here can reconfigure the live bot. Others are chart-only views.
const STRAT_TO_ENGINE: Record<string, { key: string; label: string }> = {
  "Decision Brain": { key: "brain", label: "Decision Brain" },
  "Trend Following": { key: "supertrend", label: "Supertrend" },
  "Supply/Demand": { key: "smc", label: "SMC (Smart Money)" },
  "EMA 8/30": { key: "ema", label: "EMA Crossover" },
};
// Fallback only — used if the backend didn't send a viz spec. Normally the chart
// is driven entirely by data.meta.viz (the ACTIVE strategy's real inputs).
const FALLBACK_TOGGLES: ChartToggles = {
  ema8: false, ema20: false, ema30: false, ema50: false,
  sma20: false, sma50: false, vwap: false, bb: false,
  volume: true, structure: true, zones: true, osc: "none", supertrend: false, crossovers: false,
};
const KNOWN_OVERLAYS = new Set(["ema8", "ema20", "ema30", "ema50", "sma20", "sma50",
  "vwap", "bb_upper", "bb_mid", "bb_lower", "supertrend"]);
const EXTRA_COLORS = ["#22d3ee", "#a855f7", "#f59e0b", "#3b82f6", "#ec4899", "#10b981"];
const CONF_TONE: Record<string, string> = { "Very High": "green", High: "green", Medium: "amber", Low: "red", "Very Low": "red" };
const STAGE_ICON: Record<string, string> = { engine: "robot", execution: "play", brain: "bot", risk: "shield",
  controls: "settings", webhook: "external", account: "wallet", market: "globe", bots: "robot" };
const hhmmss = (t?: string) => (t ? t.slice(11, 19) || t.slice(0, 8) : "");

/** Search-any-symbol picker — queries the full multi-asset universe
 *  (/symbols/search). Live tick streaming is crypto-only; non-crypto refreshes
 *  every ~2 min. Picks the compact ticker (BTCUSDT / AAPL). */
function SymbolSearch({ value, onPick }: { value: string; onPick: (t: string) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SymbolRow[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    if (!q.trim()) { setResults([]); return; }
    timer.current = window.setTimeout(() => {
      apiGet<{ results: SymbolRow[] }>(`/symbols/search?q=${encodeURIComponent(q)}&limit=10`)
        .then((r) => setResults(r.results ?? [])).catch(() => setResults([]));
    }, 180);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [q]);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  const pick = (t: string) => { onPick(t); setOpen(false); setQ(""); };
  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <button className="rule-num" style={{ minWidth: 96, textAlign: "left", cursor: "pointer" }}
        title="Search any symbol" onClick={() => setOpen((o) => !o)}>{value} ▾</button>
      {open && (
        <div className="sym-pop">
          <input autoFocus className="sym-search" placeholder="Search symbol or name…"
            value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="sym-results">
            {results.map((r) => {
              const crypto = r.asset_class === "crypto";
              // A Binance USDT-M perpetual is a USDT/USDC-quoted crypto pair
              // (BTCUSDT, ETHUSDT). Detect by the pair's quote, not the catalog's
              // spot/futures label — that label is unreliable when the live
              // exchange sync is blocked and only the seed (all "spot") is left.
              const perp = crypto && isCryptoStreamable(r.ticker);
              const tag = perp ? "perp" : crypto ? "USDT perp only" : "crypto only";
              return (
                <button key={r.symbol} className={`sym-row ${perp ? "" : "off"}`} disabled={!perp}
                  title={perp ? "" : crypto
                    ? "Only USDT-margined perpetuals stream here (e.g. BTCUSDT)"
                    : "Live streaming is crypto perpetual futures only"}
                  onClick={() => perp && pick(r.ticker)}>
                  <b>{r.ticker}</b><span className="dim sym-nm">{r.name}</span>
                  <span className="sym-cls">{tag}</span>
                </button>
              );
            })}
            {q.trim() && !results.length && <div className="dim" style={{ padding: 9, fontSize: 12 }}>No matches.</div>}
            {!q.trim() && <div className="dim" style={{ padding: 9, fontSize: 11.5 }}>Type a ticker — crypto perpetual futures only (e.g. BTC, ETH, SOL).</div>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function BotTerminalPage() {
  const { toast } = useApp();
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [tf, setTf] = useState("5m");
  const [strategy, setStrategy] = useState("Decision Brain");
  const [dev, setDev] = useState(false);
  const [data, setData] = useState<ReplayData | null>(null);
  const [idx, setIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [full, setFull] = useState(false);
  const [wsOk, setWsOk] = useState(false);
  const [closing, setClosing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [dockTab, setDockTab] = useState<"positions" | "history" | "orders" | "activity" | "performance" | "equity">("positions");
  const [gridOn, setGridOn] = useState(false);
  const [leverage, setLeverage] = useState(1);
  const [grid, setGrid] = useState({ upper: 0, lower: 0, levels: 20, geo: false, investment: 1000 });

  const { data: eng, refetch: refetchEng } = useLive<EngineStatus>("/engine/status", 5000);
  const { data: risk } = useLive<RiskSummary>("/risk/summary", 10000);
  const { data: acct } = useLive<PaperAccount>("/paper/account", 8000);
  const { data: ai } = useLive<AIAnalysis>(`/ai/analyze?symbol=${symbol}&timeframe=${tf}`, 30000);
  const { data: positions } = useLive<LedgerPosition[]>("/paper/positions", 5000);
  const { data: liveTrades } = useLive<PaperTradeRow[]>("/paper/trades", 8000);
  const { data: logs } = useLive<LogRow[]>("/ledger/logs?limit=40", 8000);
  const { data: perf } = useLive<StrategyPerformance>("/strategy/performance", 10000);

  const streaming = isCryptoStreamable(symbol);

  // Load real candles up to NOW + the strategy's causal read of them. Refreshes
  // every 2 min; the WebSocket fills the gap with tick-by-tick current-candle
  // updates. source=binance + real-data-only — never demo/synthetic.
  const loadRun = (silent = false) => {
    if (!silent) setLoading(true);
    return apiGet<ReplayData>(`/replay/run?symbol=${symbol}&timeframe=${tf}&limit=${LIMIT}&strategy=${encodeURIComponent(strategy)}&source=binance`)
      .then((d) => { if (d?.candles?.length) { setData(d); setIdx(d.candles.length - 1); } else if (!silent) setData(null); })
      .catch(() => { if (!silent) toast("Could not load live candles", "error"); })
      .finally(() => { if (!silent) setLoading(false); });
  };
  useEffect(() => { loadRun(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [symbol, tf, strategy]);
  useEffect(() => {
    const id = window.setInterval(() => loadRun(true), 120_000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, tf, strategy]);
  // Keep the chart on the strategy the LIVE ENGINE is actually running, so the
  // "…uses" strip always mirrors the real bot. A manual pick is a temporary
  // override, released the next time the engine's strategy changes.
  const engStratRef = useRef<string | null>(null);
  const userOverrodeStrat = useRef(false);
  useEffect(() => {
    const label = eng?.strategy;
    if (!label) return;
    const mapped = ENGINE_STRAT_MAP[label] ?? "Decision Brain";
    if (mapped !== engStratRef.current) {
      engStratRef.current = mapped;
      userOverrodeStrat.current = false;
      if (STRATS.includes(mapped)) setStrategy(mapped);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eng?.strategy]);

  // LIVE candle stream — Binance USDT-M FUTURES (perpetual) public kline
  // WebSocket, from the browser (no key). Updates the current candle in place
  // and appends on close. Perp market, not spot.
  useEffect(() => {
    if (!streaming) { setWsOk(false); return; }
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`wss://fstream.binance.com/ws/${symbol.toLowerCase()}@kline_${tf}`);
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
      } catch { /* malformed frame — ignore */ }
    };
    return () => { try { ws?.close(); } catch { /* noop */ } };
  }, [symbol, tf, streaming]);
  // the cursor always follows the newest candle
  useEffect(() => { if (data?.candles?.length) setIdx(data.candles.length - 1); }, [data]);

  const frame = data?.frames?.[Math.min(idx, (data?.frames?.length ?? 1) - 1)];
  const candle = data?.candles?.[idx];
  const openPos = useMemo(() => (positions ?? []).find((p) => p.symbol === symbol), [positions, symbol]);
  const signal = ai?.decision === "BUY" ? "LONG" : ai?.decision === "SELL" ? "SHORT" : ai?.decision ?? "—";
  const ma = ai?.market_analysis;
  const checks = (ai?.checklist ?? []).filter((c) => c.status !== "N/A");

  // the chart shows ONLY what the ACTIVE strategy uses — engine-declared viz spec
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

  // ── Grid tester: overlay a configurable grid on the LIVE price + exact math ──
  const centerGrid = () => {
    if (!candle) return;
    setGrid((g) => ({ ...g, upper: +(candle.c * 1.03).toFixed(2), lower: +(candle.c * 0.97).toFixed(2) }));
  };
  const setG = (k: keyof typeof grid, v: number | boolean) => setGrid((g) => ({ ...g, [k]: v }));
  const gridData = useMemo(() => {
    if (!gridOn || !candle) return null;
    const { lower, upper, levels, geo, investment } = grid;
    if (levels < 2 || lower <= 0 || upper <= lower) return { lines: [] as GridLine[], m: null };
    const prices: number[] = [];
    if (geo) { const r = Math.pow(upper / lower, 1 / (levels - 1)); for (let i = 0; i < levels; i++) prices.push(lower * Math.pow(r, i)); }
    else { const step = (upper - lower) / (levels - 1); for (let i = 0; i < levels; i++) prices.push(lower + i * step); }
    const cur = candle.c;
    const lines: GridLine[] = prices.map((p, i) => ({ price: +p.toFixed(2), side: p < cur ? "buy" : "sell", edge: i === 0 || i === levels - 1 }));
    const fee = 0.04;
    const gapPct = geo ? (Math.pow(upper / lower, 1 / (levels - 1)) - 1) * 100 : (((upper - lower) / (levels - 1)) / cur) * 100;
    const netPct = gapPct - 2 * fee;
    const orderValue = (investment / levels) * leverage;   // leverage scales exposure
    const profitPerGrid = (orderValue * netPct) / 100;
    const liq = leverage > 1 ? cur * (1 - 1 / leverage) : null;  // rough long liquidation
    const inRange = cur >= lower && cur <= upper;
    return { lines, m: { gapPct, netPct, orderValue, profitPerGrid, liq, inRange,
      buys: lines.filter((l) => l.side === "buy").length, sells: lines.filter((l) => l.side === "sell").length,
      exposure: investment * leverage } };
  }, [gridOn, candle, grid, leverage]);

  // Make the terminal the control surface: when a DEPLOYABLE strategy or the
  // timeframe differs from what the live engine runs, offer to reconfigure it.
  const engineStrat = eng?.strategy ? ENGINE_STRAT_MAP[eng.strategy] : null;
  const engineTf = eng?.timeframe;
  const deployTarget = STRAT_TO_ENGINE[strategy];
  const stratNeedsApply = !!deployTarget && !!eng?.strategy && eng.strategy !== deployTarget.label;
  const tfNeedsApply = !!engineTf && tf !== engineTf;
  const canApplyToBot = !!deployTarget && (stratNeedsApply || tfNeedsApply);
  const chartOnlyMismatch = !deployTarget && engineStrat != null && engineStrat !== strategy;
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
      if (tfNeedsApply) await apiPost(`/engine/timeframe?timeframe=${encodeURIComponent(tf)}`);
      toast(`Live engine now running ${parts.join(" · ")}`, "success");
      refetchEng?.();
    } catch {
      toast("Could not reconfigure the engine — is the backend reachable?", "error");
    } finally {
      setApplying(false);
    }
  };
  // real order blotter — each paper trade is an entry fill (+ an exit fill when
  // closed). These are the actual MARKET orders the engine placed.
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
  const state = openPos ? `Managing a live ${openPos.side.toUpperCase()}` : eng?.running ? "Scanning live market" : "Engine stopped";
  const waiting = openPos ? "stop / target / exit rule" : eng?.running ? `next ${eng?.timeframe ?? tf} candle close` : "engine start";

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
  const kv = (label: string, value: ReactNode) => (
    <div className="risk-item"><span className="dim">{label}</span><b>{value}</b></div>);

  return (
    <div className="terminal">
      {/* ── header strip ─────────────────────────────────────────── */}
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <h1 className="pagehead-title" style={{ margin: 0, fontSize: 19 }}>Bot Terminal</h1>
          <span className="dim" style={{ fontSize: 11.5 }}>live crypto · paper trading · every value is a real engine read</span>
        </div>
        <div className="chips" style={{ alignItems: "center" }}>
          <SymbolSearch value={symbol} onPick={setSymbol} />
          <select className="rule-num" value={strategy} title="Strategy the chart visualizes (follows the live engine by default)"
            onChange={(e) => { setStrategy(e.target.value); userOverrodeStrat.current = true; }}>
            {STRATS.map((s) => <option key={s}>{s}</option>)}
          </select>
          {TFS.map((t) => <button key={t} className={`chip-btn ${tf === t ? "active" : ""}`} onClick={() => setTf(t)}>{t}</button>)}
          <span style={{ width: 10 }} />
          <div className="seg-toggle">
            <button className={!gridOn ? "on" : ""} onClick={() => setGridOn(false)}>Strategy</button>
            <button className={gridOn ? "on" : ""} onClick={() => { setGridOn(true); if (grid.upper <= grid.lower) centerGrid(); }}>Grid</button>
          </div>
          <select className="rule-num" value={leverage} title="Leverage (perp)" onChange={(e) => setLeverage(Number(e.target.value))}>
            {[1, 2, 3, 5, 10, 20].map((x) => <option key={x} value={x}>{x}×</option>)}
          </select>
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

      {!streaming && (
        <div className="banner" style={{ marginBottom: 10 }}><Icon name="info" size={14} />
          The terminal streams crypto perpetual futures. {symbol} isn't a crypto perp, so the chart
          refreshes about every 2 minutes instead of tick-by-tick.</div>
      )}

      {/* ── main: chart + decision engine ─────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 330px", gap: 12 }} className="terminal-main">
        <div className={full ? "chart-full" : ""}>
        <Card title="">
          <div className="toolbar" style={{ marginBottom: 6 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 12.5 }}>
              <b>{symbol}</b><span className="dim">{tf} · Binance Perp</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span className={`pulse-dot ${wsOk ? "green" : "gold"}`} />
                <b style={{ fontSize: 11.5, color: wsOk ? "var(--green)" : "var(--gold)" }}>
                  {wsOk ? "LIVE · streaming" : "LIVE · polling"}</b>
              </span>
              <Badge text={eng?.running ? "engine live" : "engine stopped"} tone={eng?.running ? "green" : "default"} />
              {openPos && <Badge text={`live ${openPos.side} open`} tone={openPos.side === "long" ? "green" : "red"} />}
            </div>
            <div className="chips">
              {candle && <b className="mono" style={{ fontSize: 13 }}>{candle.c.toLocaleString()}</b>}
              <span className="dim" style={{ fontSize: 11 }}>{viz?.title ?? "strategy view"} · scroll to zoom</span>
              <button className="chip-btn" title="Fullscreen" onClick={() => setFull((f) => !f)}>
                <Icon name="external" size={12} /> {full ? "Exit" : "Full"}</button>
            </div>
          </div>
          {/* Grid config strip (Grid mode) OR what the active strategy uses */}
          {gridOn ? (
            <div className="viz-strip grid-strip">
              <span className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6 }}>
                <Icon name="chart" size={11} /> Grid</span>
              <label className="gcfg">Lower<input type="number" value={grid.lower} onChange={(e) => setG("lower", Number(e.target.value))} /></label>
              <label className="gcfg">Upper<input type="number" value={grid.upper} onChange={(e) => setG("upper", Number(e.target.value))} /></label>
              <label className="gcfg">Levels<input type="number" min={2} value={grid.levels} onChange={(e) => setG("levels", Math.max(2, Number(e.target.value) || 2))} /></label>
              <label className="gcfg">USDT<input type="number" value={grid.investment} onChange={(e) => setG("investment", Number(e.target.value))} /></label>
              <button className={`chip-btn ${grid.geo ? "active" : ""}`} onClick={() => setG("geo", !grid.geo)}>{grid.geo ? "Geometric" : "Arithmetic"}</button>
              <button className="chip-btn" onClick={centerGrid} title="Set range to ±3% of live price"><Icon name="target" size={11} /> Center</button>
              {gridData?.m && <span className="dim" style={{ marginLeft: "auto", fontSize: 11 }}>{gridData.m.buys} buy / {gridData.m.sells} sell · step {gridData.m.gapPct.toFixed(2)}%</span>}
            </div>
          ) : viz && (viz.used?.length ?? 0) > 0 && (
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
            <div className="dim ta-center" style={{ padding: 120 }}>
              {loading ? "Connecting to live Binance data…" : "Waiting for live data — check the engine feed in the status bar."}</div>
          ) : (
            <CandleChart data={data} index={idx} toggles={chartToggles} extraLines={extraLines} gridLines={gridData?.lines} height={full ? Math.max(420, window.innerHeight - 220) : 548} />
          )}
          {data && (
            <div className="row-actions" style={{ gap: 10, alignItems: "center", marginTop: 8, fontSize: 11.5 }}>
              <span className="dim">Watching the live market — the engine acts when a {tf} candle closes.</span>
              <span className="dim mono" style={{ marginLeft: "auto" }}>
                last update {hhmmss(candle?.t)} · {data.candles.length} bars</span>
            </div>
          )}
        </Card>
        </div>

        {/* right panel: Grid Tester (grid mode) + Bot Decision Engine / Developer view */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
          {gridOn && (
            <Card title="Grid Tester" subtitle={`live · ${grid.levels} levels · ${leverage}× leverage`}>
              {gridData?.m ? (
                <>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <Badge text={gridData.m.inRange ? "PRICE IN RANGE" : "PRICE OUT OF RANGE"} tone={gridData.m.inRange ? "green" : "amber"} />
                    <span className="dim" style={{ fontSize: 11.5, marginLeft: "auto" }}>{candle ? candle.c.toLocaleString() : "—"}</span>
                  </div>
                  <div className="risk-list" style={{ fontSize: 12.5 }}>
                    {kv("Profit / grid", <span className={gridData.m.netPct > 0 ? "pos" : "neg"}>{`$${gridData.m.profitPerGrid.toFixed(2)} · ${gridData.m.netPct.toFixed(2)}%`}</span>)}
                    {kv("Grid step", `${gridData.m.gapPct.toFixed(2)}%`)}
                    {kv("Order / grid", `$${gridData.m.orderValue.toFixed(2)}`)}
                    {kv("Exposure", `$${gridData.m.exposure.toLocaleString()} (${leverage}×)`)}
                    {kv("Buy / sell levels", `${gridData.m.buys} / ${gridData.m.sells}`)}
                    {kv("Est. liquidation", gridData.m.liq != null ? <span className="neg">{gridData.m.liq.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span> : "— (1×)")}
                  </div>
                  {gridData.m.netPct <= 0 && <div className="banner" style={{ marginTop: 8, fontSize: 11.5 }}><Icon name="warning" size={12} /> Grid step is below round-trip fees — every grid loses. Widen range or use fewer levels.</div>}
                  <div className="banner" style={{ marginTop: 8, fontSize: 11 }}><Icon name="info" size={12} />
                    Overlay & math are exact on the live price. Est. liquidation is a rough perp estimate; leverage scales exposure, not the live engine.</div>
                </>
              ) : <div className="dim" style={{ fontSize: 12, padding: 8 }}>Set a valid range (lower &lt; price &lt; upper) and ≥ 2 levels, or press <b>Center</b>.</div>}
            </Card>
          )}
          {!dev ? (
            <Card title="Bot Decision Engine" subtitle="live AI reasoning on the current market">
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span className={`pulse-dot ${openPos ? "green" : "gold"}`} />
                <b style={{ fontSize: 13 }}>{state}</b>
                <span className="dim" style={{ fontSize: 11.5, marginLeft: "auto" }}>waiting for: {waiting}</span>
              </div>
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
              {openPos ? (
                <>
                  <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "12px 0 4px" }}>Trade details (live position)</div>
                  <div className="risk-list" style={{ fontSize: 12.5 }}>
                    {kv("Direction", <Badge text={openPos.side.toUpperCase()} tone={openPos.side === "long" ? "green" : "red"} />)}
                    {kv("Entry", openPos.entry)}
                    {kv("Stop Loss", openPos.stop != null ? `${openPos.stop} (${(((openPos.stop - openPos.entry) / openPos.entry) * 100).toFixed(2)}%)` : "—")}
                    {kv("Position Size", `${openPos.size} ${openPos.symbol.replace(/USDT?$/, "")}`)}
                    {kv("Unrealized", <span className={(liveUPnl ?? 0) >= 0 ? "pos" : "neg"}>
                      {liveUPnl != null ? `${liveUPnl >= 0 ? "+" : "−"}$${Math.abs(liveUPnl).toFixed(2)}` : "—"}</span>)}
                    {kv("Status", <Badge text="OPEN" tone="green" />)}
                  </div>
                  <button className="btn btn-warn btn-sm" style={{ marginTop: 8, width: "100%" }}
                    disabled={closing} onClick={() => closePosition(openPos)}>
                    <Icon name="close" size={13} /> {closing ? "Closing…" : "Close Position"}</button>
                </>
              ) : ai?.setup ? (
                <>
                  <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "12px 0 4px" }}>Proposed setup</div>
                  <div className="risk-list" style={{ fontSize: 12.5 }}>
                    {kv("Entry", ai.setup.entry)}
                    {kv("Stop Loss", `${ai.setup.stop} (${(((ai.setup.stop - ai.setup.entry) / ai.setup.entry) * 100).toFixed(2)}%)`)}
                    {kv("Take Profit", `${ai.setup.target} (${(((ai.setup.target - ai.setup.entry) / ai.setup.entry) * 100).toFixed(2)}%)`)}
                    {kv("Risk / Reward", ai.risk_analysis ? `1 : ${ai.risk_analysis.risk_reward}` : "—")}
                    {kv("Status", <Badge text={ai.allowed ? "PROPOSED" : "NOT QUALIFIED"} tone={ai.allowed ? "amber" : "default"} />)}
                  </div>
                </>
              ) : null}
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, margin: "12px 0 4px" }}>Reasoning</div>
              <ul style={{ margin: 0, paddingLeft: 4, listStyle: "none", fontSize: 12.5, lineHeight: 1.7 }}>
                {checks.slice(0, 7).map((c) => (
                  <li key={c.name}><span className={c.status === "PASS" ? "pos" : "neg"}>{c.status === "PASS" ? "✔" : "✘"}</span> {c.name}</li>
                ))}
                {!checks.length && <li className="dim">Analysing…</li>}
              </ul>
            </Card>
          ) : (
            <Card title="Developer View" subtitle="brain state · latest candle">
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
            </Card>
          )}
        </div>
      </div>

      {/* ── bottom dock: live blotter ── */}
      <div className="dock" style={{ marginTop: 12 }}>
        <div className="dock-tabs">
          {([
            ["positions", "Open Positions", (positions ?? []).length],
            ["history", "Trade History", (liveTrades ?? []).length],
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

          {/* ── Trade History (real live paper trades) ── */}
          {dockTab === "history" && (
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
          )}

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

          {/* ── Activity (real engine log) ── */}
          {dockTab === "activity" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {(logs ?? []).length ? (logs ?? []).map((l, i) => (
                <div key={l.id ?? i} className="tl-row" style={{ cursor: "default" }}>
                  <span className="mono dim" style={{ fontSize: 11, width: 58, flexShrink: 0 }}>{hhmmss(l.ts)}</span>
                  <span className={`tl-dot ${l.level === "error" ? "veto" : l.level === "warning" ? "signal" : "entry"}`} />
                  <Icon name={STAGE_ICON[l.stage] ?? "info"} size={12} className="dim" />
                  <span style={{ fontSize: 12.5 }}>{l.message}</span>
                </div>
              )) : <div className="dim ta-center" style={{ padding: 26 }}>No live engine activity yet — start the engine from Paper Trading.</div>}
            </div>
          )}

          {/* ── Performance (the engine's real live track record) ── */}
          {dockTab === "performance" && (
            <div className="stat-row" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
              <StatCard label="Win Rate" value={perf ? `${(perf.win_rate ?? 0).toFixed(1)}%` : "—"} tone={(perf?.win_rate ?? 0) >= 50 ? "green" : "amber"} />
              <StatCard label="Profit Factor" value={perf ? (perf.profit_factor ?? 0).toFixed(2) : "—"} tone={(perf?.profit_factor ?? 0) >= 1 ? "green" : "red"} />
              <StatCard label="Realized P&L" value={perf ? `${(perf.realized_pnl ?? 0) >= 0 ? "+" : "−"}$${Math.abs(perf.realized_pnl ?? 0).toFixed(2)}` : "—"}
                tone={(perf?.realized_pnl ?? 0) >= 0 ? "green" : "red"} />
              <StatCard label="Max Drawdown" value={perf ? `${(perf.max_drawdown_pct ?? 0).toFixed(1)}%` : "—"} tone="amber" />
              <StatCard label="Trades" value={perf ? String(perf.trades ?? 0) : "—"} sub="closed" />
              <StatCard label="Balance" value={perf ? `$${(perf.balance ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : "—"} />
              <StatCard label="Worst Streak" value={perf ? String(perf.longest_losing_streak ?? 0) : "—"} sub="losses in a row" />
              <StatCard label="Strategy" value={perf?.strategy ?? eng?.strategy ?? "—"} />
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
        <span><span className="dim">Mode</span> {wsOk ? "LIVE · WS stream" : "LIVE · REST poll"}</span>
        <span><span className="dim">Data</span> Binance Futures (perp)</span>
        <span><span className="dim">Feed</span> <span className={eng?.running ? "pos" : "dim"}>{(eng as any)?.feed_status ?? (eng?.running ? "running" : "stopped")}</span></span>
        <span><span className="dim">Bars</span> {data?.candles?.length ?? 0}</span>
        <span><span className="dim">Last candle</span> {hhmmss(data?.candles?.[data.candles.length - 1]?.t) || "—"}</span>
        <span><span className="dim">Strategy</span> {data?.meta?.debug?.strategy_id ?? data?.meta?.strategy ?? "—"}</span>
        <span style={{ marginLeft: "auto" }}><span className={`pulse-dot ${eng?.running ? "green" : "dim"}`} /> {eng?.running ? "engine analysing" : "engine idle"}</span>
      </div>
    </div>
  );
}
