import { useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader } from "../components/common/ui";
import { apiGet, apiPost, useLive, type CoachReview, type CoachLeaderboard, type JournalEntry,
  type LedgerPosition, type PaperAccount, type RiskSummary, type StrategyPerformance, type SystemStatus } from "../lib/api";
import { useApp } from "../app-context";

interface Ctx {
  sys: SystemStatus | null; acct: PaperAccount | null; perf: StrategyPerformance | null;
  risk: RiskSummary | null; positions: LedgerPosition[];
}

// Deterministic, rule-based answers over REAL backend data — no fabricated
// numbers. The same answer() seam can later be backed by an LLM.
function answer(q: string, c: Ctx): string {
  const s = q.toLowerCase();
  const has = (...w: string[]) => w.some((x) => s.includes(x));
  if (has("balance", "account", "equity", "money"))
    return `Balance is $${(c.acct?.balance ?? 0).toLocaleString()}, realized P&L $${(c.acct?.realized_pnl ?? 0).toFixed(2)}, with ${c.positions.length} open position(s).`;
  if (has("win", "performance", "profit", "doing"))
    return `Win rate ${(c.perf?.win_rate ?? 0).toFixed(1)}%, profit factor ${(c.perf?.profit_factor ?? 0).toFixed(2)} over ${c.perf?.trades ?? 0} paper trades.`;
  if (has("risk", "exposure", "drawdown"))
    return `Exposure ${((c.risk?.exposure_pct ?? 0) * 100).toFixed(1)}%, trading state "${c.risk?.trading_state ?? "unknown"}", ${c.risk?.rejections ?? 0} risk-blocked signals.`;
  if (has("live", "real money"))
    return "Live trading is locked. The bot only trades paper money until the full safety flow passes and a broker is connected.";
  if (has("strategy", "engine", "running"))
    return `Strategy "${c.sys?.strategy ?? "—"}" on ${c.sys?.timeframe ?? "—"}; engine is ${c.sys?.engine_running ? "running" : "stopped"} in ${c.sys?.mode ?? "paper"} mode.`;
  return "I can answer about your balance, performance, risk/exposure, the active strategy and live-trading status — all from real backend data. Try one of the suggestions above.";
}

const SAMPLES = ["How is my account?", "How am I performing?", "What's my risk?", "Is live trading on?"];

