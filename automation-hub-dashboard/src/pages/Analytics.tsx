import Card, { Dropdown } from "../components/common/Card";
import AreaLine from "../components/chart/AreaLine";
import BarChart from "../components/chart/BarChart";
import Doughnut from "../components/chart/Doughnut";
import { PageHeader, StatCard } from "../components/common/ui";
import { analytics } from "../data/mock";

export default function AnalyticsPage() {
  const a = analytics;
  return (
    <>
      <PageHeader title="Analytics" subtitle="Performance across bots, strategies and symbols" actions={<Dropdown label="Last 30 Days" />} />

      <div className="stat-row">
        <StatCard label="Best Bot" value={a.bestBot.value} sub={a.bestBot.name} tone="green" />
        <StatCard label="Worst Bot" value={a.worstBot.value} sub={a.worstBot.name} tone="red" />
        <StatCard label="Best Symbol" value={a.bestSymbol.value} sub={a.bestSymbol.name} tone="green" />
        <StatCard label="Worst Symbol" value={a.worstSymbol.value} sub={a.worstSymbol.name} tone="red" />
      </div>

      <div className="grid-2-eq">
        <Card title="Overall Performance">
          <div className="chart-md"><AreaLine labels={a.overallLabels} series={[{ name: "Equity", data: a.overall, color: "#8b5cf6" }]} yFormatter={(v) => `$${(v / 1000).toFixed(0)}K`} valueFormatter={(v) => `$${v.toLocaleString()}`} /></div>
        </Card>
        <Card title="P&L by Bot">
          <div className="chart-md"><BarChart labels={a.pnlByBot.map((x) => x.name)} data={a.pnlByBot.map((x) => x.value)} diverging horizontal /></div>
        </Card>
      </div>

      <div className="grid-3-eq">
        <Card title="Win Rate by Strategy">
          <div className="chart-sm"><BarChart labels={a.winRateByStrategy.map((x) => x.name)} data={a.winRateByStrategy.map((x) => x.value)} color="#22c55e" max={100} /></div>
        </Card>
        <Card title="Profit Factor by Strategy">
          <div className="chart-sm"><BarChart labels={a.profitFactorByStrategy.map((x) => x.name)} data={a.profitFactorByStrategy.map((x) => x.value)} color="#3b82f6" /></div>
        </Card>
        <Card title="Trade Distribution">
          <div className="chart-sm doughnut-center-wrap">
            <Doughnut data={a.tradeDistribution} height={150} centerLabel="Trades" centerValue={`${a.tradeDistribution.reduce((s, x) => s + x.value, 0)}`} />
          </div>
        </Card>
      </div>

      <div className="grid-2-eq">
        <Card title="Drawdown">
          <div className="chart-md"><AreaLine labels={a.overallLabels} series={[{ name: "Drawdown", data: a.drawdown, color: "#ef4444" }]} yFormatter={(v) => `${v}%`} valueFormatter={(v) => `${v}%`} /></div>
        </Card>
        <Card title="Monthly P&L">
          <div className="chart-md"><BarChart labels={a.monthly.map((x) => x.name)} data={a.monthly.map((x) => x.value)} diverging /></div>
        </Card>
      </div>
    </>
  );
}
