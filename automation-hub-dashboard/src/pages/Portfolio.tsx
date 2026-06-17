import Card from "../components/common/Card";
import Doughnut from "../components/chart/Doughnut";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { useLive, hhmmss, type LedgerPosition, type PaperAccount, type RiskSummary } from "../lib/api";

const money = (n: number | undefined) => `$${(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const COLORS = ["#8b5cf6", "#22c55e", "#3b82f6", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899", "#84cc16"];

export default function PortfolioPage() {
  const { data: acct } = useLive<PaperAccount>("/paper/account", 2500);
  const { data: risk } = useLive<RiskSummary>("/risk/summary", 2500);
  const { data: positions } = useLive<LedgerPosition[]>("/paper/positions", 2500);

  const pos = positions ?? [];
  const slices = pos.map((p, i) => ({
    name: p.symbol,
    value: Math.round(p.size * p.entry * 100) / 100,
    color: COLORS[i % COLORS.length],
  }));
  const notional = slices.reduce((s, x) => s + x.value, 0);

  return (
    <>
      <PageHeader title="Portfolio" subtitle="Allocation & exposure across open paper positions" />

      <div className="stat-row">
        <StatCard label="Equity" value={money(risk?.equity ?? acct?.balance)} />
        <StatCard label="Open Positions" value={String(pos.length)} />
        <StatCard label="Exposure" value={risk ? `${(risk.exposure_pct * 100).toFixed(1)}%` : "—"} tone="amber" />
        <StatCard label="Realized P&L" value={money(acct?.realized_pnl)} tone={(acct?.realized_pnl ?? 0) >= 0 ? "green" : "red"} />
      </div>

      <div className="grid-2-1">
        <Card title="Open Positions" className="span-2">
          <div className="tablewrap">
            <table className="data-table">
              <thead><tr><th>Symbol</th><th>Side</th><th>Size</th><th>Entry</th><th>Notional</th><th>Opened</th></tr></thead>
              <tbody>
                {pos.map((p) => (
                  <tr key={p.id}>
                    <td><b>{p.symbol}</b></td>
                    <td><Badge text={p.side} tone={p.side === "long" ? "green" : "red"} /></td>
                    <td>{p.size.toFixed(6)}</td>
                    <td>{p.entry.toLocaleString()}</td>
                    <td>{money(p.size * p.entry)}</td>
                    <td className="dim mono">{hhmmss(p.opened_at)}</td>
                  </tr>
                ))}
                {pos.length === 0 && <tr><td colSpan={6} className="dim ta-center" style={{ padding: 18 }}>No open positions.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Allocation" subtitle="by notional">
          {slices.length > 0 ? (
            <Doughnut data={slices} height={220} centerLabel="Notional" centerValue={money(notional)} />
          ) : (
            <div className="dim ta-center" style={{ padding: 30 }}>No open positions to allocate.</div>
          )}
        </Card>
      </div>
    </>
  );
}
