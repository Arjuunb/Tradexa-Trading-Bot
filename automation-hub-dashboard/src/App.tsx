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
import MarketsPage from "./pages/Markets";
import SymbolExplorerPage from "./pages/SymbolExplorer";
import SimulationPage from "./pages/Simulation";
import ReplayPage from "./pages/Replay";
import EvolutionPage from "./pages/Evolution";
import LiveTradingPage from "./pages/LiveTrading";
import PortfolioPage from "./pages/Portfolio";
import AnalyticsPage from "./pages/Analytics";
import AIAssistantPage from "./pages/AIAssistant";
import AIIntelligencePage from "./pages/AIIntelligence";
import SafetyCenterPage from "./pages/SafetyCenter";
import JournalPage from "./pages/Journal";
import DecisionsPage from "./pages/Decisions";
import MemoryPage from "./pages/Memory";
import BotHealthPage from "./pages/BotHealth";
import StrategyProofPage from "./pages/StrategyProof";
import { AppContext, parseHash, slug } from "./app-context";

const MOBILE = "(max-width: 720px)";

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);   // off-canvas drawer (small screens)
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

  // On phones the hamburger opens an off-canvas drawer; on desktop it collapses
  // the rail to icons. Escape and picking a page both close the drawer, and
  // growing back to desktop width clears any stuck open state.
  const toggleSidebar = () => {
    if (window.matchMedia(MOBILE).matches) setMobileNav((o) => !o);
    else setCollapsed((c) => !c);
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMobileNav(false); };
    const onResize = () => { if (!window.matchMedia(MOBILE).matches) setMobileNav(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("resize", onResize); };
  }, []);

  const go = (page: string) => { window.location.hash = "/" + slug(page); setMobileNav(false); };
  const viewBot = (id: string) => { window.location.hash = "/bot/" + id; setMobileNav(false); };

  const renderPage = () => {
    switch (active) {
      case "Markets": return <MarketsPage />;
      case "Symbols": return <SymbolExplorerPage />;
      case "Strategies": return <StrategiesPage />;
      case "Backtesting": return <BacktestingPage />;
      case "Simulation": return <SimulationPage />;
      case "Replay": return <ReplayPage />;
      case "Paper Trading": return <PaperTradingPage />;
      case "Live Trading": return <LiveTradingPage />;
      case "Portfolio": return <PortfolioPage />;
      case "Analytics": return <AnalyticsPage />;
      case "Strategy Proof": return <StrategyProofPage />;
      case "AI Intelligence": return <AIIntelligencePage />;
      case "AI Assistant": return <AIAssistantPage />;
      case "Risk Manager": return <RiskCenterPage />;
      case "Evolution": return <EvolutionPage />;
      case "Journal": return <JournalPage />;
      case "Decisions": return <DecisionsPage />;
      case "Memory": return <MemoryPage />;
      case "Bot Health": return <BotHealthPage />;
      case "Logs": return <LogsPage />;
      case "Settings": return <SettingsPage />;
      case "Safety Center": return <SafetyCenterPage />;
      // legacy routes (not in the main nav, still reachable by hash)
      case "Bots": return <BotsPage />;
      case "Alerts": return <AlertsPage />;
      case "BotDetail": return <BotDetail botId={route.botId} />;
      default: return <Overview />;
    }
  };

  const title = active === "Overview" ? "Dashboard" : active === "BotDetail" ? route.botId : active;

  return (
    <AppContext.Provider value={{ go, viewBot, toast }}>
      <div className={`app ${collapsed ? "sidebar-collapsed" : ""} ${mobileNav ? "mobile-nav-open" : ""}`}>
        <Toasts items={toasts} />
        {mobileNav && <div className="nav-backdrop" onClick={() => setMobileNav(false)} aria-hidden />}
        <Sidebar active={active === "BotDetail" ? "Bots" : active} onSelect={go} collapsed={collapsed} />

        <div className="main">
          <TopHeader onToggleSidebar={toggleSidebar} title={title} />
          <div className="content">{renderPage()}</div>
          <TickerBar />
        </div>
      </div>
    </AppContext.Provider>
  );
}
