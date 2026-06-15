import { useState } from "react";
import Sidebar from "./components/layout/Sidebar";
import TopHeader from "./components/layout/TopHeader";
import TickerBar from "./components/layout/TickerBar";
import MetricCards from "./components/cards/MetricCards";
import PerformanceOverview from "./components/cards/PerformanceOverview";
import PnlDistribution from "./components/cards/PnlDistribution";
import MyBots from "./components/bots/MyBots";
import ActivityFeed from "./components/activity/ActivityFeed";
import RiskCenter from "./components/risk/RiskCenter";
import RecentAlerts from "./components/alerts/RecentAlerts";
import EquityCurve from "./components/chart/EquityCurve";
import Card, { Dropdown } from "./components/common/Card";
import Modal from "./components/common/Modal";
import type { Bot, BotStatus } from "./types";
import { bots as seedBots } from "./data/mock";

export default function App() {
  const [active, setActive] = useState("Overview");
  const [collapsed, setCollapsed] = useState(false);
  const [bots, setBots] = useState<Bot[]>(seedBots);
  const [showCreate, setShowCreate] = useState(false);

  // Play/Pause updates local mock bot status.
  const toggleBot = (id: string) => {
    setBots((prev) =>
      prev.map((b) => {
        if (b.id !== id) return b;
        const next: BotStatus =
          b.status === "Live" || b.status === "Running" ? "Stopped" : "Running";
        return { ...b, status: next };
      }),
    );
  };

  return (
    <div className={`app ${collapsed ? "sidebar-collapsed" : ""}`}>
      <Sidebar active={active} onSelect={setActive} collapsed={collapsed} />

      <div className="main">
        <TopHeader onToggleSidebar={() => setCollapsed((c) => !c)} />

        <div className="content">
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
            <MyBots bots={bots} onToggle={toggleBot} onCreate={() => setShowCreate(true)} />
          </div>

          <div className="grid-bottom">
            <ActivityFeed />
            <PnlDistribution />
            <RiskCenter />
            <RecentAlerts />
          </div>
        </div>

        <TickerBar />
      </div>

      <Modal open={showCreate} title="Create Bot" onClose={() => setShowCreate(false)}>
        <p className="dim">
          Bot creation is a placeholder in this Phase 1 dashboard. Wire it to the
          Automation Hub API in a later phase.
        </p>
        <div className="modal-form">
          <label>Bot name<input placeholder="My Strategy Bot" /></label>
          <label>Strategy
            <select>
              <option>EMA Trend</option>
              <option>SMC Breakout</option>
              <option>RSI Scalper</option>
            </select>
          </label>
          <label>Pair<input placeholder="BTC/USDT" /></label>
        </div>
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancel</button>
          <button className="btn btn-primary" onClick={() => setShowCreate(false)}>Create</button>
        </div>
      </Modal>
    </div>
  );
}