export default function AIAssistantPage() {
  const sys = useLive<SystemStatus>("/system/status", 4000);
  const acct = useLive<PaperAccount>("/paper/account", 4000);
  const perf = useLive<StrategyPerformance>("/strategy/performance", 4000);
  const risk = useLive<RiskSummary>("/risk/summary", 4000);
  const positions = useLive<LedgerPosition[]>("/paper/positions", 4000);
  const ctx: Ctx = { sys: sys.data, acct: acct.data, perf: perf.data, risk: risk.data, positions: positions.data ?? [] };

  const [q, setQ] = useState("");
  const [log, setLog] = useState<{ q: string; a: string }[]>([]);

  const ask = (question: string) => {
    if (!question.trim()) return;
    setLog((l) => [{ q: question, a: answer(question, ctx) }, ...l]);
    setQ("");
  };

  return (
    <>
      <PageHeader title="AI Assistant" subtitle="Answers from your real bot data — no fabricated numbers" />

      <Card title="Ask about your bot">
        <div className="chips" style={{ marginBottom: 10 }}>
          {SAMPLES.map((s) => <button key={s} className="chip-btn" onClick={() => ask(s)}>{s}</button>)}
        </div>
        <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8 }}>
          <input style={{ flex: 1 }} placeholder="Type a question…" value={q}
            onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask(q)} />
          <button className="btn btn-primary" onClick={() => ask(q)}><Icon name="bot" size={14} /> Ask</button>
        </div>
      </Card>

      <TradingCoach />
      <TradeJournal />

      {log.length > 0 && (
        <Card title="Conversation">
          <div className="alert-stack">
            {log.map((m, i) => (
              <div key={i} className="risk-item" style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 4 }}>
                  <Icon name="help" size={15} className="dim" /><b>{m.q}</b>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                  <Icon name="bot" size={15} className="pos" /><span>{m.a}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}

const COACH_SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"];
const COACH_STRATS = ["Decision Brain", "Trend Following", "Supply/Demand", "EMA 8/30", "EMA 20/50", "Liquidity Sweep"];
const rTone = (n: number) => (n > 0 ? "pos" : n < 0 ? "neg" : "");

function TradingCoach() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [strategy, setStrategy] = useState("Decision Brain");
  const [rev, setRev] = useState<CoachReview | null>(null);
  const [board, setBoard] = useState<CoachLeaderboard | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyB, setBusyB] = useState(false);

  const review = async () => {
    setBusy(true);
    try { setRev(await apiGet<CoachReview>(`/coach/review?symbol=${symbol}&strategy=${encodeURIComponent(strategy)}&timeframe=15m&limit=800`)); }
    catch { setRev({ available: false, error: "request failed" } as any); }
    finally { setBusy(false); }
  };
  const leaderboard = async () => {
    setBusyB(true);
    try { setBoard(await apiGet<CoachLeaderboard>(`/coach/leaderboard?symbols=BTCUSDT,ETHUSDT&strategies=Decision Brain,EMA 20/50,Supply/Demand&timeframe=15m&limit=600`)); }
    catch { /* ignore */ } finally { setBusyB(false); }
  };

  const attrTable = (title: string, rows?: { key: string; trades: number; net_r: number; win_rate: number }[]) => (
    <div>
      <div className="card-subtitle" style={{ marginBottom: 4 }}>{title}</div>
      <table className="data-table" style={{ fontSize: 12 }}>
        <tbody>
          {(rows ?? []).map((b) => (
            <tr key={b.key}><td><b>{b.key}</b></td><td className="dim">{b.trades > 0 ? `${b.trades}t · ${b.win_rate}%` : ""}</td>
              <td className={rTone(b.net_r)} style={{ textAlign: "right" }}>{b.net_r >= 0 ? "+" : ""}{b.net_r}R</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <Card title="AI Trading Coach" subtitle="mentor review of a real simulation · why won / lost, mistakes, attribution"
      right={<div className="row-actions" style={{ gap: 6 }}>
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>{COACH_STRATS.map((s) => <option key={s}>{s}</option>)}</select>
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>{COACH_SYMS.map((s) => <option key={s}>{s}</option>)}</select>
        <button className="btn btn-primary" disabled={busy} onClick={review}><Icon name="bot" size={14} /> {busy ? "Reviewing…" : "Review"}</button>
      </div>}>
      {!rev ? (
        <div className="dim ta-center" style={{ padding: 16 }}>Pick a strategy + symbol and let the coach review a real replay.</div>
      ) : rev.available === false ? (
        <div className="card" style={{ borderColor: "var(--gold)", background: "rgba(234,181,79,0.08)" }}>
          <Icon name="warning" size={14} className="amber" /> {rev.error || "No data."} {rev.needs_download && "Download Binance history first."}
        </div>
      ) : (
        <>
          <div className="row-actions" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <b style={{ fontSize: 14 }}>{rev.headline}</b>
            <span className="row-actions" style={{ gap: 6 }}>
              <Badge text={`confidence ${rev.confidence_score}`} tone={rev.confidence_score >= 60 ? "green" : rev.confidence_score >= 35 ? "amber" : "red"} />
              <Badge text={`stability ${rev.stability_score}`} tone={rev.stability_score >= 60 ? "green" : "amber"} />
            </span>
          </div>

          <div className="grid-2-eq" style={{ marginTop: 10 }}>
            <div>
              <div className="card-subtitle pos" style={{ marginBottom: 4 }}>Why trades won</div>
              <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.5 }}>{rev.why_won.map((w, i) => <li key={i}>{w}</li>)}</ul>
              {rev.why_lost.length > 0 && <>
                <div className="card-subtitle neg" style={{ margin: "10px 0 4px" }}>Why trades lost</div>
                <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.5 }}>{rev.why_lost.map((w, i) => <li key={i}>{w}</li>)}</ul>
              </>}
            </div>
            <div>
              <div className="card-subtitle" style={{ marginBottom: 4 }}>Common mistakes</div>
              {rev.common_mistakes.length ? rev.common_mistakes.map((m, i) => (
                <div key={i} className="risk-item"><span className="neg">{m.mistake}</span> <b>×{m.count}</b></div>
              )) : <div className="dim">No recurring mistake stood out.</div>}
              {rev.weak_conditions.length > 0 && (
                <div style={{ marginTop: 8 }}><span className="dim">Avoid: </span>{rev.weak_conditions.map((w) => <Badge key={w} text={w} tone="amber" />)}</div>
              )}
            </div>
          </div>

          <div className="card-subtitle" style={{ margin: "12px 0 4px", color: "var(--purple-2)" }}>Coach suggestions</div>
          <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.6 }}>{rev.suggestions.map((s, i) => <li key={i}>{s}</li>)}</ul>

          <div className="card-subtitle" style={{ margin: "12px 0 6px" }}>Performance attribution</div>
          <div className="grid-2-eq">
            {attrTable("By regime", rev.attribution.by_regime)}
            {attrTable("By session", rev.attribution.by_session)}
            {attrTable("By setup", rev.attribution.by_setup)}
            {attrTable("By side", rev.attribution.by_side)}
          </div>

          {rev.sample_explanations && rev.sample_explanations.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary className="dim" style={{ cursor: "pointer", fontSize: 12 }}>Explainable AI — why / why-not / why-trust</summary>
              {rev.sample_explanations.map((e) => (
                <div key={e.id} className="card" style={{ marginTop: 8, background: "var(--card-2)" }}>
                  <div className="row-actions" style={{ justifyContent: "space-between" }}>
                    <b>Trade #{e.id}</b><Badge text={`${e.result} ${e.rr! >= 0 ? "+" : ""}${e.rr}R`} tone={e.result === "Winner" ? "green" : "red"} />
                  </div>
                  <div className="risk-item"><span className="dim" style={{ minWidth: 70 }}>Why</span> <span>{e.why}</span></div>
                  <div className="risk-item"><span className="dim" style={{ minWidth: 70 }}>Why not</span> <span>{e.why_not}</span></div>
                  <div className="risk-item"><span className="dim" style={{ minWidth: 70 }}>Why trust</span> <span style={{ color: "var(--purple-2)" }}>{e.why_trust}</span></div>
                </div>
              ))}
            </details>
          )}
        </>
      )}

      <div style={{ borderTop: "1px solid var(--card-border-soft)", marginTop: 14, paddingTop: 12 }}>
        <div className="row-actions" style={{ justifyContent: "space-between" }}>
          <div className="card-subtitle">Leaderboard — which strategy / symbol makes money</div>
          <button className="btn btn-soft" disabled={busyB} onClick={leaderboard}><Icon name="chart" size={13} /> {busyB ? "Running…" : "Run leaderboard"}</button>
        </div>
        {board && (
          <div className="grid-2-eq" style={{ marginTop: 8 }}>
            {attrTable("By strategy (net R)", board.by_strategy.map((b) => ({ key: b.key, net_r: b.net_r, trades: 0, win_rate: 0 })) as any)}
            {attrTable("By symbol (net R)", board.by_symbol.map((b) => ({ key: b.key, net_r: b.net_r, trades: 0, win_rate: 0 })) as any)}
          </div>
        )}
      </div>
    </Card>
  );
}

