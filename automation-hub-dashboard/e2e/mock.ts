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

// --- permanent trade memory (all 8 categories, honesty markers preserved) ---
const MEM_SECTIONS = {
  trade_information: { trade_id: "T1", date: "2026-07-05", time_utc: "09:00:00 UTC", exchange: "kraken",
    symbol: "BTCUSDT", direction: "Long", entry: 100, exit: 115, stop_loss: 95, take_profit: 115,
    position_size: 2, risk_pct: 0.1, planned_rr: 3, actual_rr: 3,
    fees: "0.00 (paper — fees not modeled)", duration: "2h 0m" },
  market_context: { trend: "trend", market_structure: "Not checked", session: "London", volatility: 0.8,
    atr: "not captured", volume: "not captured", liquidity: "not captured", support: "not captured",
    resistance: "not captured", funding_rate: "not captured", fear_greed_index: "not captured",
    btc_dominance: "not captured" },
  technical_analysis: { ema_fast: 101, ema_slow: 99, rsi: 61, macd: "Not checked", vwap: "Not checked",
    bollinger_bands: "Not checked", order_blocks: "Not checked", fair_value_gaps: "Not checked",
    supply_demand: "Not checked", break_of_structure: "Not checked", change_of_character: "Not checked" },
  strategy: { name: "Decision Brain", version: "not captured", timeframe: "15m", setup_grade: "A",
    confidence_score: 70, brain_score: 72, regime: "trend", htf_bias: "not captured" },
  execution: { why_opened: "EMA crossover long", why_closed: "take-profit",
    conditions_passed: ["EMA fast over slow"], conditions_failed: ["None — all evaluated gates passed."] },
  emotion_journal: { manual_notes: "" },
  trade_outcome: { result: "win", profit: 30, loss: 0, pnl: 30, actual_rr: 3,
    mistakes: "None — trade followed the plan.", lessons_learned: "Aligned trend longs pay in this regime",
    improvement_notes: "Repeat the disciplined process." },
  ai_reflection: { what_went_well: "Disciplined A-grade win — the plan was followed and it paid (3R).",
    what_went_wrong: "Nothing mechanical — the stop did its job; the setup simply failed.",
    what_to_repeat: "Repeat the disciplined process. This setup is worth taking again within existing risk limits.",
    what_to_never_do_again: "No hard rule was broken; keep the same discipline.",
    basis: "Composed from the trade's real review + evolution memory (no invented insight)." },
};
const MEM_ROW = { trade_id: "T1", closed_at: "2026-07-05T11:00:00Z", symbol: "BTCUSDT", side: "long",
  strategy: "Decision Brain", timeframe: "15m", result: "win", grade: "A", pnl: 30, actual_rr: 3,
  session: "London", weekday: "Friday", notes: "", sections: MEM_SECTIONS };
const MEM_INSIGHTS = {
  sample: 8, overall: { trades: 8, win_rate: 62.5, expectancy: 12.5, avg_rr: 1.4, pnl: 100 },
  sharpe_ratio: 0.5, sortino_ratio: 1.1, max_drawdown_abs: 40, avg_hold_seconds: 7200,
  by_symbol: [{ symbol: "BTCUSDT", trades: 8, win_rate: 62.5, expectancy: 12.5, avg_rr: 1.4, pnl: 100 }],
  by_strategy: [{ strategy: "Decision Brain", trades: 8, win_rate: 62.5, expectancy: 12.5, avg_rr: 1.4, pnl: 100 }],
  by_session: [{ session: "London", trades: 6, win_rate: 66.7, expectancy: 15, avg_rr: 1.5, pnl: 90 }],
  by_weekday: [{ weekday: "Friday", trades: 5, win_rate: 60, expectancy: 10, avg_rr: 1.3, pnl: 50 }],
  by_setup_grade: [{ grade: "A", trades: 5, win_rate: 80, expectancy: 20, avg_rr: 1.8, pnl: 100 }],
  mistakes: [{ mistake: "Chased the entry after the move started.", count: 2, loss_attributed: -35, repeated: true }],
  winning_patterns: [{ grade: "A", trades: 5, win_rate: 80, expectancy: 20, avg_rr: 1.8, pnl: 100 }],
  evidence_note: "8 closed trades. Early sample — treat breakdowns as signals, not proof.",
  coaching: [{ statement: "You perform 27% better during the London session (+15.000R vs +12.500R overall, 6 trades).",
    stage: "early-signal", metric: null }],
};
const MEM_REVIEWS = { reviews: [{ period: "nightly", period_key: "2026-07-05",
  created_at: "2026-07-05T23:59:00Z",
  report: { overall: { trades: 3, win_rate: 66.7, expectancy: 14 }, sharpe_ratio: 0.5, max_drawdown_abs: 20 } }] };
