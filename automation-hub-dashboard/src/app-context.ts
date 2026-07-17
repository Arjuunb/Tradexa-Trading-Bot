import { createContext, useContext } from "react";

export interface AppApi {
  /** Navigate to a page by its sidebar label (updates the URL hash). */
  go: (page: string) => void;
  /** Open a single bot's detail page (route #/bot/<id>). */
  viewBot: (id: string) => void;
  /** Show a transient toast notification. */
  toast: (msg: string, tone?: "success" | "error" | "info") => void;
}

export const AppContext = createContext<AppApi>({
  go: () => {},
  viewBot: () => {},
  toast: () => {},
});

export const useApp = () => useContext(AppContext);

// The sidebar pages (the standalone trading-bot workspace layout).
export const NAV_LABELS = [
  "Overview", "Markets", "Strategies", "Backtesting",
  "Paper Trading", "Bot Terminal", "Portfolio", "Analytics", "Strategy Proof", "Strategy Studio", "Grid & DCA", "AI Intelligence",
  "Risk Manager", "Evolution", "Journal", "Memory", "Bot Health", "Logs", "Settings", "Safety Center",
] as const;

// Extra routes reachable by hash but not shown in the main nav. Every page
// still works — these are linked from their sibling pages instead of taking
// a sidebar slot (Symbols from Markets, Simulation/Replay from Backtesting,
// Live Trading from Safety Center, AI Assistant from AI Intelligence,
// Decisions from Journal).
const EXTRA_ROUTES = [
  "Bots", "Alerts", "Symbols", "Simulation", "Replay",
  "Live Trading", "AI Assistant", "Decisions",
] as const;

export const slug = (page: string) => page.toLowerCase().replace(/ /g, "-");

export interface Route {
  page: string;
  botId: string;
}

export const parseHash = (): Route => {
  const h = window.location.hash.replace(/^#\/?/, "").trim();
  const m = h.match(/^bot\/(.+)$/);
  if (m) return { page: "BotDetail", botId: m[1] };
  const found = [...NAV_LABELS, ...EXTRA_ROUTES].find((n) => slug(n) === h);
  return { page: found ?? "Overview", botId: "" };
};
