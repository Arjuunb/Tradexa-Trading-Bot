import { useEffect, useState } from "react";
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
import BotDetail from "./pages/BotDetail";
import type { Bot, BotStatus } from "./types";
import { bots as seedBots } from "./data/mock";
import { AppContext, parseHash, slug } from "./app-context";

const emptyForm = { name: "", strategy: "EMA Trend", pair: "BTC/USDT" };

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const [collapsed, setCollapsed] = useState(false);
  const [bots, setBots] = useState<Bot[]>(seedBots);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [backtestStrategy, setBacktestStrategy] = useState<string>("");
  const active = route.page;

  // Hash routing: the URL hash is the single source of truth for the page,
  // so the browser back/forward buttons work.
  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    if (!window.location.hash) window.location.hash = "/overview";
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (page: string) => { window.location.hash = "/" + slug(page); };
  const viewBot = (id: string) => { window.location.hash = "/bot/" + id; };
  const backtest = (strategy: string) => { setBacktestStrategy(strategy); go("Backtesting"); };
  const openCreateBot = () => { setForm(emptyForm); setShowCreate(true); };

  const detailBot = bots.find((b) => b.id === route.botId);

  const toggleBot = (id: string) =>
    setBots((prev) =>
      prev.map((b) => {
        if (b.id !== id) return b;
        const next: BotStatus = b.status === "Live" || b.status === "Running" ? "Stopped" : "Running";
        return { ...b, status: next };
      }),
    );

  const createBot = () => {
    const newBot: Bot = {
      id: "b" + Math.random().toString(36).slice(2, 7),
      name: form.name.trim() || "New Bot",
      status: "Stopped",
      strategy: form.strategy,
      pair: form.pair.trim() || "BTC/USDT",
      timeframe: "1h",
      riskPct: 1.0,
      todayPnl: 0,
      totalPnl: 0,
    };
    setBots((prev) => [...prev, newBot]);
    setShowCreate(false);
    go("Bots");
  };

  const renderPage = () => {
    switch (active) {
      case "Bots": return <BotsPage bots={bots} setBots={setBots} onCreate={openCreateBot} />;
      case "Strategies": return <StrategiesPage />;
      case "Paper Trading": return <PaperTradingPage />;
      case "Backtesting": return <BacktestingPage initialStrategy={backtestStrategy} />;
      case "Risk Center": return <RiskCenterPage />;
      case "Analytics": return <AnalyticsPage />;
      case "Logs": return <LogsPage />;
      case "Alerts": return <AlertsPage />;
      case "Settings": return <SettingsPage />;
      case "BotDetail": return <BotDetail bot={detailBot} setBots={setBots} />;
      default: return <Overview bots={bots} onToggle={toggleBot} onCreate={openCreateBot} />;
    }
  };

  const title = active === "Overview" ? "Dashboard" : active === "BotDetail" ? (detailBot?.name ?? "Bot") : active;

  return (
    <AppContext.Provider value={{ go, backtest, openCreateBot, viewBot }}>
      <div className={`app ${collapsed ? "sidebar-collapsed" : ""}`}>
        <Sidebar active={active === "BotDetail" ? "Bots" : active} onSelect={go} collapsed={collapsed} />

        <div className="main">
          <TopHeader onToggleSidebar={() => setCollapsed((c) => !c)} title={title} />
          <div className="content">{renderPage()}</div>
          <TickerBar />
        </div>

        <Modal open={showCreate} title="Create Bot" onClose={() => setShowCreate(false)}>
          <div className="modal-form">
            <Field label="Bot name">
              <input placeholder="My Strategy Bot" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="Strategy">
              <select value={form.strategy} onChange={(e) => setForm({ ...form, strategy: e.target.value })}>
                <option>EMA Trend</option><option>SMC Breakout</option><option>RSI Scalper</option>
                <option>Mean Reversion</option><option>AI Momentum</option>
              </select>
            </Field>
            <Field label="Pair">
              <input placeholder="BTC/USDT" value={form.pair} onChange={(e) => setForm({ ...form, pair: e.target.value })} />
            </Field>
          </div>
          <div className="modal-actions">
            <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={createBot}>Create Bot</button>
          </div>
        </Modal>
      </div>
    </AppContext.Provider>
  );
}
