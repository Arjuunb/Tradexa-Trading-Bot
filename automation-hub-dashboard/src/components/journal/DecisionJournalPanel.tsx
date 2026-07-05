import { useEffect, useState } from "react";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { apiGet } from "../../lib/api";

/** Full Decision Journal for one bot trade — every section explains WHY the
 *  bot acted, from real captured data. Fetched lazily when the row expands. */

type Read = { name: string; status: string; detail?: string; rule?: string };
type Journal = {
  trade_id: string; mode: string; symbol: string; side: string; strategy: string;
  timeframe: string; entry: number; stop: number; target: number | null; exit: number | null;
  size: number; risk_amount: number; planned_rr: number | null; actual_rr: number | null;
  pnl: number | null; result: string | null; confidence: number | null;
  brain_score: number | null; regime: string; grade: string | null; status: string;
  events: { ts: string; kind: string; detail: string }[];
  sections: {
    entry_decision?: any; checklist?: { entry_reads: Read[]; risk_gates: Read[] };
    market_snapshot?: Record<string, any>; risk_check?: any; exit_decision?: any;
    review?: any; evolution?: any;
  };
};

const statusTone = (s: string) =>
  s === "Passed" ? "green" : s === "Failed" ? "red" : s === "Neutral" ? "amber" : "default";
const gradeTone = (g?: string | null) =>
  g === "A" || g === "B" ? "green" : g === "C" ? "amber" : g ? "red" : "default";

function Row({ k, v }: { k: string; v: any }) {
  if (v === undefined || v === null || v === "") return null;
  return <div className="risk-item"><span className="dim">{k}</span><b style={{ fontSize: 12 }}>{String(v)}</b></div>;
}
function Section({ title, children }: { title: string; children: any }) {
  return (
    <div style={{ marginTop: 12 }}>
      <div className="card-subtitle" style={{ marginBottom: 6, marginLeft: 0, fontWeight: 700 }}>{title}</div>
      {children}
    </div>
  );
}
function Checks({ items }: { items: Read[] }) {
  return (
    <div className="risk-list">
      {items.map((c, i) => (
        <div key={i} className="risk-item">
          <span style={{ fontSize: 12 }}>{c.name}{c.detail ? <span className="dim"> · {c.detail}</span> : null}</span>
          <Badge text={c.status} tone={statusTone(c.status) as any} />
        </div>
      ))}
    </div>
  );
}

