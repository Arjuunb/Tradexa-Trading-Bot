import { useEffect, useState } from "react";
import Sidebar from "./components/layout/Sidebar";
import TopHeader from "./components/layout/TopHeader";
import TickerBar from "./components/layout/TickerBar";
import Toasts, { type ToastItem } from "./components/common/Toasts";
import Overview from "./pages/Overview";
import BotsPage from "./pages/Bots";
import StrategiesPage from "./pages/Strategies";
import PaperTradingPage from "./pages/PaperTrading";
import BacktestingPage from "./pages/Backtesting";
import RiskCenterPage from "./pages/RiskCenter";
import LogsPage from "./pages/Logs";
import AlertsPage from "./pages/Alerts";
import SettingsPage from "./pages/Settings";
import BotDetail from "./pages/BotDetail";
import { AppContext, parseHash, slug } from "./app-context";

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const [collapsed, setCollapsed] = useState(false);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const active = route.page;

  const toast = (msg: string, tone: "success" | "error" | "info" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 2600);
  };

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

  const renderPage = () => {
    switch (active) {
      case "Bots": return <BotsPage />;
      case "Strategies": return <StrategiesPage />;
      case "Paper Trading": return <PaperTradingPage />;
      case "Backtesting": return <BacktestingPage />;
      case "Risk Center": return <RiskCenterPage />;
      case "Logs": return <LogsPage />;
      case "Alerts": return <AlertsPage />;
      case "Settings": return <SettingsPage />;
      case "BotDetail": return <BotDetail botId={route.botId} />;
      default: return <Overview />;
    }
  };

  const title = active === "Overview" ? "Dashboard" : active === "BotDetail" ? route.botId : active;

  return (
    <AppContext.Provider value={{ go, viewBot, toast }}>
      <div className={`app ${collapsed ? "sidebar-collapsed" : ""}`}>
        <Toasts items={toasts} />
        <Sidebar active={active === "BotDetail" ? "Bots" : active} onSelect={go} collapsed={collapsed} />

        <div className="main">
          <TopHeader onToggleSidebar={() => setCollapsed((c) => !c)} title={title} />
          <div className="content">{renderPage()}</div>
          <TickerBar />
        </div>
      </div>
    </AppContext.Provider>
  );
}
