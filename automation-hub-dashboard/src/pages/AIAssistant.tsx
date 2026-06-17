import { useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { PageHeader } from "../components/common/ui";
import { useLive, type LedgerPosition, type PaperAccount, type RiskSummary, type StrategyPerformance, type SystemStatus } from "../lib/api";

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
