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

// The sidebar, organised as the trading lifecycle: observe the bot → build a
// strategy → prove it → run it → study the results → govern the system.
// Grouped sections keep the platform feeling like one operating system
// instead of a flat list of pages.
export const NAV_GROUPS: { title: string | null; items: string[] }[] = [
  { title: null, items: ["Dashboard"] },
  { title: "Trading", items: ["Strategy Studio", "Fleet Manager", "Paper Trading", "Replay", "Backtesting", "Optimization Lab", "Grid & DCA", "Live Trading"] },
  { title: "Performance", items: ["Portfolio", "Allocation", "Analytics", "AI Intelligence"] },
  { title: "Records", items: ["Journal", "Decision Archive", "Memory"] },
  { title: "System", items: ["Risk Manager", "Bot Health", "Logs", "Settings"] },
];

export const NAV_LABELS: string[] = NAV_GROUPS.flatMap((g) => g.items);

// Extra routes reachable by hash but not shown in the main nav. Every page
// still works — these are linked from their sibling pages instead of taking
// a sidebar slot (Markets/Symbols from Portfolio, Strategies + Strategy Proof
// from Strategy Studio, Simulation from Backtesting, Safety Center from Live
// Trading + Risk Manager, Evolution from Memory, Paper Account from the Paper
// Trading terminal, AI Assistant from AI Intelligence).
const EXTRA_ROUTES = [
  "Alerts", "Symbols", "Markets", "Strategies", "Strategy Proof",
  "Simulation", "Evolution", "Safety Center", "Paper Account", "AI Assistant",
] as const;

// Old bookmarks / saved hashes keep working after the reorganisation.
const LEGACY_SLUGS: Record<string, string> = {
  "overview": "Dashboard",
  "bot-terminal": "Paper Trading",   // the terminal IS the paper-trading page now
  "decisions": "Decision Archive",
  "bots": "Fleet Manager",           // the Bots page is now the Fleet Manager
};

export const slug = (page: string) => page.toLowerCase().replace(/ /g, "-");

export interface Route {
  page: string;
  botId: string;
  /** Deep-link target id — the decision cycle or trade to focus on arrival. */
  focusId?: string;
}

export const parseHash = (): Route => {
  const h = window.location.hash.replace(/^#\/?/, "").trim();
  const bot = h.match(/^bot\/(.+)$/);
  if (bot) return { page: "BotDetail", botId: bot[1] };
  // shareable deep links to a single decision or trade (for audit/sharing)
  const dec = h.match(/^decision\/(.+)$/);
  if (dec) return { page: "Decision Archive", botId: "", focusId: decodeURIComponent(dec[1]) };
  const trd = h.match(/^trade\/(.+)$/);
  if (trd) return { page: "Journal", botId: "", focusId: decodeURIComponent(trd[1]) };
  if (LEGACY_SLUGS[h]) return { page: LEGACY_SLUGS[h], botId: "" };
  const found = [...NAV_LABELS, ...EXTRA_ROUTES].find((n) => slug(n) === h);
  return { page: found ?? "Dashboard", botId: "" };
};
