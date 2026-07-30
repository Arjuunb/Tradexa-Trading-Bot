/**
 * The site's public route table.
 *
 * Navigation used to be six hash links into one very long landing page, so
 * "Engine" and "Security" were positions in a scroll rather than places you
 * could link to, bookmark, or have indexed separately. Each entry below is now
 * a real route with its own document, and this table is the single source the
 * navbar, the footer, the page-transition accent and the SEO metadata all read
 * from — so adding a page cannot leave one of them behind.
 */

export type Accent = "gold" | "electric" | "terminal" | "aurum" | "spectrum" | "emerald";

export interface SiteRoute {
  path: string;
  /** Navbar label. */
  label: string;
  /** <title> for the route (the brand suffix is appended once, centrally). */
  title: string;
  /** <meta name="description"> — also the og/twitter description. */
  description: string;
  /** Which palette the page owns; drives the nav underline + transition tint. */
  accent: Accent;
  /** One-line summary used by the footer's product column. */
  blurb: string;
}

export const SITE_ROUTES: SiteRoute[] = [
  {
    path: "/features",
    label: "Features",
    title: "Features — every capability, explorable",
    description:
      "Search, filter and expand every TradeLogX Nexus capability: the Nexus Engine, risk enforcement, Strategy Lab backtesting, the intelligence feed, trading memory and exchange connectivity.",
    accent: "gold",
    blurb: "The full capability map, searchable",
  },
  {
    path: "/engine",
    label: "Engine",
    title: "Nexus Engine — the decision operating system",
    description:
      "Inside the Nexus Engine: an eight-stage AI pipeline that ingests market data, extracts structure, scores conviction, arbitrates a decision and enforces risk before a single order leaves the building.",
    accent: "electric",
    blurb: "The AI pipeline, stage by stage",
  },
  {
    path: "/live-trade",
    label: "Live trade",
    title: "Live trade — the execution terminal",
    description:
      "A trading terminal view of TradeLogX Nexus: live candles, depth-of-book, open positions, the AI decision panel and a timestamped execution timeline for every fill.",
    accent: "terminal",
    blurb: "Terminal, order book and fills",
  },
  {
    path: "/selectivity",
    label: "Selectivity",
    title: "Selectivity — conviction before capital",
    description:
      "How TradeLogX Nexus decides not to trade. A confidence gauge, a nine-point qualification checklist and the full reasoning trail behind every accepted and rejected setup.",
    accent: "aurum",
    blurb: "Why most setups are rejected",
  },
  {
    path: "/how-it-works",
    label: "How it works",
    title: "How it works — exchange to analytics",
    description:
      "The end-to-end journey of a TradeLogX Nexus trade: exchange, analysis, AI, risk, execution, journal and analytics — told as a scroll-driven, stage-by-stage process.",
    accent: "spectrum",
    blurb: "The seven-stage journey",
  },
  {
    path: "/security",
    label: "Security",
    title: "Security — zero-trust by construction",
    description:
      "TradeLogX Nexus security: envelope-encrypted API keys, withdrawal-disabled scopes, zero-trust service identity, append-only audit logging and an isolated multi-region deployment.",
    accent: "emerald",
    blurb: "Keys, isolation and audit trails",
  },
];

/** Route paths that own their own chrome + backdrop (i.e. use SiteLayout). */
export const SITE_PATHS: ReadonlySet<string> = new Set(SITE_ROUTES.map((r) => r.path));

export function isSitePath(pathname: string): boolean {
  return SITE_PATHS.has(pathname.replace(/\/+$/, "") || "/");
}

export function routeFor(pathname: string): SiteRoute | undefined {
  const clean = pathname.replace(/\/+$/, "") || "/";
  return SITE_ROUTES.find((r) => r.path === clean);
}

/**
 * Accent → the handful of classes the shared chrome needs to tint itself.
 * Written out in full because Tailwind scans source text: `text-${accent}`
 * would compile to nothing.
 */
export interface AccentClasses {
  text: string;
  bg: string;
  border: string;
  /** Written out in full — Tailwind cannot see `hover:${...}`. */
  hoverBorder: string;
  glow: string;
}

export const ACCENT_CLASSES: Record<Accent, AccentClasses> = {
  gold: {
    text: "text-gold",
    bg: "bg-gold",
    border: "border-gold/30",
    hoverBorder: "hover:border-gold/40",
    glow: "shadow-[0_0_24px_-6px_rgba(201,162,75,0.65)]",
  },
  electric: {
    text: "text-electric-soft",
    bg: "bg-electric",
    border: "border-electric/40",
    hoverBorder: "hover:border-electric/50",
    glow: "shadow-[0_0_24px_-6px_rgba(46,123,255,0.7)]",
  },
  terminal: {
    text: "text-emerald-soft",
    bg: "bg-emerald",
    border: "border-emerald/40",
    hoverBorder: "hover:border-emerald/50",
    glow: "shadow-[0_0_24px_-6px_rgba(47,191,113,0.7)]",
  },
  aurum: {
    text: "text-gold-soft",
    bg: "bg-gold-soft",
    border: "border-gold/40",
    hoverBorder: "hover:border-gold-soft/50",
    glow: "shadow-[0_0_24px_-6px_rgba(231,206,134,0.7)]",
  },
  spectrum: {
    text: "text-aqua-soft",
    bg: "bg-aqua",
    border: "border-aqua/40",
    hoverBorder: "hover:border-aqua/50",
    glow: "shadow-[0_0_24px_-6px_rgba(34,211,238,0.7)]",
  },
  emerald: {
    text: "text-emerald-soft",
    bg: "bg-emerald",
    border: "border-emerald/40",
    hoverBorder: "hover:border-emerald/50",
    glow: "shadow-[0_0_24px_-6px_rgba(47,191,113,0.7)]",
  },
};
