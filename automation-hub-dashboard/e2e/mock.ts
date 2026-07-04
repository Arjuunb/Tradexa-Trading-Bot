import type { Page, Route } from "@playwright/test";

/** Deterministic mock backend for the E2E audit. Intercepts every request to
 *  the API host (:8000) and returns plausible JSON so pages render without a
 *  live backend. Endpoints with nested access get exact shapes; everything
 *  else defaults to {} or [] so the SPA's "loading/empty" states show. */

const SETTINGS = {
  editable: {
    risk_per_trade_pct: 0.01, exposure_limit_pct: 0.05, max_drawdown_pct: 0.2,
    max_open_positions: 3, dedup_window_s: 300, max_daily_loss_pct: 0,
    session_start: 0, session_end: 24, max_weekly_loss_pct: 0,
    max_trades_per_day: 0, max_consecutive_losses: 0, cooldown_after_loss_min: 0,
    trading_days_mask: 127, entry_mode: "limit", daily_report_hour: 8,
  },
  readonly: {
    strategy: "Decision Brain", strategy_key: "brain", timeframe: "4h",
    symbols: ["BTCUSDT", "ETHUSDT"], starting_cash: 10000, data_source: "synthetic",
    poll_seconds: null, mode: "paper", broker_connected: false,
    webhook_secret_set: true, telegram_configured: false, min_quality_score: 60,
  },
};

const SYSTEM = {
  engine_running: false, strategy: "Decision Brain", timeframe: "4h",
  trading_state: "active", mode: "paper", auto_halted: false, halt_reason: "",
};

const RISK = {
  equity: 10000, realized_pnl: 0, open_positions: 0, exposure_pct: 0,
  trading_state: "active", rejections: 0, exposure_limit_pct: 0.05,
};

const PERF = {
  win_rate: 0, profit_factor: 0, trades: 0, wins: 0, losses: 0, breakeven: 0,
  net_r: 0, equity_curve: [], max_drawdown_pct: 0, realized_pnl: 0,
  expectancy: 0, best: 0, worst: 0,
};

// exact shapes keyed by pathname substring (first match wins)
const SHAPES: [string, unknown][] = [
  ["/settings", SETTINGS],
  ["/replay/run", { meta: { bars: 0, data_warning: "" }, candles: [], trades: [], frames: [], events: [] }],
  ["/strategies/registry", { strategies: [] }],
  ["/strategy/health", { classification: "—", health_score: 0, drawdown_score: 0, reasons: [], breakdown: { by_symbol: [], by_session: [] } }],
  ["/risk/portfolio", { available: false, positions: [], allocations: [], correlations: [], concentration: [] }],
  ["/production/readiness", { checks: [] }],
  ["/bot-os", { services: [] }],
  ["/alerts/channels", { channels: [] }],
  ["/alerts/check", { ok: true, issues: [] }],
  ["/econ/protection", { mode: "normal", actions: [], next_event: null, minutes_to_event: null }],
  ["/market/context", { fear_greed: { available: false }, btc_dominance: { available: false }, total_mcap_usd: { available: false }, eth_btc: { available: false }, funding_rate: { available: false }, open_interest: { available: false }, liquidations: { available: false }, econ_calendar: { available: false }, news: { available: false, connected: false, headlines: [] }, provider_debug: [] }],
  ["/paper/equity-curve", { points: [] }],

  ["/system/status", SYSTEM],
  ["/risk/summary", RISK],
  ["/risk/portfolio", { available: false }],
  ["/risk/recovery", { available: false }],
  ["/strategy/performance", PERF],
  ["/paper/account", { balance: 10000, realized_pnl: 0, equity: 10000 }],
  ["/auth/status", { authenticated: true, user: "admin", signup_open: false }],
  ["/notifications/status", { notify_trades: true, notify_risk: true, configured: false }],
  ["/execution/fill-model", { model: "perfect" }],
  ["/engine/status", { running: false, symbols: ["BTCUSDT"], entry_mode: "limit", timeframe: "4h" }],
  ["/control/options", { symbols: ["BTCUSDT", "ETHUSDT"], timeframes: ["1h", "4h", "1d"],
    strategies: ["Decision Brain"], default_tuning: {} }],
  ["/markets/watchlist", { rows: [], any_real: false }],
  ["/strategy/league", { available: false, detail: "no data (mock)" }],
  ["/report/daily", { report: {}, text: "Daily report — mock", telegram_configured: false }],
  ["/performance/track-record", { live: { trades: 0 }, verdict: "insufficient-live-trades", detail: "mock" }],
  ["/execution/quality", { overall: { fills: 0 } }],
  ["/data/integrity", { verdict: "empty", series: [] }],
  ["/learning/report", { active_adjustments: {}, evolution: [], lessons: [] }],
  ["/counterfactual/report", { total_saved_r: 0, open_virtual_trades: 0, rules: {} }],
  ["/shadow/report", { active: false, note: "mock" }],
  ["/retune/report", { ran: false, note: "mock" }],
  ["/ops/watchdog", { running: true, findings: [], last_heartbeat: null }],
  ["/ops/storage", { data_dir: "/logs", persistent: true, files: {}, warning: null }],
  ["/evolution/dashboard", { sentiment: { available: false }, workflow: [], lessons_weekly: 0,
    lessons_total: 0, upgrade_status: {}, live_rule: "mock" }],
  ["/market/context", { fear_greed: { available: false }, news: { available: false, connected: false, headlines: [] } }],
  ["/paper/equity-curve", { points: [] }],
  ["/bots/live", []],
  ["/system/why-no-trades", { reasons: [] }],
  ["/news/world", { available: false, headlines: [], snapshot: {} }],
];

const ARRAY_HINTS = ["/paper/trades", "/paper/positions", "/ledger/", "/strategy/custom", "/bots",
  "/research", "/brokers", "/journal", "/logs", "/commits", "/evolution/lessons",
  "/evolution/upgrades", "/alerts"];

function bodyFor(pathname: string): unknown {
  for (const [frag, shape] of SHAPES) if (pathname.includes(frag)) return shape;
  if (ARRAY_HINTS.some((h) => pathname.includes(h))) return [];
  return {};
}

export async function mockApi(page: Page) {
  await page.route(
    (url) => url.host === "localhost:8000",
    async (route: Route) => {
      const url = new URL(route.request().url());
      // POST/PUT actions succeed with an echo so save/toggle flows show success
      if (route.request().method() !== "GET") {
        return route.fulfill({ status: 200, contentType: "application/json",
          body: JSON.stringify({ ok: true, saved: true, ...(bodyFor(url.pathname) as object) }) });
      }
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify(bodyFor(url.pathname)) });
    },
  );
}