const J_STRATS = ["Decision Brain", "Supply/Demand", "EMA 8/30", "EMA 20/50", "Liquidity Sweep"];

function TradeJournal() {
  const app = useApp();
  const j = useLive<{ entries: JournalEntry[] }>("/journal", 8000);
  const [strategy, setStrategy] = useState("Decision Brain");
  const [busy, setBusy] = useState(false);
  const entries = j.data?.entries ?? [];
  const gen = async () => {
    setBusy(true);
    try { const r = await apiPost<any>(`/journal/from-replay?symbol=BTCUSDT&strategy=${encodeURIComponent(strategy)}&timeframe=15m&limit=800`);
      app.toast(`Journaled ${r.added ?? 0} trades`, "success"); j.refetch(); }
    catch { app.toast("Journaling needs the webhook secret", "error"); }
    finally { setBusy(false); }
  };
  return (
    <Card title="Trade Journal" subtitle="auto-entries per trade · notes, mistakes, lessons (editable)"
      right={<div className="row-actions" style={{ gap: 6 }}>
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>{J_STRATS.map((s) => <option key={s}>{s}</option>)}</select>
        <button className="btn btn-soft" disabled={busy} onClick={gen}><Icon name="history" size={13} /> {busy ? "…" : "Auto-journal"}</button>
      </div>}>
      {entries.length === 0 ? <div className="dim ta-center" style={{ padding: 14 }}>No journal entries yet — auto-journal a strategy's trades.</div> : (
        <div className="alert-stack" style={{ maxHeight: 360, overflowY: "auto" }}>
          {entries.slice(0, 25).map((e) => (
            <div key={e.id} className="card" style={{ background: "var(--card-2)", marginBottom: 6 }}>
              <div className="row-actions" style={{ justifyContent: "space-between" }}>
                <b>{e.symbol.replace("USDT", "")} · {e.side}</b>
                <Badge text={`${e.result} ${e.rr != null ? `${e.rr >= 0 ? "+" : ""}${e.rr}R` : ""}`} tone={e.result === "Winner" ? "green" : e.result === "Loser" ? "red" : "default"} />
              </div>
              <span className="dim" style={{ fontSize: 12 }}>{e.notes}</span>
              {e.mistakes.length > 0 && <div className="neg" style={{ fontSize: 12 }}><Icon name="warning" size={11} /> {e.mistakes.join("; ")}</div>}
              {e.lessons.length > 0 && <div style={{ fontSize: 12, color: "var(--purple-2)" }}>Lesson: {e.lessons.join("; ")}</div>}
              <div className="row-actions" style={{ gap: 4, flexWrap: "wrap" }}>{e.tags.map((t) => <span key={t} className="ui-badge" style={{ background: "rgba(139,92,246,0.14)", color: "var(--purple-2)" }}>{t}</span>)}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
