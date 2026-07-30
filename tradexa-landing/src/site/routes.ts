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

import type { ComponentType } from "react";

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
  /**
   * The page's opaque base colour, mirrored into `<meta name="theme-color">`.
   *
   * Mobile Safari and Chrome paint their own chrome with this, so without it
   * every page kept the landing page's near-black while its own background was
   * navy or graphite — a visible seam right at the top of the screen.
   */
  themeColor: string;
  /**
   * The page module.
   *
   * Declared once here so `React.lazy` and the hover prefetch cannot disagree
   * about which chunk a route needs. A dynamic `import()` inside a function
   * body is not evaluated until called, so listing them here does not pull six
   * pages into the entry bundle.
   */
  load: () => Promise<{ default: ComponentType }>;
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
    themeColor: "#07080B",
    load: () => import("@/pages/site/Features"),
  },
  {
    path: "/engine",
    label: "Engine",
    title: "Nexus Engine — the decision operating system",
    description:
      "Inside the Nexus Engine: an eight-stage AI pipeline that ingests market data, extracts structure, scores conviction, arbitrates a decision and enforces risk before a single order leaves the building.",
    accent: "electric",
    blurb: "The AI pipeline, stage by stage",
    themeColor: "#0B0E12",
    load: () => import("@/pages/site/Engine"),
  },
  {
    path: "/live-trade",
    label: "Live trade",
    title: "Live trade — the execution terminal",
    description:
      "A trading terminal view of TradeLogX Nexus: live candles, depth-of-book, open positions, the AI decision panel and a timestamped execution timeline for every fill.",
    accent: "terminal",
    blurb: "Terminal, order book and fills",
    themeColor: "#06080A",
    load: () => import("@/pages/site/LiveTrade"),
  },
  {
    path: "/selectivity",
    label: "Selectivity",
    title: "Selectivity — conviction before capital",
    description:
      "How TradeLogX Nexus decides not to trade. A confidence gauge, a nine-point qualification checklist and the full reasoning trail behind every accepted and rejected setup.",
    accent: "aurum",
    blurb: "Why most setups are rejected",
    themeColor: "#040404",
    load: () => import("@/pages/site/Selectivity"),
  },
  {
    path: "/how-it-works",
    label: "How it works",
    title: "How it works — exchange to analytics",
    description:
      "The end-to-end journey of a TradeLogX Nexus trade: exchange, analysis, AI, risk, execution, journal and analytics — told as a scroll-driven, stage-by-stage process.",
    accent: "spectrum",
    blurb: "The seven-stage journey",
    themeColor: "#05070C",
    load: () => import("@/pages/site/HowItWorks"),
  },
  {
    path: "/security",
    label: "Security",
    title: "Security — zero-trust by construction",
    description:
      "TradeLogX Nexus security: envelope-encrypted API keys, withdrawal-disabled scopes, zero-trust service identity, append-only audit logging and an isolated multi-region deployment.",
    accent: "emerald",
    blurb: "Keys, isolation and audit trails",
    themeColor: "#060B15",
    load: () => import("@/pages/site/Security"),
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
 * Start fetching a route's chunk before it is asked for.
 *
 * Every page is split, so clicking a nav item means a network round trip
 * before anything can render — on a slow connection that is the transition
 * playing over a skeleton. Pointing at a link is a reliable signal that a
 * click is coming and buys a few hundred milliseconds of head start.
 *
 * Fired on pointer-enter *and* focus, so keyboard users get the same benefit,
 * and tracked so repeated hovers over the same link do not queue work.
 */
const prefetched = new Set<string>();

export function prefetchRoute(path: string) {
  if (prefetched.has(path)) return;
  const route = routeFor(path);
  if (!route) return;
  prefetched.add(path);
  // A failed prefetch is not an error worth surfacing: the click that follows
  // will request the same chunk again through the normal Suspense path.
  void route.load().catch(() => prefetched.delete(path));
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
