import { useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import {
  apiPostJson,
  type CustomSpec, type OptimisationSuggestion, type Scorecard,
  type StrategyFullReview, type SuggestionApplyResult,
} from "../../lib/api";

/**
 * AI Strategy Review — unlocked once a backtest has run.
 *
 * Everything shown is computed from that backtest. Scores that the sample
 * cannot support render as "not enough data" rather than a number, each score
 * exposes the formula behind it, and no suggestion is ever applied on its own —
 * accepting one re-runs the SAME window and shows a before/after comparison for
 * the user to judge.
 */

const RATING_TONE: Record<string, string> = {
  A: "green", B: "green", C: "amber", D: "amber", E: "red", F: "red",
};
const CONF_TONE: Record<string, string> = { high: "green", medium: "amber", low: "red" };
const num = (v: unknown, dp = 2) =>
  typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(dp)) : "—";

function ScoreBar({ label, value, basis }: { label: string; value: number | null; basis?: string }) {
  return (
    <div style={{ marginBottom: 8 }} title={basis}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
        <span className="dim">{label}</span>
        <b>{value == null ? <span className="dim">not enough data</span> : `${value}`}</b>
      </div>
      <div style={{ height: 5, borderRadius: 3, background: "rgba(255,255,255,.07)", marginTop: 3 }}>
        {value != null && (
          <div style={{
            width: `${Math.max(0, Math.min(100, value))}%`, height: "100%", borderRadius: 3,
            background: value >= 70 ? "#089981" : value >= 45 ? "#eab54f" : "#f23645",
          }} />
        )}
      </div>
    </div>
  );
}

function Bucket({ title, rows, keyName }: {
  title: string; keyName: string;
  rows: { trades: number; net_r: number; win_rate: number; [k: string]: unknown }[];
}) {
  if (!rows?.length) return null;
  return (
    <>
      <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6, margin: "10px 0 4px" }}>{title}</div>
      <table className="data-table"><tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td>{String(r[keyName])}</td>
            <td className="mono dim">{r.trades}</td>
            <td className={`mono ${r.net_r >= 0 ? "pos" : "neg"}`}>{r.net_r > 0 ? "+" : ""}{r.net_r}R</td>
            <td className="mono dim">{r.win_rate}%</td>
          </tr>
        ))}
      </tbody></table>
    </>
  );
}

