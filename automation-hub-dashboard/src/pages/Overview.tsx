import type { Bot } from "../types";
import Card from "../components/common/Card";
import MetricCards from "../components/cards/MetricCards";
import EquityCurve from "../components/chart/EquityCurve";
import Icon from "../components/common/Icon";
import { Badge } from "../components/common/ui";
import {
  useLive, hhmmss,
  type AlertRow, type LedgerPosition, type LogRow, type RiskSummary,
} from "../lib/api";

interface OverviewProps { bots: Bot[]; onToggle: (id: string) => void; onCreate: () => void; }

const money = (n: number | null | undefined) => `${(n ?? 0) >= 0 ? "+" : "-"}$${Math.abs(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const lvlTone = (l: string) => ({ info: "blue", warning: "amber", error: "red", critical: "red" }[l] as any) ?? "default";

// All data here is live from the backend (paper simulation). No mock widgets.
export default function Overview(_props: OverviewProps) {
  const risk = useLive<RiskSummary>("/risk/summary", 2500);
  const positions = useLive<LedgerPosition[]>("/paper/positions", 2500);
  const logs = useLive<LogRow[]>("/ledger/logs?limit=12", 2500);
  const alerts = useLive<AlertRow[]>("/ledger/alerts?limit=8", 4000);
  const r = risk.data;

  return (
    <>
      <MetricCards />

      <div className="grid-mid">
        <Card title="Equity Curve" subtitle="paper · realized P&L" className="equity-card">
          <div className="equity-chart"><EquityCurve /></div>
        </Card>

        <Card title="Risk Exposure">
          {r ? (
            <div className="risk-list">
              <Row k="Exposure" v={`${(r.exposure_pct * 100).toFixed(1)}% / ${(r.exposure_limit_pct * 100).toFixed(0)}%`} />
              <Row k="Open positions" v={`${r.open_positions} / ${r.max_open_positions}`} />
              <Row k="Realized P&L" v={money(r.realized_pnl)} tone={r.realized_pnl >= 0 ? "pos" : "neg"} />
              <Row k="Equity" v={`$${r.equity.toLocaleString(undefined, { maximumFractionDigits: 2 })}`} />
              <Row k="Risk-blocked" v={String(r.rejections)} />
              <Row k="Trading state" v={r.trading_state} tone={r.trading_state === "Active" ? "pos" : "neg"} />
            </div>
          ) : <div className="dim">{risk.error ? "Backend not reachable." : "Loading…"}</div>}
        </Card>
      </div>

      <div className="grid-bottom">
        <Card title="Open Positions">
          <div className="tablewrap">
            <table className="data-table">
              <thead><tr><th>Symbol</th><th>Side</th><th>Size</th><th>Entry</th></tr></thead>
              <tbody>
                {(positions.data ?? []).map((p) => (
                  <tr key={p.id}>
                    <td><b>{p.symbol}</b></td>
                    <td><Badge text={p.side} tone={p.side === "long" ? "green" : "red"} /></td>
                    <td>{p.size.toFixed(6)}</td><td>{p.entry.toLocaleString()}</td>
                  </tr>
                ))}
                {(positions.data?.length ?? 0) === 0 && <tr><td colSpan={4} className="dim ta-center" style={{ padding: 14 }}>No open positions.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Recent Decisions">
          <ul className="activity">
            {(logs.data ?? []).map((l) => (
              <li key={l.id}><span className="dim mono">{hhmmss(l.ts)}</span> <b>{l.symbol || l.stage}</b> {l.message}</li>
            ))}
            {(logs.data?.length ?? 0) === 0 && <li className="dim">No decisions yet.</li>}
          </ul>
        </Card>

        <Card title="Recent Alerts">
          <ul className="activity">
            {(alerts.data ?? []).map((a) => (
              <li key={a.id}>
                <Icon name={a.severity === "critical" ? "warning" : "info"} size={13} className={lvlTone(a.severity) === "red" ? "neg" : "dim"} />{" "}
                <b>{a.title}</b> <span className="dim">{a.detail}</span>
              </li>
            ))}
            {(alerts.data?.length ?? 0) === 0 && <li className="dim">No alerts yet.</li>}
          </ul>
        </Card>
      </div>
    </>
  );
}

function Row({ k, v, tone }: { k: string; v: string; tone?: string }) {
  return (
    <div className="risk-item"><div className="risk-head">
      <span className="dim">{k}</span><b className={tone ?? ""}>{v}</b>
    </div></div>
  );
}
