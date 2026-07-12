import { Fragment, useMemo, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard, EmptyState } from "../components/common/ui";
import { useLive, apiPatchJson, apiDelete, API_BASE } from "../lib/api";

/** Memory — the AI's permanent long-term memory of every trade. Composed from
 *  REAL captured data (decision journal + decision object + ledger); fields the
 *  bot never measured are shown as "not captured" / "Not checked", never faked.
 *  Nothing here enables live trading; it is a record + coaching surface. */

type Mem = {
  trade_id: string; closed_at: string | null; symbol: string; side: string;
  strategy: string; timeframe: string; result: string | null; grade: string | null;
  pnl: number | null; actual_rr: number | null; session: string; weekday: string;
  notes: string; sections?: Record<string, Record<string, unknown>>;
};
type Bucket = Record<string, unknown> & {
  trades: number; win_rate: number; expectancy: number; avg_rr: number; pnl: number;
};
type Insights = {
  sample: number; overall: Bucket; sharpe_ratio: number; sortino_ratio: number;
  max_drawdown_abs: number; avg_hold_seconds: number | null;
  by_symbol: Bucket[]; by_strategy: Bucket[]; by_session: Bucket[];
  by_weekday: Bucket[]; by_setup_grade: Bucket[];
  mistakes: { mistake: string; count: number; loss_attributed: number; repeated: boolean }[];
  winning_patterns: Bucket[]; evidence_note: string;
  coaching: { statement: string; stage: string; metric: unknown }[];
};
type Review = { period: string; period_key: string; created_at: string; report: Insights };

