import { createContext, useContext } from "react";

export interface AppApi {
  /** Navigate to a page by its sidebar label (updates the URL hash). */
  go: (page: string) => void;
  /** Jump to Backtesting pre-filled with a strategy. */
  backtest: (strategy: string) => void;
  /** Open the global Create Bot modal. */
  openCreateBot: () => void;
  /** Open a single bot's detail page (route #/bot/<id>). */
  viewBot: (id: string) => void;
  /** Show a transient toast notification. */
  toast: (msg: string, tone?: "success" | "error" | "info") => void;
}

export const AppContext = createContext<AppApi>({
  go: () => {},
  backtest: () => {},
  openCreateBot: () => {},
  viewBot: () => {},
  toast: () => {},
});

export const useApp = () => useContext(AppContext);

export const NAV_LABELS = [
  "Overview", "Bots", "Strategies", "Paper Trading", "Backtesting",
  "Risk Center", "Analytics", "Logs", "Alerts", "Settings",
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
  const found = NAV_LABELS.find((n) => slug(n) === h);
  return { page: found ?? "Overview", botId: "" };
};
