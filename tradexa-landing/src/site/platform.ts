/**
 * Platform facts shown in the footer.
 *
 * ─────────────────────────────────────────────────────────────────────────
 * READ THIS BEFORE LAUNCH.
 *
 * `PLATFORM_STATS` are placeholders. They are presented in the footer as
 * current operating metrics, and right now nothing produces them — they are
 * numbers written by hand in this file. Wire them to real telemetry (the
 * status service already tracks uptime and latency; trade and account counts
 * come from the platform database) before this is public, or remove the band.
 *
 * They are deliberately all in one place, with one shape, so that swapping the
 * source is a single change rather than a hunt through JSX.
 * ─────────────────────────────────────────────────────────────────────────
 */

export interface PlatformStat {
  /** Short label under the value. */
  label: string;
  /** The number itself, already formatted. */
  value: string;
  /** Optional qualifier — the period or scope the number covers. */
  note: string;
}

export const PLATFORM_STATS: PlatformStat[] = [
  { label: "Uptime", value: "99.98%", note: "trailing 90 days" },
  { label: "Decision latency", value: "62 ms", note: "p95, close to order" },
  { label: "Active accounts", value: "3,400+", note: "connected exchanges" },
  { label: "Decisions processed", value: "48.2M", note: "since launch" },
];

/**
 * Venues the execution layer can connect to.
 *
 * `live` is the honest distinction: a venue that is written but not shipped is
 * marked, rather than listed alongside the others and quietly qualified in a
 * footnote nobody reads.
 */
export interface Venue {
  name: string;
  live: boolean;
}

export const VENUES: Venue[] = [
  { name: "Binance", live: true },
  { name: "Bybit", live: true },
  { name: "OKX", live: true },
  { name: "Hyperliquid", live: false },
  { name: "Coinbase", live: false },
];

/**
 * Security properties, shown as badges.
 *
 * These are architectural facts about the product, each of which is explained
 * on /security — not third-party certifications. Nothing here claims SOC 2,
 * ISO 27001 or a penetration-test attestation, because none of those have been
 * awarded, and a badge asserting one would be a fabricated credential rather
 * than a design flourish. If and when an audit is completed, add it here with
 * a link to the report.
 */
export interface TrustBadge {
  label: string;
  detail: string;
}

export const TRUST_BADGES: TrustBadge[] = [
  { label: "AES-256 envelope", detail: "Per-tenant data keys under a managed master key" },
  { label: "TLS 1.3", detail: "Everything in transit, no downgrade" },
  { label: "Withdrawal-disabled", detail: "Keys with withdrawal scope are refused at connection" },
  { label: "Append-only audit", detail: "Hash-chained; no product path can amend an entry" },
  { label: "Zero trust", detail: "Every internal hop authenticates independently" },
];

/**
 * The footer ticker's symbols.
 *
 * Representative instruments, not a live feed — the footer is not the place to
 * open a market-data connection, and a tape that is wrong is worse than a tape
 * that is clearly illustrative. The strip is labelled as such.
 */
export interface TickerRow {
  symbol: string;
  price: string;
  change: number;
}

export const TICKER: TickerRow[] = [
  { symbol: "BTC/USDT", price: "68,408.0", change: 0.42 },
  { symbol: "ETH/USDT", price: "3,284.15", change: -0.18 },
  { symbol: "SOL/USDT", price: "148.24", change: 1.36 },
  { symbol: "ARB/USDT", price: "0.8412", change: -0.94 },
  { symbol: "AVAX/USDT", price: "27.61", change: 0.22 },
  { symbol: "OP/USDT", price: "1.7420", change: -0.51 },
  { symbol: "LINK/USDT", price: "16.88", change: 0.77 },
  { symbol: "DOGE/USDT", price: "0.1284", change: 0.09 },
  { symbol: "MATIC/USDT", price: "0.4917", change: -0.33 },
];

/** The project's public repository. Used by the developer pages. */
export const REPO_URL = "https://github.com/Arjuunb/Tradexa-Trading-Bot";
