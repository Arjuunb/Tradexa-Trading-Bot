import Icon from "../common/Icon";
import Sparkline from "../chart/Sparkline";
import { Badge } from "../common/ui";
import { useLive, type EngineStatus, type PaperAccount, type RiskSummary, type EquityCurveData, type SystemStatus } from "../../lib/api";

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const usd = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

/** Tradexa command-center hero — live account equity, P&L, engine state and a
 *  mini equity curve in one premium banner. Real backend data only. */
export default function DashboardHero() {
  const acct = useLive<PaperAccount>("/paper/account", 2000);
  const engine = useLive<EngineStatus>("/engine/status", 2000);
  const risk = useLive<RiskSummary>("/risk/summary", 2000);
  const eq = useLive<EquityCurveData>("/paper/equity-curve", 4000);
  const sys = useLive<SystemStatus>("/system/status", 4000);
  const a = acct.data, e = engine.data, r = risk.data;
  const curve = (eq.data?.points ?? []).map((p) => p.equity);
  const pnl = a?.realized_pnl ?? 0;
  const exposure = (r?.exposure_pct ?? 0) * 100;
  const expTone = exposure >= 90 ? "red" : exposure >= 60 ? "amber" : "green";

  return (
    <div className="dash-hero">
      <div className="hero-left">
        <span className="hero-eyebrow">PAPER ACCOUNT · SIMULATION</span>
        <div className="hero-equity">{usd(a?.balance ?? 0)}</div>
        <div className="hero-row">
          <Badge text={`${pnl >= 0 ? "+" : ""}${money(pnl)} realized`} tone={pnl >= 0 ? "green" : "red"} />
          <span className="hero-dot" />
          <span className={e?.running ? "pos" : "neg"} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontWeight: 600 }}>
            <span className={`dot ${e?.running ? "online" : "offline"}`} /> Engine {e?.running ? "running" : "stopped"}
          </span>
          <span className="hero-dot" />
          <span className="dim">{sys.data?.strategy ?? "—"} · {e?.timeframe ?? "—"}</span>
        </div>
      </div>

      <div className="hero-mid">
        <div className="hero-stat">
          <span className="hero-stat-label">Exposure</span>
          <b className={expTone === "green" ? "pos" : expTone === "amber" ? "amber" : "neg"}>{exposure.toFixed(0)}%</b>
          <span className="hero-bar"><span className="hero-bar-fill" style={{ width: `${Math.min(100, exposure)}%`, background: `var(--${expTone === "green" ? "green" : expTone === "amber" ? "gold" : "red"})` }} /></span>
        </div>
        <div className="hero-stat">
          <span className="hero-stat-label">Open positions</span>
          <b>{a?.open_positions ?? 0}</b>
        </div>
        <div className="hero-stat">
          <span className="hero-stat-label">Symbols</span>
          <b>{e?.symbols?.length ?? 0}</b>
          <span className="dim" style={{ fontSize: 10 }}>{(e?.symbols ?? []).map((s) => s.replace("USDT", "")).join(" · ") || "—"}</span>
        </div>
      </div>

      <div className="hero-right">
        <span className="hero-stat-label" style={{ display: "flex", alignItems: "center", gap: 5 }}><Icon name="chart" size={12} /> Equity</span>
        {curve.length > 1
          ? <div className="hero-spark"><Sparkline data={curve} color={pnl >= 0 ? "#22c55e" : "#ef4444"} height={56} /></div>
          : <span className="dim" style={{ fontSize: 12 }}>Awaiting trades…</span>}
      </div>
    </div>
  );
}
