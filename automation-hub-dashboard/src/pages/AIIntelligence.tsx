import { useMemo, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { useLive, type AIAnalysis, type AIProfile } from "../lib/api";

const CONF_TONE: Record<string, string> = {
  "Very High": "green", High: "green", Medium: "amber", Low: "red", "Very Low": "red",
};
const DECISION_TONE: Record<string, string> = { BUY: "green", SELL: "red", WAIT: "amber", SKIP: "red" };
const money = (n?: number | null) => (n == null ? "—" : `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const TFS = ["15m", "1h", "4h", "1d"] as const;
const SIDES = [["", "Auto"], ["long", "Long"], ["short", "Short"]] as const;

export default function AIIntelligencePage() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [tf, setTf] = useState<(typeof TFS)[number]>("1h");
  const [side, setSide] = useState("");
  const [lev, setLev] = useState(1);
  const [input, setInput] = useState("BTCUSDT");

  const qs = `symbol=${encodeURIComponent(symbol)}&timeframe=${tf}${side ? `&side=${side}` : ""}&leverage=${lev}`;
  const { data: a } = useLive<AIAnalysis>(`/ai/analyze?${qs}`, 20000);
  const { data: profile } = useLive<AIProfile>("/ai/profile", 30000);

  const ma = a?.market_analysis;
  const bias = ma?.available ? ma.bias : "—";
  const trendStrength = ma?.available ? ma.trend?.strength_label : "—";
  const risk = a?.risk_analysis;

  const scoreColor = useMemo(() => {
    const s = a?.overall_score ?? 0;
    return s >= 70 ? "var(--green)" : s >= 55 ? "var(--amber, #f59e0b)" : "var(--red)";
  }, [a]);

  const apply = () => setSymbol(input.trim().toUpperCase() || "BTCUSDT");

  return (
    <>
      <PageHeader title="AI Trading Intelligence"
        subtitle="On-demand pre-trade analysis — setup score, confidence, explanation and risk, composed from the engine's own reads" />

      {/* controls */}
      <div className="toolbar" style={{ gap: 8, flexWrap: "wrap" }}>
        <div className="search" style={{ maxWidth: 220 }}>
          <Icon name="search" size={15} className="search-icon" />
          <input value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && apply()} placeholder="Symbol e.g. BTCUSDT" />
        </div>
        <button className="btn btn-soft" onClick={apply}>Analyze</button>
        <div className="chips">{TFS.map((t) => <button key={t} className={`chip-btn ${tf === t ? "active" : ""}`} onClick={() => setTf(t)}>{t}</button>)}</div>
        <div className="chips">{SIDES.map(([v, l]) => <button key={v} className={`chip-btn ${side === v ? "active" : ""}`} onClick={() => setSide(v)}>{l}</button>)}</div>
        <div className="chips">{[1, 5, 10, 20].map((x) => <button key={x} className={`chip-btn ${lev === x ? "active" : ""}`} onClick={() => setLev(x)}>{x}x</button>)}</div>
      </div>

      {/* headline widgets */}
      <div className="stat-row">
        <StatCard label="Decision" value={a?.decision ?? "—"} tone={(DECISION_TONE[a?.decision ?? ""] ?? "default") as never}
          sub={a?.side ? `${a.side} · ${a.symbol}` : a?.symbol} />
        <StatCard label="AI Confidence" value={a?.confidence_level ?? "—"} tone={(CONF_TONE[a?.confidence_level ?? ""] ?? "default") as never}
          sub={a ? `${a.confidence_pct}%` : ""} />
        <StatCard label="Setup Score" value={a ? `${a.overall_score}/100` : "—"} color={scoreColor}
          sub={a?.engine_score != null ? `engine gate ${a.engine_score}` : ""} />
        <StatCard label="Market Bias" value={bias} sub={`trend ${trendStrength}`} />
        <StatCard label="Min Score" value={a ? String(a.min_score) : "—"} sub={a?.allowed ? "setup qualifies" : "below threshold"}
          tone={a?.allowed ? "green" : "amber"} />
      </div>

      <div className="grid-2-eq">
        {/* score breakdown */}
        <Card title="Setup Score" subtitle={`${a?.overall_score ?? 0} / 100 — ${a?.confidence_level ?? ""}`}>
          {(a?.score_breakdown ?? []).map((c) => {
            const pct = (c.score / c.max) * 100;
            const col = pct >= 75 ? "var(--green)" : pct >= 50 ? "var(--amber, #f59e0b)" : "var(--red)";
            return (
              <div key={c.category} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 4 }}>
                  <span className="dim">{c.category}</span><b>{c.score}/{c.max}</b>
                </div>
                <div style={{ height: 7, borderRadius: 6, background: "rgba(255,255,255,0.06)" }}>
                  <div style={{ width: `${pct}%`, height: "100%", borderRadius: 6, background: col }} />
                </div>
              </div>
            );
          })}
          {!a?.score_breakdown?.length && <div className="dim" style={{ padding: 10 }}>Analyzing…</div>}
        </Card>

        {/* explanation */}
        <Card title="AI Explanation" subtitle={a?.recommendation ?? ""}>
          <div style={{ marginBottom: 8 }}>
            <Badge text={a?.decision ?? "—"} tone={(DECISION_TONE[a?.decision ?? ""] ?? "default") as never} />
            {a?.side && <span className="dim" style={{ marginLeft: 8 }}>{a.side} · confidence {a.confidence_pct}%</span>}
          </div>
          <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, margin: "8px 0 4px" }}>Reasons</div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.6 }}>
            {(a?.reasons ?? []).map((r, i) => <li key={i}>{r}</li>)}
            {!a?.reasons?.length && <li className="dim">No confirming reasons yet.</li>}
          </ul>
          {!!a?.failed_checks?.length && (
            <>
              <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, margin: "10px 0 4px" }}>Not confirmed</div>
              <div className="chips">{a.failed_checks.map((f) => <Badge key={f} text={f} tone="red" />)}</div>
            </>
          )}
        </Card>
      </div>

      {/* risk analysis */}
      <Card title="Risk Analysis" subtitle={risk?.warning ?? "Pre-trade risk for the proposed setup"}>
        {!risk ? <div className="dim" style={{ padding: 10 }}>No directional setup — pick Long/Short or wait for a bias.</div> : (
          <>
            {risk.warning && <div className="banner" style={{ marginBottom: 10, borderColor: "rgba(239,68,68,0.4)", background: "rgba(239,68,68,0.08)" }}>
              <Icon name="warning" size={14} className="neg" /> {risk.warning}</div>}
            <div className="stat-row">
              <StatCard label="Max Loss" value={money(risk.max_loss)} tone="red" sub={`${risk.risk_pct}% of equity`} />
              <StatCard label="Expected Profit" value={money(risk.expected_profit)} tone="green" sub={`RR ${risk.risk_reward}`} />
              <StatCard label="Margin Used" value={money(risk.margin_used)} sub={`${risk.leverage}x leverage`} />
              <StatCard label="Liquidation" value={risk.liquidation_price != null ? money(risk.liquidation_price) : "— (spot)"}
                tone={risk.liquidation_price != null ? "amber" : "default"} />
              <StatCard label="Exposure" value={`${risk.portfolio_exposure_pct}%`} tone={risk.excessive ? "red" : "default"} sub="of equity" />
            </div>
            {a?.setup && <div className="detail-grid" style={{ marginTop: 12 }}>
              <div><span className="dim">Entry</span><b>{money(a.setup.entry)}</b></div>
              <div><span className="dim">Stop</span><b>{money(a.setup.stop)}</b></div>
              <div><span className="dim">Target</span><b>{money(a.setup.target)}</b></div>
            </div>}
          </>
        )}
      </Card>

      {/* trader profile */}
      <div className="grid-2-eq">
        <Card title="Your Trading Profile" subtitle={profile?.note ?? ""}>
          <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>Strengths</div>
          <ul style={{ margin: "0 0 10px", paddingLeft: 18, fontSize: 13, lineHeight: 1.6 }}>
            {(profile?.strengths ?? []).map((s, i) => <li key={i} className="pos">{s}</li>)}
            {!profile?.strengths?.length && <li className="dim">Building as trades close…</li>}
          </ul>
          <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>Weaknesses</div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.6 }}>
            {(profile?.weaknesses ?? []).map((w, i) => <li key={i} className="neg">{w}</li>)}
            {!profile?.weaknesses?.length && <li className="dim">None flagged yet.</li>}
          </ul>
        </Card>
        <Card title="Market Read" subtitle={`${a?.symbol ?? ""} · ${a?.timeframe ?? ""}${a?.data_source ? ` · ${a.data_source}` : ""}`}>
          {!ma?.available ? <div className="dim" style={{ padding: 10 }}>{ma?.note ?? "Analyzing…"}</div> : (
            <div className="detail-grid">
              <div><span className="dim">Bias</span><b>{ma.bias}</b></div>
              <div><span className="dim">Trend strength</span><b>{ma.trend?.strength_label}</b></div>
              <div><span className="dim">Structure</span><b>{ma.structure?.state}</b></div>
              <div><span className="dim">Break of structure</span><b>{String(ma.structure?.break_of_structure)}</b></div>
              <div><span className="dim">Change of character</span><b>{ma.structure?.change_of_character ? "yes" : "no"}</b></div>
              <div><span className="dim">Liquidity sweep</span><b>{String(ma.liquidity?.sweep)}</b></div>
              <div><span className="dim">Volume</span><b>{ma.volume?.label}</b></div>
              <div><span className="dim">Volatility</span><b>{ma.volatility?.label}</b></div>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
