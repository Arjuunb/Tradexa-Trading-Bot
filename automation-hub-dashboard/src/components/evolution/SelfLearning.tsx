import Card from "../common/Card";
import { Badge } from "../common/ui";
import { useLive } from "../../lib/api";

/** Live self-learning loop — what the bot has taught itself from its OWN
 *  closed trades (services/learning.py), how every gate grades against what
 *  it actually blocked (counterfactual tracker), and any candidate currently
 *  auditioning in shadow / proposed by the self-retune pipeline. */

type LearningReport = {
  updated_at: string | null;
  lessons: { kind: string; key: string; lesson: string }[];
  active_adjustments: Record<string, { lesson?: string; type?: string; expires_at?: string }>;
  evolution: { ts: string; action: string; key: string; lesson: string }[];
};

type CfReport = {
  total_saved_r: number;
  open_virtual_trades: number;
  rules: Record<string, { vetoes_resolved: number; still_open: number; saved_r: number;
    vetoed_win_rate: number | null; verdict: string }>;
};

type ShadowReport = {
  active: boolean; candidate?: string; verdict?: string; detail?: string;
  shadow?: { trades?: number; expectancy_r?: number; net_r?: number };
  live?: { trades?: number; expectancy_r?: number; net_r?: number };
  note?: string;
};

type RetuneReport = { ran?: boolean; verdict?: string; detail?: string; note?: string;
  best_candidate?: Record<string, number>; test_net_r?: { candidate: number; incumbent: number } };

const actionTone = (a: string) =>
  a === "applied" ? "amber" : a === "falsified" ? "red" : "green";
const verdictTone = (v: string) =>
  v === "saving" ? "green" : v === "costing" ? "red" : v === "neutral" ? "default" : "blue";

export default function SelfLearningPanel() {
  const learning = useLive<LearningReport>("/learning/report", 10000);
  const cf = useLive<CfReport>("/counterfactual/report", 10000);
  const shadow = useLive<ShadowReport>("/shadow/report", 10000);
  const retune = useLive<RetuneReport>("/retune/report", 15000);

  const rules = Object.entries(learning.data?.active_adjustments ?? {});
  const grades = Object.entries(cf.data?.rules ?? {});
  const timeline = learning.data?.evolution ?? [];
  const sh = shadow.data;
  const rt = retune.data;

  return (
    <div className="evo-grid">
      <div className="evo-col">
        <Card title="Live Learning Book"
          subtitle="rules the bot taught itself from its own closed trades — bounded, evidenced, expiring"
          right={<Badge text={`${rules.length} in force`} tone={rules.length ? "amber" : "default"} />}>
          {rules.length === 0 ? (
            <div className="dim ta-center" style={{ padding: 14 }}>
              No learned rules in force — it needs ~20 closed trades before the first lessons appear. That is correct, not broken.
            </div>
          ) : (
            <div className="risk-list">
              {rules.map(([key, adj]) => (
                <div key={key} className="risk-item">
                  <span><Badge text={key} tone="amber" /></span>
                  <span className="dim" style={{ fontSize: 12 }}>{adj.lesson ?? adj.type}</span>
                </div>
              ))}
            </div>
          )}
          {timeline.length > 0 && (
            <>
              <div className="dim" style={{ marginTop: 10, fontSize: 12 }}>Evolution timeline</div>
              <div className="risk-list" style={{ marginTop: 4 }}>
                {timeline.slice(-5).reverse().map((h, i) => (
                  <div key={i} className="risk-item">
                    <span><Badge text={h.action} tone={actionTone(h.action)} /> <b style={{ fontSize: 12 }}>{h.key}</b></span>
                    <span className="dim" style={{ fontSize: 11 }}>{h.lesson.slice(0, 90)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
      </div>

      <div className="evo-col">
        <Card title="Gate Grades" subtitle="every veto tracked as a virtual trade — rules that block winners get falsified"
          right={cf.data ? <Badge text={`saved ${cf.data.total_saved_r >= 0 ? "+" : ""}${cf.data.total_saved_r}R`}
            tone={cf.data.total_saved_r >= 0 ? "green" : "red"} /> : undefined}>
          {grades.length === 0 ? (
            <div className="dim ta-center" style={{ padding: 14 }}>
              No vetoes graded yet — grades appear once gates start blocking trades
              ({cf.data?.open_virtual_trades ?? 0} still resolving).
            </div>
          ) : (
            <div className="risk-list">
              {grades.map(([rule, s]) => (
                <div key={rule} className="risk-item">
                  <span style={{ fontSize: 12 }}><b>{rule}</b> <span className="dim">×{s.vetoes_resolved}{s.still_open ? ` (+${s.still_open} open)` : ""}</span></span>
                  <span>
                    <span className={s.saved_r >= 0 ? "green" : "red"} style={{ marginRight: 8 }}>
                      {s.saved_r >= 0 ? "+" : ""}{s.saved_r}R
                    </span>
                    <Badge text={s.verdict} tone={verdictTone(s.verdict)} />
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Shadow Audition & Self-Retune"
          subtitle="candidates prove themselves on live candles before you promote anything">
          {sh?.active ? (
            <div className="risk-list">
              <div className="risk-item"><span className="dim">Candidate</span> <b>{sh.candidate}</b></div>
              <div className="risk-item"><span className="dim">Shadow</span>
                <span>{sh.shadow?.trades ?? 0} trades · {sh.shadow?.expectancy_r != null ? `${sh.shadow.expectancy_r >= 0 ? "+" : ""}${sh.shadow.expectancy_r}R avg` : "—"}</span></div>
              <div className="risk-item"><span className="dim">Incumbent (same period)</span>
                <span>{sh.live?.trades ?? 0} trades · {sh.live?.expectancy_r != null ? `${sh.live.expectancy_r >= 0 ? "+" : ""}${sh.live.expectancy_r}R avg` : "—"}</span></div>
              <div className="risk-item"><span className="dim">Verdict</span>
                <Badge text={sh.verdict ?? "collecting"}
                  tone={sh.verdict === "promote" ? "green" : sh.verdict === "reject" ? "red" : "blue"} /></div>
              {sh.detail && <p className="dim" style={{ marginTop: 6, fontSize: 12 }}>{sh.detail}</p>}
            </div>
          ) : (
            <div className="dim" style={{ fontSize: 13 }}>
              No shadow running. The nightly self-retune starts one automatically when the live
              record diverges from the backtest promise{rt?.verdict ? <> — last retune: <Badge
                text={rt.verdict} tone={rt.verdict === "candidate-found" ? "green" : "default"} />
                {rt.detail && <span> {rt.detail}</span>}</> : "."}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
