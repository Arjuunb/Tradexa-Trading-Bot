import { useEffect, useRef, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader } from "../components/common/ui";
import CandleChart from "../components/replay/CandleChart";
import { useApp } from "../app-context";
import { apiGet, type ReplayData, type ReplayFrame, type ReplayTrade } from "../lib/api";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"];
const SPEEDS = [1, 2, 5, 10, 25];
const trendTone = (v?: string) => (v === "Bullish" ? "green" : v === "Bearish" ? "red" : "default");

export default function ReplayPage() {
  const app = useApp();
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [tf, setTf] = useState("15m");
  const [limit, setLimit] = useState(800);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [data, setData] = useState<ReplayData | null>(null);
  const [loading, setLoading] = useState(false);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const timer = useRef<number | null>(null);

  const load = async () => {
    setLoading(true); setPlaying(false);
    try {
      let q = `/replay/run?symbol=${symbol}&timeframe=${tf}&limit=${limit}`;
      if (startDate) q += `&start=${startDate}`;
      if (endDate) q += `&end=${endDate}`;
      const r = await apiGet<ReplayData>(q);
      if (r.meta.bars === 0) { app.toast("No data in that date range — try another window.", "info"); }
      setData(r); setIdx(0);
    } catch { app.toast("Replay failed — backend reachable?", "error"); }
    finally { setLoading(false); }
  };

  // playback loop
  useEffect(() => {
    if (!playing || !data) return;
    const ms = Math.max(40, 600 / speed);
    timer.current = window.setInterval(() => {
      setIdx((i) => {
        if (i >= data.candles.length - 1) { setPlaying(false); return i; }
        return i + 1;
      });
    }, ms);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [playing, speed, data]);

  const frame: ReplayFrame | null = data ? data.frames[idx] ?? null : null;
  const candle = data?.candles[idx];
  const visibleEvents = data ? data.events.filter((e) => e.idx <= idx).slice(-14).reverse() : [];
  const active = data?.trades.find((t) => t.entry_idx <= idx && (t.exit_idx === null || t.exit_idx > idx));
  const lastClosed = data ? [...data.trades].reverse().find((t) => t.exit_idx !== null && t.exit_idx <= idx) : undefined;

  // live RR + status on the active trade
  let liveRR: number | null = null;
  if (active && candle) {
    const risk = Math.abs(active.entry - active.sl);
    const move = active.side === "long" ? candle.c - active.entry : active.entry - candle.c;
    liveRR = risk > 0 ? Math.round((move / risk) * 100) / 100 : null;
  }
  const tradeStatus = active
    ? (active.tp1_idx !== null && active.tp1_idx <= idx ? "Partial TP / Break-even" : "Open")
    : null;

  return (
    <>
      <PageHeader title="Strategy Replay" subtitle="Watch the bot analyse real history candle-by-candle — no lookahead" />

      <Card title="Load Replay" right={data ? <Badge text={`${data.meta.data_source} · ${data.meta.bars} bars`} tone="purple" /> : undefined}>
        <div className="row-actions" style={{ justifyContent: "flex-start", gap: 10, flexWrap: "wrap" }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>{SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select>
          <select value={tf} onChange={(e) => setTf(e.target.value)}>{["15m", "5m"].map((t) => <option key={t}>{t}</option>)}</select>
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>{[500, 800, 1200, 1500].map((b) => <option key={b} value={b}>{b} bars</option>)}</select>
          <label className="row-actions" style={{ gap: 4 }}><span className="dim">From</span>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></label>
          <label className="row-actions" style={{ gap: 4 }}><span className="dim">To</span>
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></label>
          <button className="btn btn-primary" disabled={loading} onClick={load}><Icon name="history" size={14} /> {loading ? "Loading…" : "Load"}</button>
        </div>
        <p className="dim" style={{ marginTop: 6, fontSize: 12 }}>
          Leave dates blank for the most recent window. Date ranges need a live data source
          (HUB_USE_LIVE_DATA) to jump to arbitrary months; otherwise they filter the available history.
        </p>
        {data && (
          <p className="dim" style={{ marginTop: 8 }}>
            {(data.meta.start ?? "").slice(0, 16).replace("T", " ")} → {(data.meta.end ?? "").slice(0, 16).replace("T", " ")} ·
            HTF: {Object.entries(data.meta.htf_available).map(([k, v]) => `${k} ${v ? "✓" : "n/a"}`).join(" · ")}
          </p>
        )}
      </Card>

      {!data ? (
        <Card title=""><div className="dim ta-center" style={{ padding: 30 }}>Pick an asset and timeframe, then <b>Load</b> to replay real market history.</div></Card>
      ) : (
        <>
          {/* controls */}
          <Card title="">
            <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button className="btn btn-soft" onClick={() => setIdx((i) => Math.max(0, i - 1))}><Icon name="chevron" size={14} /> Step ←</button>
              <button className="btn btn-primary" onClick={() => setPlaying((p) => !p)}>
                <Icon name={playing ? "pause" : "play"} size={14} /> {playing ? "Pause" : "Play"}
              </button>
              <button className="btn btn-soft" onClick={() => setIdx((i) => Math.min(data.candles.length - 1, i + 1))}>Step → <Icon name="chevron" size={14} /></button>
              <span className="dim">Speed</span>
              {SPEEDS.map((s) => <button key={s} className={`chip-btn ${speed === s ? "active" : ""}`} onClick={() => setSpeed(s)}>{s}x</button>)}
              <span className="dim mono" style={{ marginLeft: "auto" }}>{idx + 1} / {data.candles.length} · {(candle?.t ?? "").replace("T", " ").slice(0, 16)}</span>
            </div>
            <input type="range" min={0} max={data.candles.length - 1} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} style={{ width: "100%", marginTop: 10 }} />
          </Card>

          <div className="grid-2-1" style={{ gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)" }}>
            <Card title={`${symbol} · ${tf}`} className="span-2">
              <CandleChart data={data} index={idx} />
            </Card>

            <BrainPanel frame={frame} active={active} liveRR={liveRR} status={tradeStatus} />
          </div>

          <div className="grid-2-eq">
            <Card title="Decision Timeline" subtitle="every candle generates reasoning">
              <div className="alert-stack" style={{ maxHeight: 280, overflowY: "auto" }}>
                {visibleEvents.length === 0 ? <div className="dim">Press Play to watch the bot think.</div> :
                  visibleEvents.map((e, i) => (
                    <div key={i} className="exec-line">
                      <span className="exec-time">{(data.candles[e.idx]?.t ?? "").slice(11, 16)}</span>{" "}
                      <EventDot kind={e.kind} /> {e.text}
                    </div>
                  ))}
              </div>
            </Card>

            <TradeReview trade={lastClosed} />
          </div>

          <StatsPanel data={data} />
        </>
      )}
    </>
  );
}

function EventDot({ kind }: { kind: string }) {
  const c = kind === "entry" ? "#089981" : kind === "exit" ? "#3b82f6" : kind === "blocked" ? "#f23645"
    : kind === "sweep" || kind === "structure" || kind === "fvg" ? "#8b5cf6" : "#8a93a6";
  return <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: c, marginRight: 4 }} />;
}

function BrainPanel({ frame, active, liveRR, status }: {
  frame: any; active?: ReplayTrade; liveRR: number | null; status: string | null;
}) {
  if (!frame) return <Card title="Bot Brain"><div className="dim">—</div></Card>;
  const trigTone = frame.trigger === "Entry Confirmed" ? "green" : frame.trigger === "Setup Found" ? "amber" : "default";
  return (
    <Card title="Bot Brain" right={<Badge text={frame.regime} tone={frame.regime === "Trending" ? "green" : frame.regime?.includes("Volatility") ? "amber" : "default"} />}>
      <div className="risk-list">
        {["Weekly", "Daily", "4H", "15M"].map((tf) => (
          <div className="risk-item" key={tf}><span className="dim">{tf} trend</span> <Badge text={frame.trends[tf] ?? "n/a"} tone={trendTone(frame.trends[tf])} /></div>
        ))}
        <div className="risk-item"><span className="dim">5M trigger</span> <Badge text={frame.trigger} tone={trigTone as any} /></div>
      </div>

      <div style={{ marginTop: 10 }}>
        <div className="card-subtitle" style={{ marginBottom: 6 }}>
          Trade Quality {frame.score ? <b style={{ color: frame.score >= 75 ? "#089981" : frame.score >= 60 ? "#f59e0b" : "#f23645" }}>{frame.score}/100</b> : <span className="dim">no setup</span>}
        </div>
        {frame.breakdown && Object.entries(frame.breakdown).map(([k, v]: any) => (
          <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
            <span className="dim" style={{ width: 130, fontSize: 11 }}>{k}</span>
            <div style={{ flex: 1, height: 6, background: "#161d30", borderRadius: 3 }}>
              <div style={{ width: `${Math.min(100, (v / 25) * 100)}%`, height: 6, background: "#8b5cf6", borderRadius: 3 }} />
            </div>
            <b style={{ width: 24, textAlign: "right", fontSize: 11 }}>+{v}</b>
          </div>
        ))}
        {frame.blocked && <div className="risk-item" style={{ marginTop: 6 }}><Badge text={`Trade Blocked — ${frame.reason}`} tone="red" /></div>}
      </div>

      {active && (
        <div style={{ marginTop: 10, borderTop: "1px solid #1b2336", paddingTop: 8 }}>
          <div className="card-subtitle" style={{ marginBottom: 4 }}>Open {active.side} #{active.id}</div>
          <div className="risk-item"><span className="dim">Status</span>
            <Badge text={status ?? "Open"} tone={status?.includes("Partial") ? "amber" : "default"} /></div>
          <div className="risk-item"><span className="dim">Current RR</span> <b className={(liveRR ?? 0) >= 0 ? "pos" : "neg"}>{liveRR !== null ? `${liveRR >= 0 ? "+" : ""}${liveRR}R` : "—"}</b></div>
          <div className="risk-item"><span className="dim">{status?.includes("Partial") ? "SL→BE / TP" : "SL / TP"}</span> <b>{status?.includes("Partial") ? active.entry : active.sl} / {active.tp}</b></div>
        </div>
      )}
    </Card>
  );
}

function TradeReview({ trade }: { trade?: ReplayTrade }) {
  if (!trade) return <Card title="Trade Review"><div className="dim ta-center" style={{ padding: 24 }}>No closed trade yet — keep replaying.</div></Card>;
  const win = trade.result === "Winner";
  return (
    <Card title={`Trade Review #${trade.id}`} right={<Badge text={trade.result} tone={win ? "green" : "red"} />}>
      <div className="risk-list">
        <div className="risk-item"><span className="dim">Asset / Direction</span> <b>{trade.symbol} · {trade.side}</b></div>
        <div className="risk-item"><span className="dim">Result / RR</span> <b className={win ? "pos" : "neg"}>{trade.result} · {trade.rr! >= 0 ? "+" : ""}{trade.rr}R</b></div>
        <div className="risk-item"><span className="dim">Quality score</span> <b>{trade.score}/100</b></div>
        {trade.tp1_idx !== null && (
          <div className="risk-item"><span className="dim">Scale-out</span>
            <b className="pos">50% booked at +1R → break-even runner</b></div>
        )}
      </div>
      <div style={{ marginTop: 8 }}>
        <div className="card-subtitle" style={{ marginBottom: 4 }}>Reason for entry</div>
        <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.5 }}>{trade.entry_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      </div>
      <div style={{ marginTop: 8 }}>
        <div className="card-subtitle" style={{ marginBottom: 4 }}>Reason for exit</div>
        <p style={{ margin: 0 }}>{trade.exit_reason}</p>
        {!win && trade.loss_analysis && (
          <p className="neg" style={{ marginTop: 6, display: "flex", gap: 6, alignItems: "flex-start" }}>
            <Icon name="warning" size={14} /> {trade.loss_analysis}
          </p>
        )}
      </div>
    </Card>
  );
}