export default function DecisionJournalPanel({ tradeId }: { tradeId: string }) {
  const [j, setJ] = useState<Journal | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let ok = true;
    apiGet<Journal>(`/journal/${tradeId}`).then((d) => ok && setJ(d))
      .catch(() => ok && setErr("No decision journal for this trade (it predates journaling)."));
    return () => { ok = false; };
  }, [tradeId]);

  if (err) return <div className="dim" style={{ padding: 12, fontSize: 12 }}><Icon name="info" size={12} /> {err}</div>;
  if (!j) return <div className="dim" style={{ padding: 12 }}>Loading journal…</div>;

  const s = j.sections;
  const snap = s.market_snapshot ?? {};
  const ed = s.entry_decision ?? {};
  const ex = s.exit_decision ?? {};
  const rv = s.review ?? {};
  const ev = s.evolution ?? {};

  return (
    <div style={{ padding: "6px 4px 10px" }}>
      {/* 1. Trade Summary */}
      <Section title="1 · Trade Summary">
        <div className="form-grid-3">
          <Row k="Trade ID" v={j.trade_id.slice(0, 8)} /><Row k="Mode" v={j.mode} />
          <Row k="Symbol" v={j.symbol} /><Row k="Direction" v={j.side} />
          <Row k="Strategy" v={j.strategy} /><Row k="Timeframe" v={j.timeframe} />
          <Row k="Entry" v={j.entry} /><Row k="Stop" v={j.stop} /><Row k="Target" v={j.target} />
          <Row k="Exit" v={j.exit} /><Row k="Size" v={j.size} /><Row k="Risk amount" v={j.risk_amount} />
          <Row k="Planned R:R" v={j.planned_rr != null ? `${j.planned_rr.toFixed(2)}R` : null} />
          <Row k="Actual R:R" v={j.actual_rr != null ? `${j.actual_rr.toFixed(2)}R` : null} />
          <Row k="P&L" v={j.pnl != null ? j.pnl.toFixed(2) : null} />
        </div>
        <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, marginTop: 8 }}>
          {j.result && <Badge text={j.result} tone={j.result === "win" ? "green" : j.result === "loss" ? "red" : "default"} />}
          {j.grade && <Badge text={`Grade ${j.grade}`} tone={gradeTone(j.grade) as any} />}
          <Badge text={j.status} tone={j.status === "closed" ? "default" : "blue"} />
        </div>
      </Section>

      {/* 2. Entry Decision */}
      <Section title="2 · Entry Decision">
        <div className="risk-list">
          <Row k="Main reason" v={ed.main_reason} />
          <Row k="Setup" v={ed.strategy_setup} />
          <Row k="Higher-timeframe trend" v={ed.higher_timeframe_trend} />
          <Row k="Confidence score" v={ed.confidence_score} />
          <Row k="Final decision score" v={ed.final_decision_score} />
        </div>
      </Section>

      {/* 3. Rule Checklist */}
      {s.checklist && (
        <Section title="3 · Rule Checklist">
          <div className="dim" style={{ fontSize: 11, margin: "2px 0 4px" }}>Entry reads</div>
          <Checks items={s.checklist.entry_reads} />
          <div className="dim" style={{ fontSize: 11, margin: "8px 0 4px" }}>Risk / safety gates</div>
          <Checks items={s.checklist.risk_gates} />
        </Section>
      )}

      {/* 4. Market Snapshot */}
      <Section title="4 · Market Snapshot (at entry)">
        <div className="form-grid-3">
          {Object.entries(snap).map(([k, v]) =>
            v == null ? null : <Row key={k} k={k.replace(/_/g, " ")} v={v} />)}
        </div>
      </Section>

      {/* 5. Risk Check */}
      {s.risk_check && (
        <Section title="5 · Risk Check">
          <div className="risk-list">
            <Row k="Risk per trade" v={s.risk_check.risk_per_trade} />
            <Row k="Final risk decision" v={s.risk_check.final_risk_decision} />
          </div>
        </Section>
      )}

      {/* 6. Trade Timeline */}
      <Section title="6 · Trade Timeline">
        <div className="risk-list">
          {j.events.map((e, i) => (
            <div key={i} className="risk-item">
              <span style={{ fontSize: 12 }}><b>{e.kind}</b> <span className="dim">{e.detail}</span></span>
              <span className="dim mono" style={{ fontSize: 11 }}>{(e.ts || "").slice(11, 19)}</span>
            </div>
          ))}
        </div>
      </Section>

      {/* 7. Exit Decision */}
      {s.exit_decision && (
        <Section title="7 · Exit Decision">
          <div className="risk-list">
            <Row k="Exit reason" v={ex.exit_reason} /><Row k="Exit price" v={ex.exit_price} />
            <Row k="Actual R:R" v={ex.actual_rr != null ? `${ex.actual_rr}R` : null} />
            <Row k="P&L" v={ex.pnl} /><Row k="Result" v={ex.result} />
          </div>
        </Section>
      )}

      {/* 8. Post-Trade Review */}
      {s.review && (
        <Section title="8 · Post-Trade Review">
          <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, marginBottom: 6 }}>
            <Badge text={`Grade ${rv.grade}`} tone={gradeTone(rv.grade) as any} />
            <Badge text={rv.quality} tone={rv.quality === "good" ? "green" : rv.quality === "acceptable" ? "amber" : "red"} />
          </div>
          <div className="risk-list">
            <Row k="Entry valid" v={rv.entry_valid ? "Yes" : "No"} />
            <Row k="Risk valid" v={rv.risk_valid ? "Yes" : "No"} />
            <Row k="Exit valid" v={rv.exit_valid ? "Yes" : "No"} />
            <Row k="Followed strategy" v={rv.followed_strategy ? "Yes" : "No"} />
            <Row k="Mistake" v={rv.mistake} />
            <Row k="Improvement" v={rv.improvement} />
          </div>
        </Section>
      )}

      {/* 9. Evolution Notes */}
      {s.evolution && (
        <Section title="9 · Evolution Notes">
          <div className="risk-list">
            <Row k="Learned" v={ev.learned} />
            <Row k="Evidence strength" v={ev.strength} />
            <Row k="Take similar again" v={ev.take_similar_again ? "Yes" : "Not on this alone"} />
            <Row k="Confidence direction" v={ev.confidence_direction} />
            <Row k="Rule-weight hint" v={ev.rule_weight_hint} />
          </div>
          {Array.isArray(ev.guardrails) && (
            <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.6 }} className="dim">
              {ev.guardrails.map((g: string, i: number) => <li key={i} style={{ fontSize: 11 }}>{g}</li>)}
            </ul>
          )}
        </Section>
      )}
    </div>
  );
}