const money = (n: number | null | undefined) => `$${(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const signed = (n: number | null | undefined) => `${(n ?? 0) >= 0 ? "+" : ""}${n ?? 0}`;
const gradeTone = (g?: string | null) => (g === "A" || g === "B" ? "green" : g === "C" ? "amber" : g ? "red" : "default");
const resultTone = (r?: string | null) => (r === "win" ? "green" : r === "loss" ? "red" : "default");
const stageTone = (s: string) =>
  s === "evidence" ? "green" : s === "building" ? "amber" : s === "early-signal" ? "blue" : "default";

const RESULTS = ["all", "win", "loss"] as const;
const PERIODS = ["nightly", "weekly", "monthly", "yearly"] as const;

export default function MemoryPage() {
  const [query, setQuery] = useState("");
  const [asked, setAsked] = useState("");
  const [result, setResult] = useState<(typeof RESULTS)[number]>("all");
  const [open, setOpen] = useState<string | null>(null);
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("nightly");
  const [toast, setToast] = useState<string>("");

  // when the user "asks", route through the NL endpoint; otherwise plain list
  const qs = new URLSearchParams({ limit: "200" });
  if (result !== "all") qs.set("result", result);
  const askPath = asked
    ? `/trade-memory/ask?q=${encodeURIComponent(asked)}&limit=200`
    : `/trade-memory/trades?${qs.toString()}`;
  const listing = useLive<{ trades: Mem[]; total?: number; answer?: string; kind?: string }>(askPath, 5000);
  const insights = useLive<Insights>("/trade-memory/insights", 8000);
  const reviews = useLive<{ reviews: Review[] }>(`/trade-memory/reviews?period=${period}`, 10000);

  const offline = listing.error && !listing.data;
  const rows = listing.data?.trades ?? [];
  const ins = insights.data;

  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(""), 2400); };

  const lessons = useMemo(() => rows
    .map((m) => ({ m, l: (m.sections?.trade_outcome as Record<string, unknown> | undefined)?.lessons_learned as string | undefined }))
    .filter((x) => x.l && !String(x.l).startsWith("not captured")), [rows]);

  return (
    <div className="page">
      <PageHeader
        title="Memory"
        subtitle="The bot's permanent memory of every trade — searchable, with pattern recognition and data-driven coaching. Composed from real data; uncaptured fields are marked honestly."
      />

      {offline && (
        <div className="card" style={{ borderColor: "#ef4444", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="warning" size={16} className="neg" />
          <span className="dim">Memory API offline — start the backend (<span className="mono">{API_BASE}</span>).
            Every closed paper trade is remembered here automatically.</span>
        </div>
      )}
      {toast && <div className="toast success" role="status">{toast}</div>}

      {/* ── Search / ask bar ─────────────────────────────────────────── */}
      <Card>
        <form
          onSubmit={(e) => { e.preventDefault(); setAsked(query.trim()); }}
          style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
        >
          <div className="search" style={{ flex: 1, minWidth: 260 }}>
            <Icon name="info" size={15} className="search-icon" />
            <input
              placeholder='Ask — "show all losing BTC trades", "which setup has the highest expectancy?", "why am I losing on Mondays?"'
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search memory"
            />
          </div>
          <button className="btn btn-primary" type="submit"><Icon name="info" size={14} /> Search</button>
          {asked && (
            <button className="btn btn-ghost" type="button" onClick={() => { setAsked(""); setQuery(""); }}>Clear</button>
          )}
        </form>
        {asked && listing.data?.answer && (
          <p style={{ marginTop: 10, marginBottom: 0 }}>
            <Badge text={listing.data.kind ?? "search"} tone="blue" /> {listing.data.answer}
          </p>
        )}
      </Card>

      {/* ── Knowledge base (real stats) ──────────────────────────────── */}
      <div className="stat-row">
        <StatCard label="Trades remembered" value={String(listing.data?.total ?? ins?.sample ?? 0)}
                  sub="forever unless deleted" />
        <StatCard label="Win rate" value={ins ? `${ins.overall.win_rate}%` : "—"}
                  sub={ins ? `${ins.overall.trades} closed` : ""} tone={ins && ins.overall.win_rate >= 50 ? "green" : "default"} />
        <StatCard label="Expectancy" value={ins ? signed(ins.overall.expectancy) : "—"}
                  sub="per trade ($)" tone={ins && ins.overall.expectancy >= 0 ? "green" : "red"} />
        <StatCard label="Sharpe · Sortino" value={ins ? `${ins.sharpe_ratio} · ${ins.sortino_ratio}` : "—"}
                  sub="per-trade R basis" />
      </div>

      {ins && (
        <Card title="AI Knowledge Base — data-driven coaching">
          <p className="dim" style={{ marginTop: 0 }}>{ins.evidence_note}</p>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {ins.coaching.map((c, i) => (
              <li key={i} style={{ marginBottom: 8 }}>
                <Badge text={c.stage} tone={stageTone(c.stage)} /> <span>{c.statement}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* ── Winning patterns + Mistake library ──────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card title="Winning Patterns">
          {ins && ins.winning_patterns.length ? (
            <div className="tablewrap"><table className="data-table">
              <thead><tr><th>Setup grade</th><th>Trades</th><th>Win %</th><th>Expectancy</th><th>Avg RR</th></tr></thead>
              <tbody>
                {ins.winning_patterns.map((b, i) => (
                  <tr key={i}>
                    <td><Badge text={String(b.grade ?? "?")} tone={gradeTone(String(b.grade)) as never} /></td>
                    <td>{b.trades}</td><td>{b.win_rate}%</td>
                    <td className={b.expectancy >= 0 ? "pos" : "neg"}>{signed(b.expectancy)}</td>
                    <td>{b.avg_rr}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          ) : <EmptyState text="No proven winning pattern yet (needs ≥ 5 trades in a bucket)." />}
        </Card>
        <Card title="Mistake Library">
          {ins && ins.mistakes.length ? (
            <div className="tablewrap"><table className="data-table">
              <thead><tr><th>Mistake</th><th>Count</th><th>Loss</th><th></th></tr></thead>
              <tbody>
                {ins.mistakes.map((m, i) => (
                  <tr key={i}>
                    <td>{m.mistake}</td><td>{m.count}</td>
                    <td className="neg">{money(m.loss_attributed)}</td>
                    <td>{m.repeated && <Badge text="repeated" tone="red" />}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          ) : <EmptyState text="No mistakes recorded — clean process so far." />}
        </Card>
      </div>

      {/* ── Breakdowns: session / weekday ───────────────────────────── */}
      {ins && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card title="By Session"><Breakdown rows={ins.by_session} label="session" k="session" /></Card>
          <Card title="By Weekday"><Breakdown rows={ins.by_weekday} label="weekday" k="weekday" /></Card>
        </div>
      )}

      {/* ── Trade timeline ──────────────────────────────────────────── */}
      <Card title="Trade Timeline">
        <div className="chips" style={{ marginBottom: 10 }}>
          {RESULTS.map((r) => (
            <button key={r} className={`chip-btn ${result === r ? "active" : ""}`} type="button"
                    onClick={() => setResult(r)}>{r}</button>
          ))}
        </div>
        {rows.length === 0 ? (
          <EmptyState text="No remembered trades yet. Every closed paper trade is stored here automatically." />
        ) : (
          <div className="tablewrap"><table className="data-table">
            <thead>
              <tr><th></th><th>Closed</th><th>Symbol</th><th>Side</th><th>Result</th>
                <th>Grade</th><th>RR</th><th>PnL</th><th>Session</th><th>Weekday</th></tr>
            </thead>
            <tbody>
              {rows.map((m) => {
                const isOpen = open === m.trade_id;
                return (
                  <Fragment key={m.trade_id}>
                    <tr>
                      <td>
                        <button className="btn btn-ghost btn-sm" aria-expanded={isOpen}
                                onClick={() => setOpen(isOpen ? null : m.trade_id)}>
                          <Icon name="chevron" size={12} className={isOpen ? "rot-180" : undefined} /> View
                        </button>
                      </td>
                      <td className="dim">{(m.closed_at ?? "").slice(0, 16).replace("T", " ")}</td>
                      <td>{m.symbol}</td>
                      <td className="dim">{m.side}</td>
                      <td><Badge text={m.result ?? "—"} tone={resultTone(m.result) as never} /></td>
                      <td><Badge text={m.grade ?? "—"} tone={gradeTone(m.grade) as never} /></td>
                      <td>{m.actual_rr ?? "—"}</td>
                      <td className={(m.pnl ?? 0) >= 0 ? "pos" : "neg"}>{money(m.pnl)}</td>
                      <td className="dim">{m.session}</td>
                      <td className="dim">{m.weekday}</td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={10} style={{ background: "var(--surface-2, #121214)", padding: 0 }}>
                          <MemoryDetail id={m.trade_id} onNote={flash}
                                        onDelete={() => { flash("Trade forgotten."); setOpen(null); listing.refetch(); }} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table></div>
        )}
      </Card>

      {/* ── Lessons timeline ────────────────────────────────────────── */}
      <Card title="Lessons Timeline">
        {lessons.length ? (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {lessons.map(({ m, l }) => (
              <li key={m.trade_id} style={{ marginBottom: 6 }}>
                <span className="dim">{(m.closed_at ?? "").slice(0, 10)} · {m.symbol}</span> — {l}
              </li>
            ))}
          </ul>
        ) : <EmptyState text="No lessons captured yet." />}
      </Card>

      {/* ── Reviews ─────────────────────────────────────────────────── */}
      <Card title="Reviews">
        <div className="chips" style={{ marginBottom: 10 }}>
          {PERIODS.map((p) => (
            <button key={p} className={`chip-btn ${period === p ? "active" : ""}`} type="button"
                    onClick={() => setPeriod(p)}>{p}</button>
          ))}
        </div>
        {reviews.data?.reviews?.length ? (
          <div className="tablewrap"><table className="data-table">
            <thead><tr><th>Period</th><th>Trades</th><th>Win %</th><th>Expectancy</th><th>Sharpe</th><th>Max DD</th></tr></thead>
            <tbody>
              {reviews.data.reviews.map((r) => (
                <tr key={`${r.period}-${r.period_key}`}>
                  <td>{r.period_key}</td>
                  <td>{r.report?.overall?.trades ?? 0}</td>
                  <td>{r.report?.overall?.win_rate ?? 0}%</td>
                  <td className={(r.report?.overall?.expectancy ?? 0) >= 0 ? "pos" : "neg"}>
                    {signed(r.report?.overall?.expectancy)}
                  </td>
                  <td>{r.report?.sharpe_ratio ?? 0}</td>
                  <td className="neg">{money(r.report?.max_drawdown_abs)}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        ) : <EmptyState text={`No ${period} reviews yet — they generate nightly (or run on demand).`} />}
      </Card>

      <p className="dim" style={{ fontSize: 12, marginTop: 8 }}>
        Search is honest local retrieval (full-text + feature-vector similarity), not an LLM embedding model.
        Coaching percentages are computed from real trades and sample-gated. API: <span className="mono">{API_BASE}/trade-memory/*</span>
      </p>
    </div>
  );
}

function Breakdown({ rows, label, k }: { rows: Bucket[]; label: string; k: string }) {
  if (!rows.length) return <EmptyState text={`No ${label} data yet.`} />;
  return (
    <div className="tablewrap"><table className="data-table">
      <thead><tr><th>{label}</th><th>Trades</th><th>Win %</th><th>Expectancy</th></tr></thead>
      <tbody>
        {rows.map((b, i) => (
          <tr key={i}>
            <td>{String(b[k] ?? "—")}</td><td>{b.trades}</td><td>{b.win_rate}%</td>
            <td className={b.expectancy >= 0 ? "pos" : "neg"}>{`${b.expectancy >= 0 ? "+" : ""}${b.expectancy}`}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );
}

function MemoryDetail({ id, onNote, onDelete }: { id: string; onNote: (m: string) => void; onDelete: () => void }) {
  const full = useLive<Mem>(`/trade-memory/${id}`, 0);
  const sim = useLive<{ similar: { trade_id: string; symbol: string; side: string; result: string; similarity: number }[] }>(`/trade-memory/similar/${id}`, 0);
  const [note, setNote] = useState<string | null>(null);
  const m = full.data;
  const s = m?.sections ?? {};
  const noteVal = note ?? (m?.notes ?? "");

  const saveNote = async () => {
    try { await apiPatchJson(`/trade-memory/${id}/notes`, { notes: noteVal }); onNote("Note saved."); }
    catch { onNote("Could not save note (secret required)."); }
  };
  const forget = async () => {
    if (!window.confirm("Permanently forget this trade? This is the only way a memory is removed.")) return;
    try { await apiDelete(`/trade-memory/${id}`); onDelete(); }
    catch { onNote("Could not delete (secret required)."); }
  };

  if (!m) return <p className="dim" style={{ padding: 16 }}>Loading memory…</p>;
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Section title="1 · Trade Information" data={s.trade_information} />
        <Section title="2 · Market Context" data={s.market_context} />
        <Section title="3 · Technical Analysis" data={s.technical_analysis} />
        <Section title="4 · Strategy" data={s.strategy} />
        <Section title="5 · Execution" data={s.execution} />
        <Section title="7 · Trade Outcome" data={s.trade_outcome} />
        <Section title="8 · AI Reflection" data={s.ai_reflection} />
      </div>

      <div style={{ marginTop: 12 }}>
        <label className="dim" htmlFor={`note-${id}`}>6 · Emotion &amp; Journal (your note)</label>
        <textarea id={`note-${id}`} rows={2} style={{ width: "100%", marginTop: 4 }}
                  placeholder='e.g. "FOMO — I entered early"' value={noteVal}
                  onChange={(e) => setNote(e.target.value)} />
        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <button className="btn btn-primary btn-sm" onClick={saveNote}>Save note</button>
          <button className="btn btn-warn btn-sm" onClick={forget}>Forget trade</button>
        </div>
      </div>

      {sim.data?.similar?.length ? (
        <div style={{ marginTop: 12 }}>
          <p className="dim" style={{ margin: "0 0 4px" }}>Similar trades</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {sim.data.similar.map((x) => (
              <Badge key={x.trade_id} tone={(x.result === "win" ? "green" : "red") as never}
                     text={`${x.symbol} ${x.side} · ${(x.similarity * 100).toFixed(0)}%`} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Section({ title, data }: { title: string; data: unknown }) {
  const obj = (data ?? {}) as Record<string, unknown>;
  return (
    <div>
      <h4 style={{ margin: "0 0 6px" }}>{title}</h4>
      <table className="data-table"><tbody>
        {Object.entries(obj).map(([k, v]) => (
          <tr key={k}>
            <td className="dim" style={{ paddingRight: 10, verticalAlign: "top", whiteSpace: "normal" }}>{k.replace(/_/g, " ")}</td>
            <td style={{ whiteSpace: "normal" }}>{fmt(v)}</td>
          </tr>
        ))}
      </tbody></table>
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length ? v.map((x) => fmt(x)).join("; ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
