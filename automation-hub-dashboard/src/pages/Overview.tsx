import Card from "../components/common/Card";
import { PageHeader } from "../components/common/ui";
import MetricCards from "../components/cards/MetricCards";
import EquityCurve from "../components/chart/EquityCurve";
import PerformanceOverview from "../components/cards/PerformanceOverview";
import PnlDistribution from "../components/cards/PnlDistribution";
import MyBots from "../components/bots/MyBots";
import ActivityFeed from "../components/activity/ActivityFeed";
import RiskCenter from "../components/risk/RiskCenter";
import RecentAlerts from "../components/alerts/RecentAlerts";
import WhyNoTrades from "../components/cards/WhyNoTrades";

// The polished layout — every card is now backed by live backend data (paper).
export default function Overview() {
  return (
    <>
      <PageHeader title="Overview" subtitle="Live paper trading · realized P&L, engine health, risk and activity at a glance" />
      <WhyNoTrades />
      <MetricCards />

      <div className="grid-mid">
        <Card
          title="Equity Curve"
          subtitle="paper · realized P&L"
          className="equity-card"
          right={<span className="legend-inline"><span className="legend-chip purple">Equity</span></span>}
        >
          <div className="equity-chart"><EquityCurve /></div>
        </Card>

        <PerformanceOverview />
        <MyBots />
      </div>

      <div className="grid-bottom">
        <ActivityFeed />
        <PnlDistribution />
        <RiskCenter />
        <RecentAlerts />
      </div>
    </>
  );
}
