import type { Bot } from "../types";
import Card, { Dropdown } from "../components/common/Card";
import MetricCards from "../components/cards/MetricCards";
import EquityCurve from "../components/chart/EquityCurve";
import PerformanceOverview from "../components/cards/PerformanceOverview";
import PnlDistribution from "../components/cards/PnlDistribution";
import MyBots from "../components/bots/MyBots";
import ActivityFeed from "../components/activity/ActivityFeed";
import RiskCenter from "../components/risk/RiskCenter";
import RecentAlerts from "../components/alerts/RecentAlerts";

interface OverviewProps {
  bots: Bot[];
  onToggle: (id: string) => void;
  onCreate: () => void;
}

export default function Overview({ bots, onToggle, onCreate }: OverviewProps) {
  return (
    <>
      <MetricCards />

      <div className="grid-mid">
        <Card
          title="Equity Curve"
          subtitle="All Bots"
          className="equity-card"
          right={
            <div className="legend-inline">
              <span className="legend-chip purple">Equity</span>
              <span className="legend-chip grey">Buy &amp; Hold</span>
              <Dropdown label="7 Days" />
            </div>
          }
        >
          <div className="equity-chart">
            <EquityCurve />
          </div>
        </Card>

        <PerformanceOverview />
        <MyBots bots={bots} onToggle={onToggle} onCreate={onCreate} />
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
