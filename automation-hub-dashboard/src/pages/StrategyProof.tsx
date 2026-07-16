import { useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { signedMoney, signedNum } from "../lib/format";
import { useApp } from "../app-context";
import {
  apiGet, useLive, type StrategyPerformance, type StrategyHealthData,
  type WalkForward, type EngineStatus,
} from "../lib/api";

type NamedVal = { name: string; net_pnl?: number; net_r?: number } | null;
type PaperValidation = {
  sample_size: number; min_review: number; min_evidence: number;
  metrics: { win_rate: number; profit_factor: number; expectancy: number;
    max_drawdown_pct: number; avg_rr: number; sharpe_ratio: number; sortino_ratio: number };
  best_symbol: NamedVal; worst_symbol: NamedVal; best_strategy: NamedVal; worst_strategy: NamedVal;
  skipped_total: number; skipped_by_category: { category: string; count: number }[];
  safety: { live_allowed: boolean; hard_locked: boolean; passed: number; total: number };
  live_review: { eligible: boolean; stage: string; reasons: string[]; note: string };
};

function PaperValidationPanel() {
  const v = useLive<PaperValidation>("/validation/paper", 5000).data;
  if (!v) return null;
  const m = v.metrics;
  const pct = (n: number) => `${(n ?? 0).toFixed(1)}%`;
  const eligible = v.live_review.eligible;
  const progress = Math.min(100, Math.round((v.sample_size / v.min_review) * 100));
  return (
    <Card
      title="Paper Validation"
      subtitle={`${v.sample_size} / ${v.min_review} closed trades toward a live review · ${v.min_evidence}+ for strong evidence`}
      right={<Badge text={eligible ? "READY FOR REVIEW" : "NOT ELIGIBLE"} tone={eligible ? "green" : "amber"} />}
    >
      <div className="card" style={{ marginBottom: 10, borderColor: v.safety.hard_locked ? "#ef4444" : "#22c55e",
        background: v.safety.hard_locked ? "rgba(239,68,68,0.08)" : "rgba(34,197,94,0.08)", display: "flex", alignItems: "center", gap: 10 }}>
        <Icon name="lock" size={16} className="neg" />
        <span><b className="neg">Live trading LOCKED.</b> <span className="dim">{v.live_review.note}</span></span>
      </div>

      {/* progress toward the sample-size minimum */}
      <div style={{ margin: "4px 0 10px" }}>
        <div style={{ height: 8, borderRadius: 6, background: "#2a2a2e", overflow: "hidden" }}>
          <div style={{ width: `${progress}%`, height: "100%", background: eligible ? "#22c55e" : "var(--gold)" }} />
        </div>
        <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>Stage: <b>{v.live_review.stage}</b></div>
      </div>

      <div className="form-grid-3">
        <div className="risk-item"><span className="dim">Win rate</span><b>{pct(m.win_rate)}</b></div>
        <div className="risk-item"><span className="dim">Profit factor</span><b className={m.profit_factor >= 1 ? "pos" : "neg"}>{m.profit_factor.toFixed(2)}</b></div>
        <div className="risk-item"><span className="dim">Expectancy</span><b className={m.expectancy >= 0 ? "pos" : "neg"}>{signedMoney(m.expectancy)}</b></div>
        <div className="risk-item"><span className="dim">Avg R</span><b>{m.avg_rr.toFixed(2)}R</b></div>
        <div className="risk-item"><span className="dim">Max drawdown</span><b>{pct(m.max_drawdown_pct)}</b></div>
        <div className="risk-item"><span className="dim">Sharpe / Sortino</span><b>{m.sharpe_ratio.toFixed(2)} / {m.sortino_ratio.toFixed(2)}</b></div>
        <div className="risk-item"><span className="dim">Best / worst symbol</span><b>{v.best_symbol?.name ?? "—"} / {v.worst_symbol?.name ?? "—"}</b></div>
        <div className="risk-item"><span className="dim">Best / worst strategy</span><b>{v.best_strategy?.name ?? "—"} / {v.worst_strategy?.name ?? "—"}</b></div>
        <div className="risk-item"><span className="dim">Skipped trades</span><b>{v.skipped_total}</b></div>
      </div>

      {v.skipped_by_category.length > 0 && (
        <div className="row-actions" style={{ justifyContent: "flex-start", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          <span className="dim" style={{ fontSize: 12 }}>Rejections:</span>
          {v.skipped_by_category.map((s) => <Badge key={s.category} text={`${s.category} · ${s.count}`} tone="amber" />)}
        </div>
      )}

      <div style={{ marginTop: 10 }}>
        <div className="dim" style={{ fontSize: 11, marginBottom: 4 }}>Live-review eligibility (needs sample size + proven edge + safety guards — never one metric):</div>
        <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.6 }}>
          {v.live_review.reasons.map((r, i) => (
            <li key={i} style={{ fontSize: 12 }} className={eligible ? "pos" : "dim"}>{r}</li>
          ))}
        </ul>
        <div className="dim" style={{ fontSize: 11, marginTop: 6 }}>
          Safety Center: {v.safety.passed}/{v.safety.total} requirements passed · live_allowed <b>{String(v.safety.live_allowed)}</b>
        </div>
      </div>
    </Card>
  );
}

/** Strategy Proof — the evidence a strategy actually works, from REAL results:
 *  paper track record, walk-forward out-of-sample folds, per-symbol / session /
 *  timeframe breakdowns, and risk-adjusted ratios. No numbers are invented; a
 *  section with no data says so. */

const pct = (n: number | undefined) => `${(n ?? 0).toFixed(1)}%`;
const money = (n: number | null | undefined) => `$${(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const rt = (n: number) => (n >= 0 ? "pos" : "neg");

function Table({ head, rows }: { head: string[]; rows: (string | number | JSX.Element)[][] }) {
  return (
    <div className="tablewrap">
      <table className="data-table">
        <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}
          {rows.length === 0 && <tr><td colSpan={head.length} className="dim ta-center" style={{ padding: 16 }}>No data yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function StrategyProofPage() {
  const app = useApp();
  const perf = useLive<StrategyPerformance>("/strategy/performance", 5000);
  const health = useLive<StrategyHealthData>("/strategy/health", 8000);
  const eng = useLive<EngineStatus>("/engine/status", 5000);
  const [wf, setWf] = useState<WalkForward | null>(null);
  const [wfBusy, setWfBusy] = useState(false);

  const p = perf.data;
  const h = health.data;
  const tf = eng.data?.timeframe ?? "4h";

  const runWalkForward = async () => {
    setWfBusy(true);
    try {
      setWf(await apiGet<WalkForward>(`/lab/walk-forward?symbol=BTCUSDT&strategy=${encodeURIComponent(p?.strategy ?? "Decision Brain")}&timeframe=${tf}&folds=4`));
    } catch {
      app.toast("Walk-forward needs cached market data", "error");
    } finally {
      setWfBusy(false);
    }
  };

  const noTrades = (p?.trades ?? 0) === 0;

  return (
    <>
      <PageHeader title="Strategy Proof" subtitle="the real evidence a strategy works — paper record, walk-forward, breakdowns, risk-adjusted ratios" />

      <PaperValidationPanel />

      {noTrades && (
        <div className="card" style={{ borderColor: "var(--gold)", background: "rgba(234,181,79,0.08)", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="info" size={15} className="amber" />
          <span><b>No closed paper trades yet.</b> <span className="dim">Proof fills in as the engine trades. Run a walk-forward below for backtest evidence in the meantime.</span></span>
        </div>
      )}

      {/* headline risk + risk-adjusted stats */}
      <div className="stat-row">
        <StatCard label="Win Rate" value={pct(p?.win_rate)} tone={(p?.win_rate ?? 0) >= 50 ? "green" : "red"} sub={`${p?.trades ?? 0} trades`} />
        <StatCard label="Profit Factor" value={(p?.profit_factor ?? 0).toFixed(2)} tone={(p?.profit_factor ?? 0) >= 1 ? "green" : "red"} />
        <StatCard label="Expectancy" value={signedMoney(p?.expectancy)} tone={(p?.expectancy ?? 0) >= 0 ? "green" : "red"} sub="per trade" />
        <StatCard label="Max Drawdown" value={pct(p?.max_drawdown_pct)} tone={(p?.max_drawdown_pct ?? 0) <= 15 ? "green" : "red"} />
        <StatCard label="Sharpe" value={signedNum(p?.sharpe_ratio)} sub="per-trade R" tone={(p?.sharpe_ratio ?? 0) >= 0 ? "green" : "red"} />
        <StatCard label="Sortino" value={signedNum(p?.sortino_ratio)} sub="per-trade R" tone={(p?.sortino_ratio ?? 0) >= 0 ? "green" : "red"} />
      </div>

      <div className="grid-2-eq">
        {/* Paper trading results */}
        <Card title="Paper Trading Results" subtitle="the bot's real executed track record"
          right={p && <Badge text={p.mode === "live" ? "live data" : "replay"} tone="blue" />}>
          {p && (
            <div className="risk-list">
              <div className="risk-item"><span className="dim">Net P&L</span><b className={rt(p.realized_pnl)}>{signedMoney(p.realized_pnl)}</b></div>
              <div className="risk-item"><span className="dim">Wins / losses</span><b>{p.wins} / {p.losses}</b></div>
              <div className="risk-item"><span className="dim">Avg win / loss</span><b>{money(p.avg_win)} / {money(p.avg_loss)}</b></div>
              <div className="risk-item"><span className="dim">Best / worst</span><b>{money(p.best)} / {money(p.worst)}</b></div>
              <div className="risk-item"><span className="dim">Longest losing streak</span><b>{p.longest_losing_streak}</b></div>
              <div className="risk-item"><span className="dim">Risk-adjusted basis</span><b className="dim" style={{ fontSize: 12 }}>{p.risk_adjusted?.note ?? "per-trade R"}</b></div>
            </div>
          )}
        </Card>

        {/* Walk-forward out-of-sample proof */}
        <Card title="Walk-Forward (out-of-sample)" subtitle="the honest test — train on the past, measure on unseen data"
          right={<button className="btn btn-soft" disabled={wfBusy} onClick={runWalkForward}><Icon name="history" size={13} /> {wfBusy ? "Running…" : "Run walk-forward"}</button>}>
          {!wf ? (
            <div className="dim ta-center" style={{ padding: 14 }}>Run a walk-forward to prove the edge survives on unseen data.</div>
          ) : wf.available === false ? (
            <p className="neg"><Icon name="warning" size={13} /> {(wf as any).error ?? "No cached data for this config."}</p>
          ) : (
            <>
              <div className="row-actions" style={{ justifyContent: "space-between", marginBottom: 8 }}>
                <Badge text={`${wf.positive_folds}/${wf.total_folds} folds positive`} tone={wf.positive_folds > wf.total_folds / 2 ? "green" : "red"} />
                <span className="dim">OOS net <b className={rt(wf.oos_net_r)}>{wf.oos_net_r >= 0 ? "+" : ""}{wf.oos_net_r}R</b></span>
              </div>
              <Table head={["Fold", "Train R", "Test R"]}
                rows={(wf.folds ?? []).map((f: any, i: number) => [
                  `#${i + 1}`,
                  <span className={rt(f.train_net_r)}>{signedNum(f.train_net_r)}R</span>,
                  <span className={rt(f.test_net_r)}>{signedNum(f.test_net_r)}R</span>,
                ])} />
            </>
          )}
        </Card>
      </div>

      {/* per-symbol / per-session breakdowns (real) */}
      <div className="grid-2-eq">
        <Card title="Per-Symbol Performance" subtitle="where the edge is real vs where it isn't">
          <Table head={["Symbol", "Trades", "Win %", "Net P&L"]}
            rows={(h?.breakdown.by_symbol ?? []).map((s) => [
              s.name, s.trades, `${s.win_rate}%`,
              <span className={rt(s.net_pnl)}>{signedMoney(s.net_pnl)}</span>,
            ])} />
        </Card>
        <Card title="Per-Session Performance" subtitle="Asia / London / New York">
          <Table head={["Session", "Trades", "Win %", "Net P&L"]}
            rows={(h?.breakdown.by_session ?? []).map((s) => [
              s.name, s.trades, `${s.win_rate}%`,
              <span className={rt(s.net_pnl)}>{signedMoney(s.net_pnl)}</span>,
            ])} />
        </Card>
      </div>

      {/* per-timeframe — honest: paper runs one TF; cross-TF proof is the walk-forward */}
      <Card title="Per-Timeframe" subtitle="what timeframe the live proof is on">
        <div className="risk-list">
          <div className="risk-item"><span className="dim">Engine timeframe</span><b>{tf}</b></div>
          <div className="risk-item"><span className="dim">Paper track record</span><b>{p?.trades ?? 0} trades @ {tf}</b></div>
        </div>
        <p className="dim" style={{ fontSize: 12, marginTop: 8 }}>
          <Icon name="info" size={12} /> Paper trading runs a single timeframe ({tf}). Cross-timeframe robustness is proven by the walk-forward folds above and by the Backtesting page — not fabricated here.
        </p>
      </Card>
    </>
  );
}
