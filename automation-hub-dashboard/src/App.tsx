import { useState } from "react";
import Sidebar from "./components/layout/Sidebar";
import TopHeader from "./components/layout/TopHeader";
import TickerBar from "./components/layout/TickerBar";
import Modal from "./components/common/Modal";
import { Field } from "./components/common/ui";
import Overview from "./pages/Overview";
import BotsPage from "./pages/Bots";
import StrategiesPage from "./pages/Strategies";
import PaperTradingPage from "./pages/PaperTrading";
import BacktestingPage from "./pages/Backtesting";
import RiskCenterPage from "./pages/RiskCenter";
import AnalyticsPage from "./pages/Analytics";
import LogsPage from "./pages/Logs";
import AlertsPage from "./pages/Alerts";
import SettingsPage from "./pages/Settings";
import type { Bot, BotStatus } from "./types";
import { bots as seedBots } from "./data/mock";

export default function App() {
  const [active, setActive] = useState("Overview");
  const [collapsed, setCollapsed] = useState(false);
  const [bots, setBots] = useState<Bot[]>(seedBots);
  const [showCreate, setShowCreate] = useState(false);

  const toggleBot = (id: string) =>
    setBots((prev) =>
      prev.map((b) => {
        if (b.id !== id) return b;
        const next: BotStatus = b.status === "Live" || b.status === "Running" ? "Stopped" : "Running";
        return { ...b, status: next };
      }),
    );

  const openCreate = () => setShowCreate(true);

  const renderPage = () => {
    switch (active) {
      case "Bots": return <BotsPage bots={bots} setBots={setBots} onCreate={openCreate} />;
      case "Strategies": return <StrategiesPage />;
      case "Paper Trading": return <PaperTradingPage />;
      case "Backtesting": return <BacktestingPage />;
      case "Risk Center": return <RiskCenterPage />;
      case "Analytics": return <AnalyticsPage />;
      case "Logs": return <LogsPage />;
      case "Alerts": return <AlertsPage />;
      case "Settings": return <SettingsPage />;
      default: return <Overview bots={bots} onToggle={toggleBot} onCreate={openCreate} />;
    }
  };

  return (
    <div className={`app ${collapsed ? "sidebar-collapsed" : ""}`}>
      <Sidebar active={active} onSelect={setActive} collapsed={collapsed} />

      <div className="main">
        <TopHeader onToggleSidebar={() => setCollapsed((c) => !c)} title={active === "Overview" ? "Dashboard" : active} />
        <div className="content">{renderPage()}</div>
        <TickerBar />
      </div>

      <Modal open={showCreate} title="Create Bot" onClose={() => setShowCreate(false)}>
        <p className="dim">
          Bot creation is a placeholder in this Phase 1 dashboard. Wire it to the
          Automation Hub API in a later phase.
        </p>
        <div className="modal-form">
          <Field label="Bot name"><input placeholder="My Strategy Bot" /></Field>
          <Field label="Strategy">
            <select><option>EMA Trend</option><option>SMC Breakout</option><option>RSI Scalper</option></select>
          </Field>
          <Field label="Pair"><input placeholder="BTC/USDT" /></Field>
        </div>
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancel</button>
          <button className="btn btn-primary" onClick={() => setShowCreate(false)}>Create</button>
        </div>
      </Modal>
    </div>
  );
}
