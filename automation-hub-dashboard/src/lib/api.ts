// Live API client for the Automation Hub backend (FastAPI).
//
// Base URL is configurable via VITE_API_BASE (defaults to the local backend).
// Control/engine actions are secret-gated; the dev secret is configurable via
// VITE_WEBHOOK_SECRET. When the backend isn't running, hooks expose `error`
// so pages can show a "start the backend" hint instead of fake data.
import { useCallback, useEffect, useRef, useState } from "react";

// Runtime config: when the backend serves this app (single-origin on Render) it
// injects window.__HUB_CONFIG__ with apiBase="" (same origin) + the secret.
// Otherwise fall back to Vite build-time env (Vercel / local dev).
const _cfg = (typeof window !== "undefined" ? (window as any).__HUB_CONFIG__ : undefined) ?? {};
export const API_BASE = (_cfg.apiBase ?? (import.meta.env.VITE_API_BASE as string | undefined)) ?? "http://localhost:8000";
const SECRET = (_cfg.secret ?? (import.meta.env.VITE_WEBHOOK_SECRET as string | undefined)) ?? "dev-webhook-secret";

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "X-Webhook-Secret": SECRET },
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE", headers: { "X-Webhook-Secret": SECRET } });
  if (!res.ok) throw new Error(`DELETE ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export async function apiPostJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "X-Webhook-Secret": SECRET, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export interface BotSettings {
  editable: {
    risk_per_trade_pct: number; exposure_limit_pct: number; max_drawdown_pct: number;
    max_open_positions: number; dedup_window_s: number;
    max_daily_loss_pct: number; session_start: number; session_end: number;
    max_weekly_loss_pct: number; max_trades_per_day: number;
    max_consecutive_losses: number; cooldown_after_loss_min: number;
    trading_days_mask: number;
  };
  readonly: {
    strategy: string; strategy_key: string; timeframe: string; symbols: string[];
    starting_cash: number; data_source: string; poll_seconds: number | null; mode: string;
    broker_connected: boolean; webhook_secret_set: boolean; telegram_configured: boolean;
  };
}

export interface LiveState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refetch: () => void;
}

/** Poll a GET endpoint every `intervalMs` and expose data/error/loading. */
export function useLive<T>(path: string, intervalMs = 2500): LiveState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const d = await apiGet<T>(path);
      if (!alive.current) return;
      setData(d);
      setError(null);
    } catch (e) {
      if (!alive.current) return;
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    load();
    const id = setInterval(load, intervalMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [load, intervalMs]);

  return { data, error, loading, refetch: load };
}

// ---- response shapes (match the FastAPI endpoints) ----
export interface PaperAccount {
  starting_balance: number;
  balance: number;
  realized_pnl: number;
  open_positions: number;
}
export interface LedgerPosition {
  id: string; symbol: string; side: string; size: number;
  entry: number; stop: number | null; status: string; pnl: number;
  opened_at: string; closed_at: string | null;
}
export interface PaperTradeRow {
  id: string; alert_id: string | null; symbol: string; side: string; size: number;
  entry: number; stop: number | null; exit: number | null; pnl: number | null;
  rr: number | null; status: string; opened_at: string; closed_at: string | null;
}
export interface LogRow {
  id: string; ts: string; symbol: string; level: string; stage: string; message: string;
}
export interface AlertRow {
  id: string; ts: string; severity: string; category: string; title: string; detail: string; read: number;
}
export interface EngineStatus {
  running: boolean; symbols: string[]; timeframe: string; interval: number;
  started_at: string | null; bars: number; signals: number; trades: number; rejections: number;
}
export interface ControlState { state: "Active" | "Paused" | "Stopped"; }
export interface SystemStatus {
  mode: string; broker_connected: boolean; data_source: string;
  engine_running: boolean; engine_mode: string; strategy: string;
  symbols: string[]; timeframe: string; bars_processed: number;
  signals: number; trades: number; started_at: string | null;
  uptime_s: number; trading_state: string; auto_halted: boolean; halt_reason: string;
}

export function uptime(secs: number | undefined): string {
  const s = Math.max(0, Math.floor(secs ?? 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
}
export interface RiskSummary {
  equity: number; realized_pnl: number; open_positions: number; max_open_positions: number;
  exposure_notional: number; exposure_pct: number; exposure_limit_pct: number;
  risk_per_trade_pct: number; rejections: number; signals: number;
  trading_state: string; engine_running: boolean;
}
export interface PositionSizeResult {
  error?: string; method: string; side: string; entry: number; stop: number; stop_distance: number;
  position_size: number; notional: number; dollar_risk: number; risk_pct_of_equity: number;
  margin_required: number; leverage: number; liquidation_estimate: number;
}
export interface CorrelationData {
  timeframe: string; lookback: number; symbols: string[]; available: string[];
  matrix: Record<string, Record<string, number | null>>;
  pairs: { a: string; b: string; correlation: number }[];
  daily_vol: Record<string, number>;
}
export interface PortfolioRisk {
  equity: number; total_exposure: number; exposure_pct: number;
  long_exposure: number; short_exposure: number; net_exposure: number;
  by_symbol: Record<string, number>; open_risk: number; portfolio_heat_pct: number;
  value_at_risk: number | null; value_at_risk_pct: number | null; var_confidence: number;
  daily_risk_used_pct: number; warnings: string[]; risk_level: string; open_positions?: number;
}
export interface AttrBucket { key: string; trades: number; net_r: number; win_rate: number; avg_r: number; }
export interface TradeExplain { id: number; result: string; rr: number | null; why: string; why_not: string; why_trust: string; }
export interface CoachReview {
  available?: boolean; error?: string; needs_download?: boolean; data_source?: string;
  symbol: string; strategy: string; trades: number; net_r?: number; headline: string;
  why_won: string[]; why_lost: string[]; common_mistakes: { mistake: string; count: number }[];
  weak_conditions: string[]; suggestions: string[]; confidence_score: number; stability_score: number;
  attribution: Record<string, AttrBucket[]>; sample_explanations?: TradeExplain[];
}
export interface CoachLeaderboard {
  timeframe: string;
  grid: { strategy: string; symbol: string; trades: number; win_rate: number; profit_factor: number; net_r: number }[];
  by_strategy: { key: string; net_r: number }[]; by_symbol: { key: string; net_r: number }[];
  best: { strategy: string; symbol: string; net_r: number } | null;
}
export interface WalkForward {
  available: boolean; error?: string; verdict: string; note: string;
  oos_net_r: number; positive_folds: number; total_folds: number; data_source?: string;
  folds: { fold: number; best_min_score: number; train_net_r: number; test_net_r: number; test_trades: number; test_pf: number }[];
}
export interface MonteCarlo {
  available: boolean; error?: string; runs: number; trades: number; prob_profit_pct: number;
  net_r: { p5: number; median: number; p95: number; mean: number };
  max_drawdown_r: { median: number; p95: number; worst: number };
}
export interface OutOfSample {
  available: boolean; error?: string; verdict: string; note: string; split: number;
  train: { net_r: number; trades: number; profit_factor: number; win_rate: number };
  test: { net_r: number; trades: number; profit_factor: number; win_rate: number };
}
export interface SlicedPerf {
  strategy: string; timeframe: string; total_trades: number;
  by_regime: AttrBucket[]; by_session: AttrBucket[]; by_symbol: AttrBucket[];
}
export interface EquityPoint { t: string | null; equity: number; }
export interface EquityCurveData { starting_balance: number; points: EquityPoint[]; }
export interface EquityCurvePoint { t: string | null; equity: number; }
export interface StrategyPerformance {
  strategy: string; mode: string;
  trades: number; win_rate: number; profit_factor: number; expectancy: number;
  wins: number; losses: number; breakeven: number; gross_win: number; gross_loss: number;
  avg_win: number; avg_loss: number; best: number; worst: number;
  realized_pnl: number; starting_balance: number; balance: number;
  max_drawdown_abs: number; max_drawdown_pct: number; longest_losing_streak: number;
  equity_curve: EquityCurvePoint[];
  recent: PaperTradeRow[];
}
export interface CustomRule { type: string; negate?: boolean; [k: string]: unknown; }
export interface CustomSpec {
  id?: string; name: string; market?: string; symbol: string; timeframe: string;
  side: "long" | "short";
  entry: { op: "AND" | "OR"; rules: CustomRule[] };
  stop: { type: "atr" | "pct"; mult?: number; period?: number; pct?: number };
  target: { type: "rr" | "pct"; rr?: number; pct?: number };
  risk_per_trade_pct: number; max_trades_per_day?: number;
  session?: { start: number; end: number } | null;
  created_at?: string; updated_at?: string;
}
export interface SimTrade {
  side: string; entry: number; exit: number; stop: number; target: number;
  r: number; result: string; reason: string; entry_time: string; exit_time: string;
  // brain tags (present when the quality filter ran)
  score?: number; grade?: string; regime?: string; htf_bias?: string; setup_type?: string;
  exit_reason?: string; bars_held?: number; passed?: string[]; failed?: string[];
}
export interface BlockedTrade {
  time: string; side: string; score: number; regime: string; htf_bias: string;
  reason: string; blocks: string[];
}
export interface SimDiagnosis {
  summary: string; headline_problem: string;
  avg_quality_score?: number | null; avg_losing_setup_score?: number | null;
  loss_reasons: Record<string, number>; blocked_reasons: Record<string, number>;
  blocked_count?: number;
  worst_regime?: { name: string; trades: number; net_r: number; win_rate: number } | null;
  worst_session?: { name: string; trades: number; net_r: number; win_rate: number } | null;
  exit_pattern?: Record<string, number>; stop_hit_losses?: number;
  avg_win_to_loss?: number | null; overtrading: boolean; trades_per_day?: number;
  choppy_markets: boolean; recommendations: string[];
}
export interface SimResult {
  results: {
    simulation: boolean; total_trades: number; win_rate: number; wins: number; losses: number;
    profit_factor: number; net_r: number; net_pct: number; max_drawdown_r: number; max_drawdown_pct: number;
    avg_rr: number; avg_win_r: number; avg_loss_r: number; best_r: number; worst_r: number;
    max_consecutive_wins: number; max_consecutive_losses: number; end_balance: number; span_days: number;
    equity_curve: { t: string | null; equity: number }[]; trades: SimTrade[];
    // new metrics + brain output
    expectancy_r?: number; sharpe?: number; recovery_factor?: number; avg_hold_bars?: number;
    long_net_r?: number; short_net_r?: number; long_trades?: number; short_trades?: number;
    blocked_count?: number; blocked?: BlockedTrade[]; diagnosis?: SimDiagnosis;
  };
  warnings: { level: string; message: string }[];
  sizing?: {
    model: string; equity: number; risk_pct: number; entry: number; stop_distance: number;
    risk_dollars: number; position_size: number; notional: number; leverage_x: number;
  };
  brain?: { quality_filter: boolean; min_score: number; blocked_count: number };
  description: string; data_source: string; symbol: string; timeframe: string; label: string;
}

export interface CompareResult {
  strategy: string; data_source: string; symbol: string; timeframe: string;
  metrics: { total_trades: number; win_rate: number; profit_factor: number; net_r: number; max_drawdown_r: number; avg_r: number };
}

export interface NotifStatus {
  telegram_configured: boolean; notify_trades: boolean; notify_risk: boolean;
  email: string; discord: string;
}

export interface StrategyHealthData {
  strategy: string;
  health: {
    status: "Healthy" | "Degrading" | "Unhealthy";
    recent: { n: number; win_rate: number; profit_factor: number; expectancy: number; avg_rr: number; max_drawdown: number; consecutive_losses: number };
    previous: { n: number; win_rate: number; profit_factor: number; expectancy: number; avg_rr: number; max_drawdown: number; consecutive_losses: number };
    warnings: { metric: string; severity: string; detail: string }[];
  };
  brain: { blocked: number; taken: number; total: number; block_rate: number; top_reasons: Record<string, number> };
  breakdown: {
    by_symbol: { name: string; trades: number; win_rate: number; net_pnl: number; blocked: number }[];
    by_session: { name: string; trades: number; win_rate: number; net_pnl: number }[];
  };
}

export interface EngineDiagnostics {
  status: string; headline: string; detail: string; severity: "info" | "warning" | "critical";
  running: boolean; mode: string; timeframe: string; data_source: string | null;
  bars: number; signals: number; trades: number; rejections: number;
  last_bar_ts: string | null; last_activity_age_s: number | null;
}

export interface ReplayCandle { t: string; o: number; h: number; l: number; c: number; v: number; }
export interface ReplayMarker { idx: number; price: number; type: string; side: "bull" | "bear"; }
export interface ReplayFrame {
  regime: string; market_regime?: string; trends: Record<string, string>; trigger: string;
  score: number; breakdown: Record<string, number> | null; blocked: boolean;
  reason: string; vol_ratio: number;
}
export interface ReplayEvent { idx: number; kind: string; text: string; }
export interface ReplayTrade {
  id: number; symbol: string; side: "long" | "short"; entry_idx: number; entry: number;
  sl: number; tp: number; tp1: number | null; tp1_idx: number | null;
  partial?: boolean; status?: string;
  score: number; breakdown: Record<string, number>;
  entry_reasons: string[]; exit_idx: number | null; exit: number | null;
  exit_reason: string | null; result: string; rr: number | null; loss_analysis: string | null;
  mtf?: { aligned: boolean; reason: string }; regime?: string; bars_held?: number | null;
}
export interface ReplayStats {
  symbol: string; trades: number; win_rate: number; profit_factor: number; net_r: number;
  max_drawdown_r: number; avg_rr: number; expectancy_r: number; best_r: number; worst_r: number;
  long_trades: number; short_trades: number; long_net_r: number; short_net_r: number;
  max_consecutive_wins: number; max_consecutive_losses: number; current_streak: number;
}
/** Every series is candle-aligned; null marks the indicator's warm-up window. */
export interface ReplayOverlays {
  ema8: (number | null)[]; ema20: (number | null)[]; ema30: (number | null)[]; ema50: (number | null)[];
  sma20: (number | null)[]; sma50: (number | null)[]; vwap: (number | null)[];
  bb_upper: (number | null)[]; bb_mid: (number | null)[]; bb_lower: (number | null)[];
  rsi: (number | null)[]; atr: (number | null)[];
  macd: (number | null)[]; macd_signal: (number | null)[]; macd_hist: (number | null)[];
}
export interface ReplayData {
  meta: { symbol: string; timeframe: string; data_source: string; bars: number;
          start: string | null; end: string | null; htf_available: Record<string, boolean>;
          strategy?: string; data_source_label?: string; data_is_real?: boolean;
          data_warning?: string | null; needs_download?: boolean; note?: string;
          debug?: { strategy_id: string; strategy_class: string; candles_loaded: number;
                    warmup_bars: number; trades_generated: number; data_source: string;
                    mtf_timeframes: string[]; gate_timeframes?: string[]; indicators?: string[];
                    computed_at: string; error: string | null } };
  candles: ReplayCandle[];
  overlays: ReplayOverlays | Record<string, (number | null)[]>;
  markers: ReplayMarker[];
  zones: { type: string; price?: number; left_idx?: number; top?: number; bottom?: number }[];
  frames: ReplayFrame[];
  events: ReplayEvent[];
  trades: ReplayTrade[];
  stats: ReplayStats;
}

export interface SentimentData {
  available: boolean; mood: string | null; risk_mode: string; fear_greed: number | null;
  fear_greed_label?: string; btc_dominance?: number | null; total_mcap_usd?: number | null;
  confidence?: { long: number; short: number; note: string };
  social?: Record<string, string>; note: string;
}
export interface Lesson {
  id: string; symbol: string; strategy: string; lesson: string; suggested_fix: string;
  confidence: number; evidence: string; status: string; tested: boolean; created_at: string;
}
export interface Upgrade {
  id: string; strategy: string; symbol: string; title: string; reason: string; evidence: string;
  expected_benefit: string; risk: string; backtest_required: boolean; confidence: number;
  status: string; created_at: string; apply?: Record<string, number | boolean> | null;
  auto_applicable?: boolean;
}
export interface StrategyVersion {
  id: string; strategy: string; version: number; label: string; note: string;
  params: any; stats: Record<string, number>;
  gates: { backtest: boolean; simulation: boolean; paper: boolean; live_unlocked: boolean };
  created_at: string;
}
export interface VersionCompare { strategy: string; versions: StrategyVersion[]; best: string | null; }
export interface Experiment {
  symbol: string; timeframe: string; data_source: string; verdict: string; note: string;
  train_gain_r: number; test_gain_r: number; warnings: string[];
  a: { label: string; train: any; test: any };
  b: { label: string; train: any; test: any };
}
export interface MarketContext {
  fear_greed: { available: boolean; value: number | null; label: string | null; mood: string | null };
  btc_dominance: { available: boolean; value: number | null };
  total_mcap_usd: { available: boolean; value: number | null };
  eth_btc: { available: boolean; trend: string | null; change_30d_pct?: number; ratio?: number; note?: string };
  funding_rate: { available: boolean; value: number | null; symbol: string; note?: string };
  open_interest: { available: boolean; value: number | null; symbol: string; note?: string };
  news: { available: boolean; connected: boolean; headlines: { title: string; url: string; published: string }[]; note?: string };
  liquidations: { available: boolean; connected: boolean; note: string };
  economic_calendar: { available: boolean; connected: boolean; note: string };
  sentiment_summary: string;
  providers: ProviderStatus[];
  provider_debug?: ProviderDebug[];
  last_updated?: string;
}
export interface ProviderStatus { id: string; label: string; needs_key: boolean; connected: boolean; }
export interface ProviderDebug {
  id: string; label: string; connected: boolean; status: string;
  last_update: string | null; freshness_s: number | null; error: string | null;
}

export interface EvoDashboard {
  sentiment: { available: boolean; mood: string | null; risk_mode: string; fear_greed: number | null };
  lessons_weekly: number; lessons_total: number;
  lesson_status: Record<string, number>; upgrade_status: Record<string, number>;
  workflow: string[]; live_rule: string;
}

export interface ControlOptions {
  strategies: string[]; symbols: string[]; timeframes: string[]; modes: string[];
  default_tuning: ControlTuning;
}
export interface ControlTuning {
  min_score: number; rr: number; trend_filter: boolean; volume_filter: boolean;
  regime_filter: boolean; session_filter: boolean; max_trades_per_day: number; cooldown_after_loss: number;
  max_consecutive_losses: number;
}
export interface ControlSimResult {
  strategy: string; symbol: string; timeframe: string; data_source: string;
  available: boolean; error?: string; mtf_gate?: string[];
  warning: { level: string; message: string } | null;
  results?: SimResult["results"];
}
export interface ControlCompare {
  a: ControlSimResult; b: ControlSimResult; winner: "A" | "B"; summary: string; error?: string;
}

export interface ControlAutoTune {
  available: boolean; error?: string; strategy: string; symbol: string; timeframe: string;
  best_tuning: ControlTuning; verdict: string; note: string;
  train: any; validation: any; baseline_test: any; baseline_train: any;
  trials: { min_score: number; rr: number; trades: number; net_r: number; profit_factor: number }[];
}

export interface StrategyInfo { key: string; label: string; desc: string; }
export interface StrategyList { active: string; timeframe: string; strategies: StrategyInfo[]; }
export interface LiveBot {
  id: string; symbol: string; name: string; strategy: string; timeframe: string;
  status: "Running" | "Paused" | "Stopped"; open: boolean; side: string | null;
  size: number; entry: number; num_trades: number; win_rate: number; realized_pnl: number;
}

/** Short "HH:MM:SS" from an ISO timestamp. */
export function hhmmss(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = iso.includes("T") ? iso.split("T")[1] : iso;
  return t.slice(0, 8);
}
