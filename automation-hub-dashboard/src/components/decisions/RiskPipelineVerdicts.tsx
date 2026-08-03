import { useMemo, useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge, EmptyState } from "../common/ui";
import { useLive } from "../../lib/api";
import type { DecisionRecord, DecisionRule, RuleStatus } from "../../lib/api";

/** Risk pipeline verdicts — what the gate decided, and why.
 *
 *  DELIBERATELY NOT a second Decision Reports feed. The card above it on this
 *  page renders cycle reports from services/explain.py: what the ANALYSIS saw
 *  on each candle, including WAIT. This renders decision_store: what the RISK
 *  PIPELINE ruled about each signal that actually reached the gate, with the
 *  per-rule verdicts and the reason for a rejection. They are complementary
 *  halves of one question, and only the first half was being shown.
 *
 *  /decisions/latest and /decisions/rejected existed on the backend and nothing
 *  in the app called them, so every rejection reason was persisted and never
 *  read by anyone.
 *
 *  Nothing here is computed in the browser. Every score, rule verdict and
 *  reason is rendered exactly as the backend recorded it at decision time; a
 *  field the record does not carry is omitted rather than filled with a dash,
 *  so an absent value is never mistaken for a measured one.
 */

// The five verdicts a rule can return — services/rule_status.py. `vetoed` is
// deliberately distinct from `failed`: overridden by the risk engine, rather
// than failing on the rule's own merits. `unavailable` is distinct from both:
// the check could not run, which is not a pass.
const STATUS_TONE: Record<RuleStatus, "green" | "amber" | "red" | "purple" | "default"> = {
  passed: "green",
  weak: "amber",
  failed: "red",
  vetoed: "purple",
  unavailable: "default",
};

const STATUS_HINT: Record<RuleStatus, string> = {
  passed: "Rule ran and the setup satisfied it",
  weak: "Satisfied, but marginally — not a rejection on its own",
  failed: "Rule ran and the setup did not satisfy it",
  vetoed: "Overridden by the risk engine, not a failure of this rule",
  unavailable: "Could not be evaluated — this is NOT a pass",
};

/** Score categories the backend computes deterministically, each out of 20.
 *  Labels only; the values come from the record. */
const COMPONENT_LABEL: Record<string, string> = {
  trend: "Trend",
  structure: "Structure",
  supply_demand: "Supply / Demand",
  volume: "Volume",
  rr_quality: "Risk / Reward",
  risk: "Risk",
};

function pct(n: number | null | undefined): string {
  return n == null ? "" : `${Math.round(n * 100)}%`;
}

function RuleRow({ rule }: { rule: DecisionRule }) {
  const tone = STATUS_TONE[rule.status] ?? "default";
  return (
    <li
      className="decision-rule"
      title={STATUS_HINT[rule.status] ?? rule.status}
      style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.04)",
      }}
    >
      <span style={{ fontSize: 13 }}>{rule.rule.replace(/_/g, " ")}</span>
      <Badge text={rule.status} tone={tone} />
    </li>
  );
}

/** The weighted confidence breakdown. §2: never show a confidence number
 *  without showing how it was reached. */
