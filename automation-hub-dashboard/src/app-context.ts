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
  "Overview", "Markets", "Strategies", "Backtesting", "Simulation", "Replay",
  "Paper Trading", "Live Trading", "Portfolio", "Analytics", "Strategy Proof", "AI Assistant",
  "Risk Manager", "Evolution", "Journal", "Decisions", "Memory", "Bot Health", "Logs", "Settings", "Safety Center",
] as const;

// Extra routes reachable by hash but not shown in the main nav (kept so the
// existing Bots / Alerts / BotDetail views still work).
const EXTRA_ROUTES = ["Bots", "Alerts"] as const;

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
