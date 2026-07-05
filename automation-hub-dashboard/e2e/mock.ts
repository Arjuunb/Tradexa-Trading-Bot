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
  strategy: "Decision Brain", mode: "replay",
  win_rate: 58, profit_factor: 1.7, trades: 24, wins: 14, losses: 10, breakeven: 0,
  net_r: 12, equity_curve: [{ t: null, equity: 10000 }, { t: "2026-07-05T09:00:00Z", equity: 10300 }],
  max_drawdown_pct: 8.2, realized_pnl: 300, expectancy: 12.5, best: 150, worst: -80,
  avg_win: 60, avg_loss: -35, gross_win: 840, gross_loss: 540, longest_losing_streak: 3,
  sharpe_ratio: 0.42, sortino_ratio: 1.06,
  risk_adjusted: { sharpe_ratio: 0.42, sortino_ratio: 1.06, sample: 24, basis: "per-trade R", note: "per-trade ratios (not annualised)" },
  starting_balance: 10000, balance: 10300, recent: [],
};
const STRAT_HEALTH = {
  strategy: "Decision Brain",
  // scorecard fields (used by the Risk Manager health card)
  classification: "Healthy", health_score: 72, drawdown_score: 80, reasons: [],
  health: { status: "Healthy", recent: { n: 24, win_rate: 58, profit_factor: 1.7, expectancy: 12.5, avg_rr: 1.4, max_drawdown: 8.2, consecutive_losses: 3 },
    previous: { n: 20, win_rate: 55, profit_factor: 1.5, expectancy: 10, avg_rr: 1.3, max_drawdown: 9, consecutive_losses: 2 }, warnings: [] },
  brain: { blocked: 12, taken: 24, total: 36, block_rate: 33.3, top_reasons: {} },
  breakdown: {
    by_symbol: [{ name: "BTCUSDT", trades: 14, win_rate: 60, net_pnl: 200, blocked: 5 },
                { name: "ETHUSDT", trades: 10, win_rate: 55, net_pnl: 100, blocked: 7 }],
    by_session: [{ name: "London", trades: 12, win_rate: 62, net_pnl: 180 },
                 { name: "New York", trades: 12, win_rate: 54, net_pnl: 120 }],
  },
};
const WALK_FORWARD = {
  available: true, oos_net_r: 6.4, positive_folds: 3, total_folds: 4,
  folds: [{ train_net_r: 8, test_net_r: 2 }, { train_net_r: 6, test_net_r: 1.5 },
          { train_net_r: 7, test_net_r: 3 }, { train_net_r: 5, test_net_r: -0.1 }],
};