function ScoreBreakdown({ d }: { d: DecisionRecord }) {
  const parts = useMemo(
    () =>
      Object.entries(d.components ?? {})
        .filter(([, v]) => typeof v === "number")
        .map(([k, v]) => ({ key: k, label: COMPONENT_LABEL[k] ?? k.replace(/_/g, " "), value: v as number })),
    [d.components],
  );

  if (!parts.length && d.setup_quality_score == null) return null;

  const max = Math.max(...parts.map((p) => p.value), 20);

  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
        <span className="stat-label">Setup quality</span>
        {d.setup_quality_score != null && (
          <b style={{ fontSize: 15 }}>{Math.round(d.setup_quality_score)}<span className="dim">/100</span></b>
        )}
        {d.confidence != null && (
          <span className="stat-sub dim">· strategy confidence {pct(d.confidence)}</span>
        )}
      </div>

      {parts.length > 0 ? (
        <div style={{ display: "grid", gap: 6 }}>
          {parts.map((p) => (
            <div key={p.key} style={{ display: "grid", gridTemplateColumns: "120px 1fr 40px", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 12 }} className="dim">{p.label}</span>
              <div style={{ height: 6, background: "rgba(255,255,255,0.06)", borderRadius: 3, overflow: "hidden" }}>
                <div
                  style={{
                    width: `${Math.max(0, Math.min(100, (p.value / max) * 100))}%`,
                    height: "100%", background: "#eab54f", borderRadius: 3,
                  }}
                />
              </div>
              <span style={{ fontSize: 12, textAlign: "right" }} className="tabular">{Math.round(p.value)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="stat-sub dim" style={{ margin: 0 }}>
          The quality gate did not run for this decision, so there is no score to break down.
        </p>
      )}
    </div>
  );
}

function DecisionCard({ d, expanded, onToggle }: {
  d: DecisionRecord; expanded: boolean; onToggle: () => void;
}) {
  const rejected = d.decision === "rejected";
  // Prefer `rules` (per-rule verdicts). Fall back to the flat lists for rows
  // written before the store carried them — reconstructed, never invented.
  const rules: DecisionRule[] = d.rules?.length
    ? d.rules
    : [
        ...(d.passed_rules ?? []).map((r) => ({ rule: r, status: "passed" as RuleStatus })),
        ...(d.failed_rules ?? []).map((r) => ({ rule: r, status: "failed" as RuleStatus })),
      ];

  const counts = rules.reduce<Record<string, number>>((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div
      className="decision-card"
      style={{
        border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10,
        borderLeft: `3px solid ${rejected ? "#ef4444" : "#22c55e"}`,
        padding: "10px 12px", marginBottom: 8,
      }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        style={{
          all: "unset", cursor: "pointer", width: "100%", display: "flex",
          alignItems: "center", justifyContent: "space-between", gap: 12,
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <b style={{ fontSize: 14 }}>{d.symbol}</b>
          <span className="dim" style={{ fontSize: 12 }}>{d.timeframe} · {d.side}</span>
          <Badge text={d.decision} tone={rejected ? "red" : "green"} />
          {d.executed && <Badge text="executed" tone="blue" />}
          {d.regime && <Badge text={d.regime} tone="default" />}
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Rule tally, so the shape of a decision is legible without expanding. */}
          {(["passed", "weak", "failed", "vetoed", "unavailable"] as RuleStatus[])
            .filter((s) => counts[s])
            .map((s) => <Badge key={s} text={`${counts[s]} ${s}`} tone={STATUS_TONE[s]} />)}
          <Icon name={expanded ? "chevron-up" : "chevron-down"} size={14} />
        </span>
      </button>

      {/* The reason is always visible, expanded or not: it is the answer to
          "why", and hiding it behind a click defeats the point of the page. */}
      {d.reason && (
        <p style={{ margin: "8px 0 0", fontSize: 13, lineHeight: 1.5 }} className={rejected ? "" : "dim"}>
          {d.reason}
        </p>
      )}

      {expanded && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12 }} className="dim">
            {d.strategy && <span>Strategy <b>{d.strategy}</b></span>}
            {d.htf_bias && <span>Higher-timeframe bias <b>{d.htf_bias}</b></span>}
            {d.regime && <span>Regime <b>{d.regime}</b></span>}
            <span>Recorded <b>{new Date(d.ts).toLocaleString()}</b></span>
          </div>

          <ScoreBreakdown d={d} />

          <div style={{ marginTop: 14 }}>
            <span className="stat-label">Rules</span>
            {rules.length ? (
              <ul style={{ listStyle: "none", margin: "6px 0 0", padding: 0 }}>
                {rules.map((r) => <RuleRow key={`${r.rule}-${r.status}`} rule={r} />)}
              </ul>
            ) : (
              <p className="stat-sub dim" style={{ margin: "6px 0 0" }}>
                No individual rule verdicts were recorded for this decision.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const FILTERS = [
  { key: "all", label: "All", path: "/decisions/latest?limit=50" },
  { key: "rejected", label: "Rejected only", path: "/decisions/rejected?limit=50" },
] as const;

export default function RiskPipelineVerdicts() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [open, setOpen] = useState<number | null>(null);

  const path = FILTERS.find((f) => f.key === filter)!.path;
  const { data, error, loading } = useLive<{ decisions: DecisionRecord[] }>(path, 5000);
  const decisions = data?.decisions ?? [];

  return (
    <Card
      title="Risk pipeline verdicts"
      subtitle="What the risk gate decided about each signal that reached it — the half the Decision Reports above do not cover"
      right={
        <div style={{ display: "flex", gap: 6 }}>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={`chip ${filter === f.key ? "on" : ""}`}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      }
    >
      {/* Error, loading and empty are three different states and say three
          different things — §9. An empty archive is not a failure. */}
      {error && (
        <p style={{ margin: 0, fontSize: 13 }} className="neg">
          Could not load decisions: {error}
        </p>
      )}
      {!error && loading && decisions.length === 0 && (
        <p className="stat-sub dim" style={{ margin: 0 }}>Loading decisions…</p>
      )}
      {!error && !loading && decisions.length === 0 && (
        <EmptyState text="No decisions recorded yet. They appear here as soon as the engine evaluates its first signal." />
      )}

      {decisions.map((d) => (
        <DecisionCard
          key={d.id}
          d={d}
          expanded={open === d.id}
          onToggle={() => setOpen(open === d.id ? null : d.id)}
        />
      ))}
    </Card>
  );
}