const MEM_SIMILAR = { similar: [{ trade_id: "T2", symbol: "ETHUSDT", side: "long", result: "win", similarity: 0.92 }] };
const MEM_ASK = { query: "show all losing BTC trades", kind: "filter",
  answer: "Found 1 loss BTCUSDT trades.", trades: [MEM_ROW] };

// exact shapes keyed by pathname substring (first match wins)
const SHAPES: [string, unknown][] = [
  // Trading modes + approvals (§7, §11) — GET shapes (POSTs auto-echo 200)
  ["/engine/mode", { mode: "semi", modes: ["full", "semi", "signal"], pending_approvals: 1 }],
  ["/approvals", { mode: "semi",
    pending: [{ id: 7, symbol: "BTCUSDT", side: "BUY", entry: 65000, stop: 63500,
      target: 69500, confidence: 0.82, planned_rr: 3.0, brain_score: 78,
      timeframe: "4h", strategy: "Decision Brain", status: "pending",
      reason: "Trend + demand reclaim; structure shift confirmed on 4H." }],
    recent: [{ id: 6, symbol: "ETHUSDT", side: "SELL", entry: 3200, stop: 3260,
      target: 3080, confidence: 0.6, planned_rr: 2.0, brain_score: 64,
      timeframe: "4h", strategy: "Decision Brain", status: "rejected",
      reject_reason: "manual" }] }],
  ["/risk/presets", { active: "balanced", presets: {
    conservative: { risk_per_trade_pct: 0.005, max_open_positions: 2, max_daily_loss_pct: 0.02, max_drawdown_pct: 0.10, exposure_limit_pct: 0.10 },
    balanced: { risk_per_trade_pct: 0.01, max_open_positions: 3, max_daily_loss_pct: 0.03, max_drawdown_pct: 0.15, exposure_limit_pct: 0.15 },
    aggressive: { risk_per_trade_pct: 0.02, max_open_positions: 5, max_daily_loss_pct: 0.05, max_drawdown_pct: 0.25, exposure_limit_pct: 0.30 } } }],
  // journal: /trades and /evolution must precede the single-journal fallback
  // Explainable Trading cycle reports: /1 must precede the list fragment
  ["/engine/cycles/1", { id: 1, ts: "2026-07-05T09:00:00Z", symbol: "BTCUSDT",
    timeframe: "5m", price: 100.2, decision: "SKIP", score: 54,
    report: {
      ts: "2026-07-05T09:00:00Z", symbol: "BTCUSDT", timeframe: "5m", price: 100.2,
      decision: "SKIP", side: "long", score: 54,
      market_analysis: { available: true, bias: "Neutral",
        trend: { ema8_vs_ema33: "above", swing_highs: "Higher High", swing_lows: "Higher Low" },
        structure: { state: "consolidation", break_of_structure: "none", change_of_character: false },
        volume: { label: "below average" }, volatility: { label: "medium" },
        liquidity: { sweep: "none detected" }, last_candle: "no notable pattern" },
      checklist: [
        { name: "EMA alignment", status: "PASS", explanation: "EMA8 above EMA33 for a long setup" },
        { name: "Risk:reward >= 2.0", status: "FAIL", explanation: "planned RR 1.40:1 — minimum is 2.0" },
        { name: "Volume confirmation", status: "FAIL", explanation: "below average (x0.72 vs 20-bar avg)" },
        { name: "Session allowed", status: "PASS", explanation: "UTC hour 9 in window 0-24" }],
      scores: { available: true, trend: 16, structure: 8, supply_demand: 10,
        volume: 6, risk: 14, total: 54, label: "skip-quality", engine_score: 48 },
      reasons: ["Blocked at the brain gate: Score 48/100 below minimum 60",
        "\u274c Risk:reward only 1.4 — minimum required is 2.0",
        "\u274c Volume below average"],
      recommendation: "Wait for a pullback toward the zone — a closer entry improves the RR." } }],
  ["/engine/cycles", { total: 42, cycles: [
    { id: 1, ts: "2026-07-05T09:00:00Z", symbol: "BTCUSDT", timeframe: "5m",
      price: 100.2, decision: "SKIP", score: 54 },
    { id: 2, ts: "2026-07-05T08:55:00Z", symbol: "ETHUSDT", timeframe: "5m",
      price: 2001.4, decision: "WAIT", score: 41 }] }],
  ["/journal/trades", JOURNAL_TRADES],
  ["/journal/evolution", JOURNAL_EVOLUTION],
  ["/journal/t1234567abcdef", JOURNAL_FULL],
  // trade memory: specific paths precede the single-memory fallback (/{id})
  ["/trade-memory/growth", { available: true,
    totals: { trades: 21, wins: 13, losses: 8, breakeven: 0, win_rate: 61.9,
      net_pnl: 412.5, net_r: 14.2, expectancy_r: 0.676, best_r: 3.0, worst_r: -1.2,
      avg_win_r: 2.1, avg_loss_r: -1.0, profit_factor: 3.4 },
    streaks: { current: 3, longest_win: 5, longest_loss: 2 },
    span: { first: "2026-06-02T09:00:00Z", last: "2026-07-05T09:00:00Z" },
    monthly: [{ month: "2026-06", trades: 12, net_r: 8.4, win_rate: 58.3 },
              { month: "2026-07", trades: 9, net_r: 5.8, win_rate: 66.7 }],
    by_strategy: [{ name: "Decision Brain", trades: 16, win_rate: 62.5, net_r: 11.0 },
                  { name: "Supertrend", trades: 5, win_rate: 60.0, net_r: 3.2 }],
    by_symbol: [{ name: "BTCUSDT", trades: 12, win_rate: 66.7, net_r: 9.1 },
                { name: "ETHUSDT", trades: 9, win_rate: 55.6, net_r: 5.1 }],
    grades: { A: 6, B: 10, C: 5 },
    sample_note: "early sample — fewer than 30 remembered trades; treat every number as provisional" }],
  ["/trade-memory/trades", { trades: [MEM_ROW], total: 8 }],
  ["/trade-memory/ask", MEM_ASK],
  ["/trade-memory/insights", MEM_INSIGHTS],
  ["/trade-memory/mistakes", { mistakes: MEM_INSIGHTS.mistakes }],
  ["/trade-memory/reviews", MEM_REVIEWS],
  ["/trade-memory/similar/", MEM_SIMILAR],
  ["/trade-memory/T1", MEM_ROW],
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
  ["/strategy/list", { active: "brain", timeframe: "4h", strategies: [
    { key: "brain", label: "Decision Brain", desc: "Multi-factor trend" },
    { key: "supertrend", label: "Supertrend", desc: "ATR trend-following" },
    { key: "smc", label: "SMC (Smart Money)", desc: "Liquidity + structure" }] }],
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
  ["/paper/account", { initial_capital: 10000, current_equity: 10300, available_balance: 10300,
    realized_pnl: 300, unrealized_pnl: 0, last_updated: "2026-07-05T09:00:00Z", open_positions: 0,
    persistent: true, storage: "supabase", warning: null, starting_balance: 10000, balance: 10300 }],
  ["/auth/status", { authenticated: true, user: "admin", signup_open: false }],
  ["/notifications/status", { notify_trades: true, notify_risk: true, configured: false }],
  ["/execution/fill-model", { model: "perfect" }],
  ["/engine/status", { running: false, symbols: ["BTCUSDT"], entry_mode: "limit", timeframe: "4h" }],
  ["/control/options", { symbols: ["BTCUSDT", "ETHUSDT"], timeframes: ["1h", "4h", "1d"],
    strategies: ["Decision Brain"], default_tuning: {} }],
  ["/markets/watchlist", { rows: [], any_real: false }],
  ["/symbols/asset-classes", { asset_classes: [{ asset_class: "crypto", count: 2 }, { asset_class: "stock", count: 1 }],
    crypto_source: "fallback (seed list)", synced_at: "2026-07-16T00:00:00Z", total: 3 }],
  ["/symbols/search", { query: "", results: [] }],
  ["/symbols/info", { found: true, symbol: "BTC/USDT", ticker: "BTCUSDT", name: "Bitcoin", asset_class: "crypto",
    exchange: "Binance", base: "BTC", quote: "USDT", type: "spot", session: "24/7", market_status: "open",
    price_available: false, note: "mock", favorite: false, pinned: false }],
  ["/symbols", { count: 2, symbols: [
    { symbol: "BTC/USDT", ticker: "BTCUSDT", name: "Bitcoin", asset_class: "crypto", exchange: "Binance",
      base: "BTC", quote: "USDT", type: "spot", session: "24/7", favorite: true, pinned: false },
    { symbol: "ETH/USDT", ticker: "ETHUSDT", name: "Ethereum", asset_class: "crypto", exchange: "Binance",
      base: "ETH", quote: "USDT", type: "spot", session: "24/7", favorite: false, pinned: false }] }],
  ["/market/prefs", { favorites: ["BTCUSDT"], pinned: [], watchlists: [{ id: "w1", name: "Crypto", symbols: ["BTCUSDT"] }] }],
  ["/ai/analyze", { available: true, symbol: "BTCUSDT", timeframe: "1h", ts: "2026-07-16T00:00:00Z", price: 60000,
    decision: "BUY", side: "long", overall_score: 82, confidence_level: "High", confidence_pct: 82, engine_score: 84,
    allowed: true, min_score: 60,
    score_breakdown: [{ category: "Trend", score: 18, max: 20 }, { category: "Market Structure", score: 17, max: 20 },
      { category: "Volume", score: 15, max: 20 }, { category: "Risk Management", score: 18, max: 20 },
      { category: "Confirmation", score: 14, max: 20 }],
    reasons: ["Higher-timeframe trend agrees", "BOS confirmed", "Volume above average"], failed_checks: [],
    recommendation: "Trade placed — manage per plan.",
    risk_analysis: { position_size: 0.01, notional: 6000, max_loss: 100, expected_profit: 200, risk_pct: 1,
      risk_reward: 2, margin_used: 600, leverage: 10, liquidation_price: 54300, portfolio_exposure_pct: 60,
      excessive: false, warning: null },
    setup: { entry: 60000, stop: 59000, target: 62000 },
    market_analysis: { available: true, bias: "Bullish", trend: { strength_label: "strong" },
      structure: { state: "trending up", break_of_structure: "bullish", change_of_character: false },
      liquidity: { sweep: "none detected" }, volume: { label: "above average" }, volatility: { label: "normal" } },
    checklist: [] }],
  ["/ai/profile", { sample: 12, ready: true, strengths: ["Best in the London session (+0.6R)."],
    weaknesses: ["Repeated mistake: entered before confirmation (×4)"], avg_hold_seconds: 3600,
    sharpe_ratio: 1.1, win_rate: 57, expectancy_r: 0.3, note: "Profile updates automatically as trades close." }],
  ["/ai/confidence-accuracy", { sample: 24, ready: true, calibrated: true,
    verdict: "Well calibrated: high-confidence setups win 72% vs 41% for low-confidence (+31 pts).",
    high_conf_win_rate: 72, low_conf_win_rate: 41, spread_pts: 31,
    by_confidence: [{ level: "Very High", trades: 6, wins: 5, win_rate: 83, avg_rr: 1.8, avg_pnl: 40 },
      { level: "High", trades: 8, wins: 5, win_rate: 62, avg_rr: 1.2, avg_pnl: 20 },
      { level: "Medium", trades: 4, wins: 2, win_rate: 50, avg_rr: 0.4, avg_pnl: 5 },
      { level: "Low", trades: 4, wins: 1, win_rate: 25, avg_rr: -0.3, avg_pnl: -12 },
      { level: "Very Low", trades: 2, wins: 1, win_rate: 50, avg_rr: 0.1, avg_pnl: 2 }] }],
  ["/ai/alerts", { count: 2, checked: ["BTCUSDT", "ETHUSDT"], alerts: [
    { type: "strong_setup", severity: "success", title: "Strong setup — BTCUSDT", detail: "BUY at score 88/100.", symbol: "BTCUSDT" },
    { type: "outside_session", severity: "info", title: "Outside trading session", detail: "Entries held until in-session.", symbol: "" }] }],
  ["/ai/insights", { timeframe: "1h", symbols: ["BTCUSDT", "ETHUSDT"], insights: [
    { symbol: "BTCUSDT", kind: "trend", tone: "green", text: "BTC is trending strongly (bullish)." },
    { symbol: "ETHUSDT", kind: "volume", tone: "default", text: "ETH volume is decreasing (below its 20-bar average)." }] }],
  ["/ai/coach", { sample: 7, ready: true, trades: 7, win_rate: 57, expectancy_r: 0.2, avg_hold_seconds: 5400,
    main_mistake: "entered before confirmation", suggestion: "Wait for BOS before entering.",
    risk_discipline: "Excellent", best_session: "London", worst_setup: "counter-trend fade",
    headline: "You've taken 7 trades at a 57% win rate." }],
  ["/trade-memory/insights", { sample: 7, overall: { trades: 7, win_rate: 57, expectancy: 0.2 }, avg_hold_seconds: 5400,
    best_session: { name: "London", expectancy: 0.6 }, worst_session: { name: "Asia", expectancy: -0.3 },
    by_symbol: [{ name: "BTCUSDT", expectancy: 0.5, trades: 4 }], by_strategy: [{ name: "Decision Brain", expectancy: 0.4, trades: 7 }],
    mistakes: [{ mistake: "entered before confirmation", count: 4, repeated: true }] }],
  ["/ai/confidence-levels", { levels: [{ level: "Very High", min_score: 85 }] }],
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