const JOURNAL_FULL = {
  trade_id: "t1234567abcdef", mode: "paper", symbol: "BTCUSDT", side: "long",
  strategy: "Decision Brain", timeframe: "4h", entry: 100, stop: 95, target: 115,
  exit: 115, size: 2, risk_amount: 10, planned_rr: 3, actual_rr: 3, pnl: 30,
  result: "win", confidence: 0.8, brain_score: 0.5, regime: "Trending",
  grade: "A", status: "closed",
  events: [
    { ts: "2026-07-05T08:00:00Z", kind: "setup-detected", detail: "aligned long" },
    { ts: "2026-07-05T08:00:01Z", kind: "risk-check-passed", detail: "1% risk" },
    { ts: "2026-07-05T08:00:02Z", kind: "trade-opened", detail: "long 2 @ 100" },
    { ts: "2026-07-05T09:00:00Z", kind: "exit-triggered", detail: "take-profit" },
    { ts: "2026-07-05T09:00:01Z", kind: "trade-closed", detail: "+30" },
  ],
  sections: {
    entry_decision: { main_reason: "Aligned 4-vote long", strategy_setup: "Trend pullback",
      higher_timeframe_trend: "up", confidence_score: 0.8, final_decision_score: 0.5 },
    checklist: {
      entry_reads: [
        { name: "EMA trend (fast vs slow)", status: "Passed", detail: "EMA12>EMA26" },
        { name: "Fair-value gap (FVG)", status: "Not checked" },
      ],
      risk_gates: [
        { rule: "daily_loss", name: "Daily loss limit", status: "Passed", detail: "today +0" },
        { rule: "exposure", name: "Exposure cap", status: "Passed", detail: "within 5%" },
      ],
    },
    market_snapshot: { price: 100, rsi: 58, atr: 1.2, regime: "Trending", trend_direction: "up" },
    risk_check: { risk_per_trade: "1%", final_risk_decision: "approved" },
    exit_decision: { exit_reason: "take-profit", exit_price: 115, actual_rr: 3, pnl: 30, result: "win" },
    review: { grade: "A", quality: "good", entry_valid: true, risk_valid: true, exit_valid: true,
      followed_strategy: true, mistake: "", improvement: "Repeatable — keep taking this setup." },
    evolution: { learned: "Aligned trend longs pay in Trending regime", strength: "early signal (3 trades)",
      take_similar_again: true, confidence_direction: "hold", rule_weight_hint: "no change yet",
      guardrails: ["Risk is never increased automatically.",
        "The Risk Manager and Safety Center are never bypassed.",
        "Insights under 30 trades are early signals; 50+ trades are needed for stronger changes."] },
  },
};
const JOURNAL_TRADES = { trades: [{
  trade_id: "t1234567abcdef", created_at: "2026-07-05T08:00:00Z", closed_at: "2026-07-05T09:00:01Z",
  mode: "paper", symbol: "BTCUSDT", side: "long", strategy: "Decision Brain", timeframe: "4h",
  entry: 100, exit: 115, pnl: 30, planned_rr: 3, actual_rr: 3, result: "win", grade: "A", status: "closed",
}] };
const JOURNAL_EVOLUTION = { setups: [{
  setup_key: "Brain|Trending|long", strategy: "Decision Brain", regime: "Trending", side: "long",
  trades: 3, wins: 2, net_r: 4, stage: "early-signal", note: "Early signal — needs 30+ trades." }] };