function StatsPanel({ data }: { data: ReplayData }) {
  const s = data.stats;
  const cells: [string, string, string][] = [
    ["Win Rate", `${s.win_rate}%`, ""],
    ["Profit Factor", s.profit_factor.toFixed(2), s.profit_factor >= 1 ? "pos" : "neg"],
    ["Net", `${s.net_r >= 0 ? "+" : ""}${s.net_r}R`, s.net_r >= 0 ? "pos" : "neg"],
    ["Max Drawdown", `${s.max_drawdown_r}R`, ""],
    ["Avg RR", s.avg_rr.toFixed(2), ""],
    ["Expectancy", `${s.expectancy_r}R`, s.expectancy_r >= 0 ? "pos" : "neg"],
    ["Best / Worst", `${s.best_r} / ${s.worst_r}R`, ""],
    ["Long / Short", `${s.long_trades} / ${s.short_trades}`, ""],
  ];
  return (
    <Card title="Simulation Statistics" subtitle={`${s.trades} trades · ${s.symbol} (run another asset to compare)`}>
      <div className="perf-grid">
        {cells.map(([l, v, tone]) => (
          <div className="perf-item" key={l}><span className="perf-label">{l}</span><div className="perf-value-row"><span className={`perf-value ${tone}`}>{v}</span></div></div>
        ))}
      </div>
    </Card>
  );
}
