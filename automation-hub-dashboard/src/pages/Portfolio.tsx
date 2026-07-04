import Card from "../components/common/Card";
import Doughnut from "../components/chart/Doughnut";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { useLive, hhmmss, type LedgerPosition, type PaperAccount, type RiskSummary, type PortfolioRisk } from "../lib/api";

const money = (n: number | undefined) => `$${(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const COLORS = ["#eab54f", "#22c55e", "#3b82f6", "#eab54f", "#ef4444", "#06b6d4", "#ec4899", "#84cc16"];

export default function PortfolioPage() {
  const { data: acct } = useLive<PaperAccount>("/paper/account", 2500);
  const { data: risk } = useLive<RiskSummary>("/risk/summary", 2500);
  const { data: pf } = useLive<PortfolioRisk>("/risk/portfolio?timeframe=1d", 4000);
  const { data: positions } = useLive<LedgerPosition[]>("/paper/positions", 2500);

  const pos = positions ?? [];
  const slices = pos.map((p, i) => ({
    name: p.symbol, value: Math.round(p.size * p.entry * 100) / 100, color: COLORS[i % COLORS.length],
  }));
  const notional = slices.reduce((s, x) => s + x.value, 0);
  const longN = pf?.long_exposure ?? 0;
  const shortN = pf?.short_exposure ?? 0;
  const gross = longN + shortN || 1;
  const lvl = pf?.risk_level ?? "normal";
  const lvlTone = lvl === "high" ? "red" : lvl === "elevated" ? "amber" : "green";

  return (
    <>
      <PageHeader title="Portfolio" subtitle="Allocation, exposure and risk across open paper positions"
        actions={pf && <Badge text={`${lvl} risk`} tone={lvlTone as any} />} />

      <div className="stat-row">
        <StatCard label="Equity" value={money(pf?.equity ?? risk?.equity ?? acct?.balance)} />
        <StatCard label="Net Exposure" value={money(pf?.net_exposure)} sub={`${pf?.exposure_pct ?? 0}% gross`} tone={(pf?.net_exposure ?? 0) >= 0 ? "green" : "red"} />
        <StatCard label="Portfolio Heat" value={`${pf?.portfolio_heat_pct ?? 0}%`} tone="amber" sub="open risk / equity" />
        <StatCard label="Value at Risk (1d)" value={pf?.value_at_risk_pct != null ? `${pf.value_at_risk_pct}%` : "—"} tone="amber" sub={pf?.value_at_risk != null ? `${money(pf.value_at_risk)} · ${Math.round((pf.var_confidence ?? 0.95) * 100)}%` : "needs data"} />
      </div>

      {(pf?.warnings?.length ?? 0) > 0 && (
        <Card title="">
          {(pf?.warnings ?? []).map((w, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
              <Icon name="warning" size={14} className="amber" /> <span>{w}</span>
            </div>
          ))}
        </Card>
      )}

      <Card title="Long vs Short Exposure" subtitle="net directional bias of the book">
        <div className="ls-bar">
          <div className="ls-long" style={{ width: `${(longN / gross) * 100}%` }} />
          <div className="ls-short" style={{ width: `${(shortN / gross) * 100}%` }} />
        </div>
        <div className="row-actions" style={{ justifyContent: "space-between", marginTop: 8, fontSize: 13 }}>
          <span className="pos"><b>Long</b> {money(longN)}</span>
          <span className="dim">Gross {money(longN + shortN)}</span>
          <span className="neg"><b>Short</b> {money(shortN)}</span>
        </div>
      </Card>

      <div className="grid-2-1">
        <Card title="Open Positions" className="span-2">
          <div className="tablewrap">
            <table className="data-table">
              <thead><tr><th>Symbol</th><th>Side</th><th>Size</th><th>Entry</th><th>Notional</th><th>% Book</th><th>Opened</th></tr></thead>
              <tbody>
                {pos.map((p) => {
                  const n = p.size * p.entry;
                  return (
                    <tr key={p.id}>
                      <td><b>{p.symbol}</b></td>
                      <td><Badge text={p.side} tone={p.side === "long" ? "green" : "red"} /></td>
                      <td>{p.size.toFixed(6)}</td>
                      <td>{p.entry.toLocaleString()}</td>
                      <td>{money(n)}</td>
                      <td className="dim">{notional > 0 ? `${Math.round((n / notional) * 100)}%` : "—"}</td>
                      <td className="dim mono">{hhmmss(p.opened_at)}</td>
                    </tr>
                  );
                })}
                {pos.length === 0 && <tr><td colSpan={7} className="dim ta-center" style={{ padding: 18 }}>No open positions.</td></tr>}
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