export default function StrategyReviewDashboard({
  review, spec, range, onUseOptimised, toast,
}: {
  review: StrategyFullReview; spec: CustomSpec; range: string;
  onUseOptimised: (s: CustomSpec) => void;
  toast: (m: string, t?: string) => void;
}) {
  const [applying, setApplying] = useState<string>("");
  const [applied, setApplied] = useState<Record<string, SuggestionApplyResult>>({});
  const [open, setOpen] = useState<string>("");

  if (!review.available || !review.scorecard) {
    return <Card title="AI Strategy Review"><div className="dim" style={{ padding: 10 }}>
      {review.note || "Run a backtest to unlock the review."}</div></Card>;
  }
  const sc: Scorecard = review.scorecard;
  const p = sc.performance;

  const accept = async (s: OptimisationSuggestion) => {
    if (!s.patch) return;
    setApplying(s.id);
    try {
      const r = await apiPostJson<SuggestionApplyResult>("/strategy/apply-suggestion",
        { spec, patch: s.patch, range });
      setApplied((a) => ({ ...a, [s.id]: r }));
      if (!r.available) toast(r.note || "Comparison unavailable", "error");
    } catch { toast("Could not test that change", "error"); }
    finally { setApplying(""); }
  };

  return (
    <>
      {/* ── overall ── */}
      <Card title="AI Strategy Review"
            subtitle={`Computed from ${p.total_trades ?? 0} real trades over ${range}`}
            right={sc.rating
              ? <Badge text={`Rating ${sc.rating}`} tone={RATING_TONE[sc.rating] ?? "default"} />
              : <Badge text="not enough data" tone="default" />}>
        <div className="grid-2-1">
          <div>
            <div style={{ fontSize: 13, marginBottom: 10 }}>{sc.summary}</div>
            <ScoreBar label="Profitability" value={sc.scores.profitability} basis={sc.score_basis.profitability} />
            <ScoreBar label="Risk control" value={sc.scores.risk} basis={sc.score_basis.risk} />
            <ScoreBar label="Consistency" value={sc.scores.consistency} basis={sc.score_basis.consistency} />
            <ScoreBar label="Stability" value={sc.scores.stability} basis={sc.score_basis.stability} />
            <ScoreBar label="Confidence (evidence, not profit)" value={sc.scores.confidence} basis={sc.score_basis.confidence} />
            <div className="dim" style={{ fontSize: 10.5, marginTop: 6 }}>
              Hover a score to see the formula behind it.
            </div>
          </div>
          <div>
            <div className="stat-row"><span className="dim">Strategy score</span>
              <b>{sc.strategy_score ?? "—"}{sc.strategy_score != null && " / 100"}</b></div>
            <div className="stat-row"><span className="dim">Net</span>
              <b className={(p.net_pct ?? 0) >= 0 ? "pos" : "neg"}>{num(p.net_pct, 1)}%</b></div>
            <div className="stat-row"><span className="dim">Profit factor</span><b>{num(p.profit_factor)}</b></div>
            <div className="stat-row"><span className="dim">Win rate</span><b>{num(p.win_rate, 1)}%</b></div>
            <div className="stat-row"><span className="dim">Gross profit / loss</span>
              <b><span className="pos">{num(p.gross_profit_r)}R</span> / <span className="neg">{num(p.gross_loss_r)}R</span></b></div>
            <div className="stat-row"><span className="dim">Sharpe / Sortino</span>
              <b>{num(p.sharpe)} / {p.sortino == null ? "—" : num(p.sortino)}</b></div>
            <div className="stat-row"><span className="dim">Max drawdown</span>
              <b className="neg">{num(p.max_drawdown_r)}R</b></div>
            <div className="stat-row"><span className="dim">Avg RR</span><b>{num(p.avg_rr)}</b></div>
            <div className="stat-row"><span className="dim">Avg hold</span><b>{num(p.avg_hold_bars, 1)} bars</b></div>
            {sc.recovery && (
              <div className="stat-row"><span className="dim">Recovery</span>
                <b>{sc.recovery.recovered
                  ? `${sc.recovery.trades_to_recover} trades`
                  : <span className="neg">never recovered</span>}</b></div>
            )}
          </div>
        </div>
      </Card>

      {/* ── strengths / weaknesses / market ── */}
      <div className="grid-2-eq">
        <Card title="Strengths & Weaknesses" subtitle="Each backed by a real statistic">
          {review.evidence?.strengths?.map((f, i) => (
            <div key={`s${i}`} style={{ fontSize: 12.5, marginBottom: 5 }}>
              <span className="pos">✓</span> {f.claim}
              <span className="dim"> — {f.stat}: <b>{String(f.value)}</b></span>
            </div>
          ))}
          {review.evidence?.weaknesses?.map((f, i) => (
            <div key={`w${i}`} style={{ fontSize: 12.5, marginBottom: 5 }}>
              <span className="neg">!</span> {f.claim}
              <span className="dim"> — {f.stat}: <b>{String(f.value)}</b></span>
            </div>
          ))}
        </Card>

        <Card title="Market Analysis" subtitle="From the trades themselves">
          <Bucket title="By market condition" keyName="regime" rows={(review.evidence as any)?.regimes ?? []} />
          <Bucket title="By session" keyName="session" rows={review.evidence?.sessions ?? []} />
          <Bucket title="By day of week" keyName="day" rows={sc.day_of_week} />
          {!!review.evidence?.not_derivable?.length && (
            <div style={{ marginTop: 10 }}>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6 }}>Not answerable from this data</div>
              {review.evidence.not_derivable.map((q, i) => (
                <div key={i} className="dim" style={{ fontSize: 11.5, marginTop: 3 }}>
                  <b>{q.question}</b> — {q.why}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* ── monthly ── */}
      {!!sc.monthly.length && (
        <Card title="Monthly Performance" subtitle={`${sc.monthly.length} month(s) in this window`}>
          <table className="data-table">
            <thead><tr><th>Month</th><th>Trades</th><th>Net R</th><th>Win rate</th></tr></thead>
            <tbody>{sc.monthly.map((m) => (
              <tr key={m.month}>
                <td className="mono">{m.month}</td>
                <td className="mono dim">{m.trades}</td>
                <td className={`mono ${m.net_r >= 0 ? "pos" : "neg"}`}>{m.net_r > 0 ? "+" : ""}{m.net_r}</td>
                <td className="mono dim">{m.win_rate}%</td>
              </tr>
            ))}</tbody>
          </table>
        </Card>
      )}

      {/* ── suggestions ── */}
      <Card title="Optimisation Suggestions"
            subtitle={review.suggestions?.length
              ? "Accept one to test it — your strategy is never changed automatically"
              : "No changes are supported by this data"}>
        {!review.suggestions?.length && (
          <div className="dim" style={{ padding: 10, fontSize: 12.5 }}>
            The backtest shows no addressable weakness worth acting on. Rather than
            offer generic advice, nothing is suggested.
          </div>
        )}
        {review.suggestions?.map((s) => {
          const res = applied[s.id];
          return (
            <div key={s.id} className="builder-rule" style={{ marginBottom: 8, padding: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <b style={{ fontSize: 13 }}>{s.title}</b>
                <Badge text={s.confidence} tone={CONF_TONE[s.confidence] ?? "default"} />
                <button className="chip-btn" style={{ marginLeft: "auto" }}
                        onClick={() => setOpen(open === s.id ? "" : s.id)}>
                  {open === s.id ? "Hide" : "Why?"}
                </button>
                {s.patch ? (
                  <button className="btn btn-soft btn-sm" disabled={applying === s.id}
                          onClick={() => accept(s)}>
                    {applying === s.id ? "Testing…" : "Accept & test"}
                  </button>
                ) : (
                  <span className="dim" style={{ fontSize: 11 }}>manual review</span>
                )}
              </div>
              <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{s.reason}</div>

              {open === s.id && (
                <div style={{ marginTop: 8, fontSize: 11.5 }}>
                  <div className="dim" style={{ textTransform: "uppercase", letterSpacing: .6, fontSize: 10 }}>Evidence</div>
                  {s.evidence.map((e, i) => (
                    <div key={i}>· {e.stat}: <b>{String(e.value)}</b></div>
                  ))}
                  <div style={{ marginTop: 5 }}><b>Expected benefit:</b> {s.expected_benefit}</div>
                  <div style={{ marginTop: 3 }}><b>Trade-offs:</b> {s.tradeoffs}</div>
                  {s.patch && (
                    <div className="mono dim" style={{ marginTop: 5 }}>
                      change: {JSON.stringify(s.patch)}
                    </div>
                  )}
                </div>
              )}

              {/* before / after, on the same window */}
              {res?.available && res.comparison && (
                <div style={{ marginTop: 10, paddingTop: 8, borderTop: "1px solid rgba(255,255,255,.08)" }}>
                  <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6, marginBottom: 4 }}>
                    Original vs optimised — rating {res.before?.scorecard.rating ?? "—"} → {res.after?.scorecard.rating ?? "—"}
                  </div>
                  <table className="data-table">
                    <thead><tr><th>Metric</th><th>Before</th><th>After</th><th>Change</th></tr></thead>
                    <tbody>{res.comparison.rows.map((r) => (
                      <tr key={r.metric}>
                        <td className="dim">{r.metric.replace(/_/g, " ")}</td>
                        <td className="mono">{num(r.before)}</td>
                        <td className="mono">{num(r.after)}</td>
                        <td className={`mono ${(r.delta ?? 0) > 0 ? "pos" : (r.delta ?? 0) < 0 ? "neg" : "dim"}`}>
                          {r.delta == null ? "—" : `${r.delta > 0 ? "+" : ""}${r.delta}`}
                        </td>
                      </tr>
                    ))}</tbody>
                  </table>
                  <button className="btn btn-primary btn-sm" style={{ marginTop: 8 }}
                          onClick={() => { if (res.spec) { onUseOptimised(res.spec); toast("Optimised strategy loaded — re-run the backtest to confirm", "success"); } }}>
                    <Icon name="check" size={12} /> Keep this version
                  </button>
                  <span className="dim" style={{ fontSize: 11, marginLeft: 8 }}>
                    Nothing is saved until you keep it.
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </Card>
    </>
  );
}