// exact shapes keyed by pathname substring (first match wins)
const SHAPES: [string, unknown][] = [
  // journal: /trades and /evolution must precede the single-journal fallback
  ["/journal/trades", JOURNAL_TRADES],
  ["/journal/evolution", JOURNAL_EVOLUTION],
  ["/journal/t1234567abcdef", JOURNAL_FULL],
  ["/settings", SETTINGS],
  ["/replay/run", { meta: { bars: 0, data_warning: "" }, candles: [], trades: [], frames: [], events: [] }],
  ["/strategies/registry", { strategies: [] }],
  ["/scanner/scan", { count: 0, opportunities: [], symbols: [] }],
  ["/control/compare", { winner: "A",
    a: { strategy: "Decision Brain", timeframe: "4h", results: { total_trades: 10, win_rate: 55, profit_factor: 1.6, net_r: 8, max_drawdown_pct: 12 } },
    b: { strategy: "EMA Cross", timeframe: "4h", results: { total_trades: 12, win_rate: 48, profit_factor: 1.2, net_r: 4, max_drawdown_pct: 15 } } }],
  ["/execution/realism", { available: true, edge_survives: true, rejected: 0, partial_fills: 0, slippage_cost_r: 0,
    ideal: { net_r: 10, profit_factor: 1.8, win_rate: 55, expectancy_r: 0.3 },
    realistic: { net_r: 8, profit_factor: 1.6, win_rate: 53, expectancy_r: 0.25 } }],
  ["/strategy/health", STRAT_HEALTH],
  ["/risk/portfolio", { available: false, positions: [], allocations: [], correlations: [], concentration: [] }],
  ["/production/readiness", { checks: [] }],
  ["/safety/live-readiness", { live_allowed: false, hard_locked: true,
    locked_reason: "Live execution is locked by design in this build — paper mode only.",
    default_mode: "paper", passed: 2, total: 6, requirements: [
      { key: "paper_record", label: "Paper trading track record", passed: false, detail: "0 closed paper trades (need ≥ 30)" },
      { key: "emergency_stop_tested", label: "Emergency stop tested", passed: false, detail: "never run" },
      { key: "max_daily_loss", label: "Max daily loss configured", passed: false, detail: "disabled" },
      { key: "max_drawdown", label: "Max drawdown configured", passed: true, detail: "20.00% circuit breaker" },
      { key: "broker_connected", label: "Live broker connection verified", passed: false, detail: "no live broker connected (paper only)" },
      { key: "decision_logging", label: "Decision logging enabled", passed: true, detail: "every trade is journaled" },
    ] }],
  ["/safety/test-emergency-stop", { ok: true, verified: true, prior_state: "Active", state_after: "Active", tested_at: "2026-07-05T09:00:00Z" }],
  ["/skipped/trades", { trades: [
    { id: 2, ts: "2026-07-05T09:10:00Z", symbol: "ETHUSDT", side: "SELL", stage: "risk_guard", category: "risk",
      status: "rejected", reason: "Max open positions (3) reached", entry: 2000, stop: 2100, target: null,
      strategy: "Decision Brain", timeframe: "4h", snapshot: { price: 2000, rsi: 71, regime: "Ranging" } },
    { id: 1, ts: "2026-07-05T09:05:00Z", symbol: "BTCUSDT", side: "BUY", stage: "controls", category: "safety",
      status: "rejected", reason: "Trading paused — entry blocked", entry: 100, stop: 95, target: 115,
      strategy: "Decision Brain", timeframe: "4h", snapshot: {} },
  ] }],
  ["/validation/paper", {
    sample_size: 24, min_review: 30, min_evidence: 50,
    metrics: { win_rate: 58, profit_factor: 1.7, expectancy: 12.5, max_drawdown_pct: 8.2, avg_rr: 1.3, sharpe_ratio: 0.42, sortino_ratio: 1.06 },
    best_symbol: { name: "BTCUSDT", net_pnl: 200 }, worst_symbol: { name: "ETHUSDT", net_pnl: -50 },
    best_strategy: { name: "Decision Brain", net_r: 12 }, worst_strategy: { name: "Decision Brain", net_r: 12 },
    skipped_total: 7, skipped_by_category: [{ category: "safety", count: 5 }, { category: "risk", count: 2 }],
    safety: { live_allowed: false, hard_locked: true, passed: 3, total: 6 },
    live_review: { eligible: false, stage: "insufficient-sample",
      reasons: ["Need ≥ 30 closed paper trades (have 24).", "Safety guards incomplete: max_daily_loss."],
      note: "Live trading stays LOCKED regardless of this verdict. This is human-review eligibility only — it never auto-enables real-money trading." },
  }],
  ["/skipped/summary", { stages: [{ stage: "risk_guard", count: 1 }, { stage: "controls", count: 1 }] }],
  ["/health/bot", {
    engine: { running: true, mode: "paper", strategy: "Decision Brain", symbols: ["BTCUSDT", "ETHUSDT"],
      timeframe: "4h", bars_processed: 150, signals: 4, trades: 1, rejections: 2, uptime_s: 320, started_at: "2026-07-05T09:00:00Z" },
    data_source: "synthetic / replay",
    broker: { connected: false, active: "paper", live_locked: true, note: "paper execution only — no live venue connected" },
    last_candle: { symbol: "BTCUSDT", ts: "2026-07-05T09:05:00Z" },
    last_signal: { symbol: "BTCUSDT", side: "long", entry: 100, ts: "2026-07-05T09:04:00Z" },
    last_rejected: { symbol: "ETHUSDT", side: "SELL", stage: "risk_guard", reason: "Max open positions (3) reached", ts: "2026-07-05T09:03:00Z" },
    open_positions: 1, daily_pnl: 30,
    risk: { equity: 10000, exposure_pct: 0.02, exposure_limit_pct: 0.05, open_positions: 1, max_open_positions: 3,
      trading_state: "Active", auto_halted: false, halt_reason: "", max_drawdown_pct: 0.2 },
    watchdog: { running: true, findings: [], last_heartbeat: "2026-07-05T09:05:30Z" },
    errors: [],
  }],
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
  ["/lab/walk-forward", WALK_FORWARD],
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
