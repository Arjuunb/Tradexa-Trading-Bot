export type BotStatus = "Live" | "Running" | "Paper" | "Paused" | "Stopped";

export interface Bot {
  id: string;
  name: string;
  status: BotStatus;
  strategy: string;
  pair: string;
  timeframe: string;
  riskPct: number;
  todayPnl: number;
  totalPnl: number;
}

export type ActivityKind =
  | "open-long"
  | "open-short"
  | "take-profit"
  | "stop-loss"
  | "closed";

export interface Activity {
  id: string;
  bot: string;
  kind: ActivityKind;
  label: string;
  time: string;
}

export type AlertKind = "warning" | "success" | "info" | "error";

export interface AlertItem {
  id: string;
  kind: AlertKind;
  title: string;
  detail: string;
  time: string;
}

export interface RiskMetric {
  label: string;
  value: string;
  pct: number;
  tone: "green" | "amber" | "red" | "purple" | "blue";
}

export interface Ticker {
  pair: string;
  price: string;
  change: number;
}

export interface PerfMetric {
  label: string;
  value: string;
  tone?: "green" | "red" | "default";
  spark?: number[];
  sparkColor?: string;
}

// ---- multi-page models ----
export type RiskLevel = "Low" | "Medium" | "High";

export interface Strategy {
  id: string;
  name: string;
  desc: string;
  winRate: number;
  profitFactor: number;
  avgRR: number;
  backtests: number;
  lastUsed: string;
  risk: RiskLevel;
  spark: number[];
  color: string;
}

export interface Position {
  id: string;
  pair: string;
  side: "Long" | "Short";
  size: number;
  entry: number;
  mark: number;
  pnl: number;
}

export interface Trade {
  id: string;
  time: string;
  pair: string;
  side: "Long" | "Short";
  entry: number;
  exit: number;
  pnl: number;
  rr: number;
  result: "Win" | "Loss";
}

export type LogType = "Info" | "Warning" | "Error" | "Trade" | "Risk";

export interface LogEntry {
  id: string;
  time: string;
  bot: string;
  type: LogType;
  message: string;
  status: string;
}

export type AlertSeverity = "Info" | "Warning" | "Critical";
export type AlertCategory = "Risk" | "Trade" | "System" | "Connection";

export interface PlatformAlert {
  id: string;
  time: string;
  severity: AlertSeverity;
  category: AlertCategory;
  title: string;
  detail: string;
  read: boolean;
  active: boolean;
}

export interface RiskSettings {
  riskPct: number;
  dailyLossLimit: number;
  maxDrawdown: number;
  maxOpenTrades: number;
  consecutiveLossLimit: number;
  autoPause: boolean;
}

// ---- safety-first models (capital protection / transparency / health) ----
export interface RuleCheck {
  rule: string;
  passed: boolean;
}

export type Verdict = "Allowed" | "Rejected" | "Blocked";

export interface Decision {
  id: string;
  time: string;
  symbol: string;
  strategy: string;
  signal: "Buy" | "Sell" | "Hold";
  confidence: number;
  checks: RuleCheck[];
  verdict: Verdict;
  reason: string;
}

export type GuardStatus = "OK" | "Warning" | "Blocked";

export interface CapitalGuard {
  rule: string;
  value: string;
  limit: string;
  pct: number;
  status: GuardStatus;
}

export interface BotHealth {
  status: string;
  exchange: string;
  dataFeed: string;
  heartbeat: string;
  uptime: string;
  lastScan: string;
  lastTrade: string;
  errors: number;
}

// ---- Phase 1: TradingView webhook -> paper execution ----
export type TradingState = "Active" | "Paused" | "Stopped";
export type WebhookStatus = "Accepted" | "Rejected" | "Duplicate";

export interface WebhookEvent {
  id: string;
  time: string;
  alertId: string;
  symbol: string;
  side: "Buy" | "Sell" | "Close";
  entry: number;
  stop: number | null;
  stage: "controls" | "dedup" | "risk" | "sizing" | "execution";
  status: WebhookStatus;
  reason: string;
}
