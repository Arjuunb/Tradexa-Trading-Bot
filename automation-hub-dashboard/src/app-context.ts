import { createContext, useContext } from "react";

export interface AppApi {
  /** Navigate to a page by its sidebar label (updates the URL hash). */
  go: (page: string) => void;
  /** Jump to Backtesting pre-filled with a strategy. */
  backtest: (strategy: string) => void;
  /** Open the global Create Bot modal. */
  openCreateBot: () => void;
}

export const AppContext = createContext<AppApi>({
  go: () => {},
  backtest: () => {},
  openCreateBot: () => {},
});

export const useApp = () => useContext(AppContext);

export const NAV_LABELS = [
  "Overview", "Bots", "Strategies", "Paper Trading", "Backtesting",
  "Risk Center", "Analytics", "Logs", "Alerts", "Settings",
] as const;

export const slug = (page: string) => page.toLowerCase().replace(/ /g, "-");

export const pageFromHash = (): string => {
  const h = window.location.hash.replace(/^#\/?/, "").trim();
  return NAV_LABELS.find((n) => slug(n) === h) ?? "Overview";
};
