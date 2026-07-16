import { lazy, Suspense, useEffect, useState } from "react";
import Sidebar from "./components/layout/Sidebar";
import TopHeader from "./components/layout/TopHeader";
import TickerBar from "./components/layout/TickerBar";
import Toasts, { type ToastItem } from "./components/common/Toasts";
// Pages are code-split (lazy) so the initial bundle is just the shell + the
// first page, not all ~25 pages and their chart libraries.
const Overview = lazy(() => import("./pages/Overview"));
const BotsPage = lazy(() => import("./pages/Bots"));
const StrategiesPage = lazy(() => import("./pages/Strategies"));
const PaperTradingPage = lazy(() => import("./pages/PaperTrading"));
const BacktestingPage = lazy(() => import("./pages/Backtesting"));
const RiskCenterPage = lazy(() => import("./pages/RiskCenter"));
const LogsPage = lazy(() => import("./pages/Logs"));
const AlertsPage = lazy(() => import("./pages/Alerts"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const BotDetail = lazy(() => import("./pages/BotDetail"));
const MarketsPage = lazy(() => import("./pages/Markets"));
const SymbolExplorerPage = lazy(() => import("./pages/SymbolExplorer"));
const SimulationPage = lazy(() => import("./pages/Simulation"));
const ReplayPage = lazy(() => import("./pages/Replay"));
const EvolutionPage = lazy(() => import("./pages/Evolution"));
const LiveTradingPage = lazy(() => import("./pages/LiveTrading"));
const PortfolioPage = lazy(() => import("./pages/Portfolio"));
const AnalyticsPage = lazy(() => import("./pages/Analytics"));
const AIAssistantPage = lazy(() => import("./pages/AIAssistant"));
const AIIntelligencePage = lazy(() => import("./pages/AIIntelligence"));
const StrategyStudioPage = lazy(() => import("./pages/StrategyStudio"));
const SafetyCenterPage = lazy(() => import("./pages/SafetyCenter"));
const JournalPage = lazy(() => import("./pages/Journal"));
const DecisionsPage = lazy(() => import("./pages/Decisions"));
const MemoryPage = lazy(() => import("./pages/Memory"));
const BotHealthPage = lazy(() => import("./pages/BotHealth"));
const StrategyProofPage = lazy(() => import("./pages/StrategyProof"));
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
      case "Strategy Studio": return <StrategyStudioPage />;
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
          <div className="content">
            <Suspense fallback={<div className="dim" style={{ padding: 24 }}>Loading…</div>}>
              {renderPage()}
            </Suspense>
          </div>
          <TickerBar />
        </div>
      </div>
    </AppContext.Provider>
  );
}
