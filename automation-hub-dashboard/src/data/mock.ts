import type {
  Activity,
  AlertItem,
  Bot,
  LogEntry,
  PerfMetric,
  PlatformAlert,
  Position,
  RiskMetric,
  RiskSettings,
  Strategy,
  Ticker,
  Trade,
  WebhookEvent,
} from "../types";

export const NAV_ITEMS = [
  "Overview",
  "Bots",
  "Strategies",
  "Paper Trading",
  "Backtesting",
  "Risk Center",
  "Analytics",
  "Logs",
  "Alerts",
  "Settings",
] as const;

export const account = {
  equity: "$24,532.10",
  available: "$19,732.20",
  dailyPnl: "+$342.21",
  dailyPnlPct: "+1.42%",
  openPositions: 4,
  exposure: "18.4%",
};

export const metricCards = [
  { key: "total", label: "Total Bots", value: "6", sub: "3 Running", tone: "default" as const, color: "#8b5cf6", spark: [4, 5, 5, 6, 6, 6, 6] },
  { key: "running", label: "Running Bots", value: "3", sub: "50%", tone: "green" as const, color: "#22c55e", spark: [1, 2, 2, 3, 2, 3, 3] },
  { key: "paper", label: "Paper Bots", value: "2", sub: "33%", tone: "blue" as const, color: "#3b82f6", spark: [1, 1, 2, 2, 2, 1, 2] },
  { key: "live", label: "Live Bots", value: "1", sub: "17%", tone: "purple" as const, color: "#8b5cf6", spark: [0, 1, 1, 1, 1, 1, 1] },
];

export const totalPnl = { value: "+$2,340.75", pct: "+12.45%" };

export const equityDates = ["May 16", "May 17", "May 18", "May 19", "May 20", "May 21", "May 22"];
export const equitySeries = [12400, 14200, 13600, 17800, 19200, 23400, 24532];
export const buyHoldSeries = [12400, 12900, 13100, 14000, 14600, 15200, 15800];

export const performance: PerfMetric[] = [
  { label: "Win Rate", value: "63.42%", tone: "green", spark: [60, 61, 59, 62, 63, 63, 64], sparkColor: "#22c55e" },
  { label: "Profit Factor", value: "2.31", tone: "default", spark: [1.8, 2.0, 1.9, 2.2, 2.3, 2.25, 2.31], sparkColor: "#8b5cf6" },
  { label: "Total Trades", value: "28" },
  { label: "Total P&L", value: "+$342.21", tone: "green", spark: [0, 80, 60, 180, 220, 300, 342], sparkColor: "#22c55e" },
  { label: "Avg R:R", value: "1.82" },
  { label: "Best Trade", value: "+$512.32", tone: "green" },
  { label: "Worst Trade", value: "-$210.45", tone: "red" },
  { label: "Max Drawdown", value: "6.35%", tone: "red" },
];

export const bots: Bot[] = [
  { id: "b1", name: "EMA Trend Bot", status: "Live", strategy: "EMA Trend", pair: "BTC/USDT", timeframe: "15m", riskPct: 1.0, todayPnl: 342.21, totalPnl: 1820.4 },
  { id: "b2", name: "SMC Breakout Bot", status: "Running", strategy: "SMC Breakout", pair: "ETH/USDT", timeframe: "1h", riskPct: 1.5, todayPnl: 186.75, totalPnl: 940.1 },
  { id: "b3", name: "RSI Scalper", status: "Running", strategy: "RSI Scalper", pair: "SOL/USDT", timeframe: "5m", riskPct: 0.75, todayPnl: 167.32, totalPnl: 512.9 },
  { id: "b4", name: "Swing Master", status: "Paper", strategy: "Mean Reversion", pair: "XRP/USDT", timeframe: "4h", riskPct: 1.0, todayPnl: 96.12, totalPnl: 220.5 },
  { id: "b5", name: "Mean Reversion", status: "Paper", strategy: "Mean Reversion", pair: "ADA/USDT", timeframe: "1h", riskPct: 1.0, todayPnl: -45.32, totalPnl: -88.2 },
  { id: "b6", name: "AI Momentum Bot", status: "Stopped", strategy: "AI Momentum", pair: "BNB/USDT", timeframe: "1h", riskPct: 2.0, todayPnl: 0, totalPnl: 0 },
];

export const strategies: Strategy[] = [
  { id: "s1", name: "EMA Trend Bot", desc: "Fast/slow EMA crossover trend following", winRate: 63.4, profitFactor: 2.31, avgRR: 1.82, backtests: 42, lastUsed: "2025-05-22", risk: "Medium", spark: [40, 60, 55, 80, 95, 120, 140], color: "#8b5cf6" },
  { id: "s2", name: "SMC Breakout Bot", desc: "Smart-money structure break + order blocks", winRate: 58.1, profitFactor: 1.96, avgRR: 2.1, backtests: 31, lastUsed: "2025-05-21", risk: "High", spark: [20, 35, 30, 55, 50, 75, 90], color: "#3b82f6" },
  { id: "s3", name: "RSI Scalper", desc: "RSI oversold/overbought mean scalps", winRate: 66.7, profitFactor: 1.74, avgRR: 1.2, backtests: 58, lastUsed: "2025-05-22", risk: "Low", spark: [10, 20, 18, 26, 30, 36, 41], color: "#22c55e" },
  { id: "s4", name: "Mean Reversion", desc: "Bollinger reversion to the mean", winRate: 61.2, profitFactor: 1.58, avgRR: 1.4, backtests: 27, lastUsed: "2025-05-20", risk: "Medium", spark: [30, 28, 35, 32, 40, 38, 46], color: "#f59e0b" },
  { id: "s5", name: "AI Momentum Bot", desc: "ML-ranked momentum (experimental)", winRate: 54.9, profitFactor: 1.41, avgRR: 1.9, backtests: 12, lastUsed: "2025-05-18", risk: "High", spark: [12, 10, 18, 14, 22, 20, 28], color: "#ec4899" },
];

export const activity: Activity[] = [
  { id: "a1", bot: "EMA Trend Bot", kind: "open-long", label: "Opened Long Position", time: "10:24:15" },
  { id: "a2", bot: "SMC Breakout Bot", kind: "take-profit", label: "Take Profit Hit", time: "10:18:42" },
  { id: "a3", bot: "RSI Scalper", kind: "closed", label: "Closed Position", time: "10:15:32" },
  { id: "a4", bot: "Swing Master", kind: "open-short", label: "Opened Short Position", time: "10:12:07" },
  { id: "a5", bot: "Mean Reversion", kind: "stop-loss", label: "Stop Loss Hit", time: "10:08:19" },
];

export const pnlDistribution = {
  totalLabel: "Total P&L",
  total: "+$342.21",
  groups: [
    { name: "Winners", count: 18, value: "+$642.11", color: "#22c55e" },
    { name: "Losers", count: 10, value: "-$299.90", color: "#ef4444" },
    { name: "Breakeven", count: 0, value: "$0.00", color: "#5b6478" },
  ],
};

export const riskMetrics: RiskMetric[] = [
  { label: "Daily Loss Limit", value: "$342.21 / $1,000", pct: 34, tone: "green" },
  { label: "Max Drawdown", value: "6.35% / 20%", pct: 32, tone: "amber" },
  { label: "Exposure", value: "18.4% / 100%", pct: 18, tone: "blue" },
  { label: "Consecutive Losses", value: "2 / 5", pct: 40, tone: "amber" },
];

export const alerts: AlertItem[] = [
  { id: "al1", kind: "warning", title: "Daily Loss Limit Approaching", detail: "34% of daily limit used", time: "10:25 AM" },
  { id: "al2", kind: "success", title: "EMA Trend Bot", detail: "Take Profit Hit: +$186.75", time: "10:18 AM" },
  { id: "al3", kind: "info", title: "System Update", detail: "Market data connection restored", time: "10:15 AM" },
  { id: "al4", kind: "error", title: "Mean Reversion", detail: "Stop Loss Hit: -$45.32", time: "10:08 AM" },
];

export const tickers: Ticker[] = [
  { pair: "BTC/USDT", price: "$67,312.45", change: 1.23 },
  { pair: "ETH/USDT", price: "$3,750.21", change: 0.87 },
  { pair: "SOL/USDT", price: "$168.44", change: 2.15 },
  { pair: "BNB/USDT", price: "$596.21", change: -0.45 },
];

export const serverTime = "22 May 2025, 10:25:30 AM (UTC)";

// ---- Paper trading ----
export const paperAccount = {
  balance: 10000,
  equity: 10412.32,
  pnl: 412.32,
  openPnl: 86.4,
  marginUsed: "12.4%",
};

export const paperPositions: Position[] = [
  { id: "p1", pair: "BTC/USDT", side: "Long", size: 0.12, entry: 66980, mark: 67312, pnl: 39.84 },
  { id: "p2", pair: "ETH/USDT", side: "Long", size: 1.4, entry: 3712, mark: 3750, pnl: 53.2 },
  { id: "p3", pair: "SOL/USDT", side: "Short", size: 8, entry: 169.8, mark: 168.4, pnl: 11.2 },
];

export const paperHistory: Trade[] = [
  { id: "t1", time: "10:18", pair: "ETH/USDT", side: "Long", entry: 3702, exit: 3742, pnl: 56.0, rr: 2.0, result: "Win" },
  { id: "t2", time: "10:05", pair: "SOL/USDT", side: "Short", entry: 170.2, exit: 167.9, pnl: 18.4, rr: 1.5, result: "Win" },
  { id: "t3", time: "09:51", pair: "BTC/USDT", side: "Long", entry: 67110, exit: 66890, pnl: -26.4, rr: -1.0, result: "Loss" },
  { id: "t4", time: "09:33", pair: "XRP/USDT", side: "Long", entry: 0.512, exit: 0.524, pnl: 24.0, rr: 1.8, result: "Win" },
  { id: "t5", time: "09:12", pair: "ADA/USDT", side: "Short", entry: 0.452, exit: 0.461, pnl: -18.0, rr: -1.0, result: "Loss" },
];

export const paperPnlSeries = [0, 40, 22, 96, 70, 150, 210, 188, 280, 340, 412];
export const paperPnlLabels = ["09:00", "09:15", "09:30", "09:45", "10:00", "10:15", "10:20", "10:22", "10:23", "10:24", "10:25"];

export const executionLog = [
  { time: "10:25:30", msg: "Signal: BUY ETH/USDT (RSI cross 30)" },
  { time: "10:24:15", msg: "Filled: LONG BTC/USDT 0.12 @ 66,980" },
  { time: "10:22:02", msg: "Risk check passed (0.8% of equity)" },
  { time: "10:18:42", msg: "Closed: ETH/USDT TP hit +$56.00" },
  { time: "10:15:00", msg: "Bar closed 15m — evaluating signals" },
];

// ---- Backtesting sample result ----
export const backtestResult = {
  netPnl: "+$3,184.20",
  winRate: "61.8%",
  profitFactor: "2.14",
  maxDrawdown: "8.2%",
  totalTrades: "146",
  avgRR: "1.76",
  equityLabels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
  equity: [10000, 10620, 10410, 11380, 12240, 13184],
  drawdown: [0, -1.2, -3.4, -2.1, -4.8, -2.0],
  trades: [
    { id: "bt1", time: "2025-05-20 14:00", pair: "BTC/USDT", side: "Long" as const, entry: 64200, exit: 65100, pnl: 142.0, rr: 1.8, result: "Win" as const },
    { id: "bt2", time: "2025-05-19 09:00", pair: "BTC/USDT", side: "Short" as const, entry: 66100, exit: 66500, pnl: -88.0, rr: -1.0, result: "Loss" as const },
    { id: "bt3", time: "2025-05-18 16:00", pair: "BTC/USDT", side: "Long" as const, entry: 63000, exit: 64400, pnl: 210.0, rr: 2.4, result: "Win" as const },
    { id: "bt4", time: "2025-05-17 11:00", pair: "BTC/USDT", side: "Long" as const, entry: 62500, exit: 62100, pnl: -64.0, rr: -1.0, result: "Loss" as const },
  ],
};

// ---- Risk settings (defaults) ----
export const defaultRiskSettings: RiskSettings = {
  riskPct: 1.0,
  dailyLossLimit: 1000,
  maxDrawdown: 20,
  maxOpenTrades: 5,
  consecutiveLossLimit: 5,
  autoPause: true,
};

export const riskAlertRows = [
  { id: "ra1", time: "10:25 AM", rule: "Daily Loss Limit", level: "Warning", detail: "34% of daily budget used", bot: "Portfolio" },
  { id: "ra2", time: "09:40 AM", rule: "Consecutive Losses", level: "Info", detail: "2 of 5 on Mean Reversion", bot: "Mean Reversion" },
  { id: "ra3", time: "08:55 AM", rule: "Max Drawdown", level: "Info", detail: "6.35% of 20%", bot: "Portfolio" },
];

// ---- Analytics ----
export const analytics = {
  overallLabels: equityDates,
  overall: equitySeries,
  pnlByBot: [
    { name: "EMA Trend", value: 1820 },
    { name: "SMC Breakout", value: 940 },
    { name: "RSI Scalper", value: 513 },
    { name: "Swing Master", value: 221 },
    { name: "Mean Reversion", value: -88 },
    { name: "AI Momentum", value: 0 },
  ],
  winRateByStrategy: [
    { name: "EMA", value: 63.4 },
    { name: "SMC", value: 58.1 },
    { name: "RSI", value: 66.7 },
    { name: "MeanRev", value: 61.2 },
    { name: "AI", value: 54.9 },
  ],
  profitFactorByStrategy: [
    { name: "EMA", value: 2.31 },
    { name: "SMC", value: 1.96 },
    { name: "RSI", value: 1.74 },
    { name: "MeanRev", value: 1.58 },
    { name: "AI", value: 1.41 },
  ],
  drawdown: [0, -1.5, -2.2, -1.1, -3.8, -2.6, -1.2],
  monthly: [
    { name: "Jan", value: 620 },
    { name: "Feb", value: -210 },
    { name: "Mar", value: 970 },
    { name: "Apr", value: 860 },
    { name: "May", value: 944 },
  ],
  tradeDistribution: [
    { name: "Wins", value: 18, color: "#22c55e" },
    { name: "Losses", value: 10, color: "#ef4444" },
    { name: "Breakeven", value: 2, color: "#5b6478" },
  ],
  bestBot: { name: "EMA Trend Bot", value: "+$1,820.40" },
  worstBot: { name: "Mean Reversion", value: "-$88.20" },
  bestSymbol: { name: "BTC/USDT", value: "+$1,142.00" },
  worstSymbol: { name: "ADA/USDT", value: "-$88.20" },
};

// ---- Logs ----
export const logs: LogEntry[] = [
  { id: "l1", time: "10:25:30", bot: "RSI Scalper", type: "Trade", message: "BUY signal ETH/USDT @ 3,750", status: "Executed" },
  { id: "l2", time: "10:24:15", bot: "EMA Trend Bot", type: "Trade", message: "Opened LONG BTC/USDT 0.12", status: "Filled" },
  { id: "l3", time: "10:22:02", bot: "Portfolio", type: "Risk", message: "Risk check passed (0.8% equity)", status: "OK" },
  { id: "l4", time: "10:20:11", bot: "System", type: "Info", message: "Market data heartbeat OK", status: "OK" },
  { id: "l5", time: "10:18:42", bot: "SMC Breakout Bot", type: "Trade", message: "Take profit hit +$186.75", status: "Closed" },
  { id: "l6", time: "10:15:00", bot: "System", type: "Warning", message: "Latency spike 420ms to exchange", status: "Recovered" },
  { id: "l7", time: "10:08:19", bot: "Mean Reversion", type: "Risk", message: "Stop loss hit -$45.32", status: "Closed" },
  { id: "l8", time: "09:55:03", bot: "AI Momentum Bot", type: "Error", message: "Model inference timeout, skipped bar", status: "Skipped" },
  { id: "l9", time: "09:40:22", bot: "Mean Reversion", type: "Risk", message: "2 consecutive losses (limit 5)", status: "Monitoring" },
  { id: "l10", time: "09:33:10", bot: "Swing Master", type: "Trade", message: "Opened LONG XRP/USDT", status: "Filled" },
  { id: "l11", time: "09:12:48", bot: "System", type: "Info", message: "Daily session started", status: "OK" },
  { id: "l12", time: "08:55:00", bot: "Connection", type: "Warning", message: "Reconnected websocket feed", status: "Recovered" },
];

// ---- Platform alerts ----
export const platformAlerts: PlatformAlert[] = [
  { id: "pa1", time: "10:25 AM", severity: "Warning", category: "Risk", title: "Daily Loss Limit Approaching", detail: "34% of the daily loss budget has been used.", read: false, active: true },
  { id: "pa2", time: "10:18 AM", severity: "Info", category: "Trade", title: "Take Profit Hit", detail: "SMC Breakout Bot closed +$186.75 on ETH/USDT.", read: false, active: true },
  { id: "pa3", time: "10:15 AM", severity: "Info", category: "System", title: "Market Data Restored", detail: "Connection to the market data feed was restored.", read: true, active: true },
  { id: "pa4", time: "09:55 AM", severity: "Critical", category: "Connection", title: "Exchange Latency", detail: "Latency to exchange exceeded 400ms briefly.", read: false, active: true },
  { id: "pa5", time: "09:40 AM", severity: "Info", category: "Risk", title: "Consecutive Losses", detail: "Mean Reversion reached 2 of 5 consecutive losses.", read: true, active: false },
  { id: "pa6", time: "08:55 AM", severity: "Warning", category: "Connection", title: "Websocket Reconnect", detail: "Market feed reconnected after a brief drop.", read: true, active: false },
];

// ================= Safety-first data (P1 capital, P2 transparency, P4 health) =================
import type { BotHealth, CapitalGuard, Decision } from "../types";

// PRIORITY 1 — Capital Protection: mandatory limits + live usage.
export const capitalGuards: CapitalGuard[] = [
  { rule: "Risk per trade", value: "0.80%", limit: "1.00%", pct: 80, status: "OK" },
  { rule: "Daily loss limit", value: "$342", limit: "$1,000", pct: 34, status: "OK" },
  { rule: "Max drawdown", value: "6.35%", limit: "20%", pct: 32, status: "OK" },
  { rule: "Consecutive losses", value: "2", limit: "5", pct: 40, status: "Warning" },
  { rule: "Max open positions", value: "4", limit: "6", pct: 67, status: "OK" },
  { rule: "Exposure", value: "18.4%", limit: "100%", pct: 18, status: "OK" },
];

export const tradingStatus = {
  state: "Active" as "Active" | "Auto-paused" | "Locked",
  detail: "All capital-protection limits within range. Trading allowed.",
};

// PRIORITY 2 — Decision Transparency: every signal explained (rules passed/failed).
export const decisions: Decision[] = [
  {
    id: "dc1", time: "10:24:15", symbol: "BTC/USDT", strategy: "EMA Trend", signal: "Buy", confidence: 72,
    checks: [
      { rule: "Trend bullish — EMA aligned", passed: true },
      { rule: "RSI confirmed (cross > 30)", passed: true },
      { rule: "Risk per trade ≤ 1%", passed: true },
      { rule: "Daily loss limit OK", passed: true },
      { rule: "Max open positions OK", passed: true },
    ],
    verdict: "Allowed", reason: "All risk + signal checks passed — order sized at 0.8% of equity.",
  },
  {
    id: "dc2", time: "10:18:42", symbol: "ETH/USDT", strategy: "SMC Breakout", signal: "Buy", confidence: 64,
    checks: [
      { rule: "Market structure break confirmed", passed: true },
      { rule: "Order block mitigated", passed: true },
      { rule: "Price not near resistance", passed: false },
    ],
    verdict: "Rejected", reason: "Price too close to resistance.",
  },
  {
    id: "dc3", time: "10:12:07", symbol: "SOL/USDT", strategy: "RSI Scalper", signal: "Sell", confidence: 58,
    checks: [
      { rule: "RSI overbought (> 70)", passed: true },
      { rule: "Spread within limit", passed: true },
      { rule: "Slippage estimate ≤ 5 bps", passed: false },
    ],
    verdict: "Rejected", reason: "Estimated slippage 9 bps exceeds the 5 bps cap.",
  },
  {
    id: "dc4", time: "10:08:19", symbol: "ADA/USDT", strategy: "Mean Reversion", signal: "Sell", confidence: 55,
    checks: [
      { rule: "RSI reversion signal", passed: true },
      { rule: "Consecutive losses (2/5)", passed: true },
      { rule: "Daily loss limit", passed: false },
    ],
    verdict: "Blocked", reason: "Daily loss limit reached for this bot — trading halted for the day.",
  },
  {
    id: "dc5", time: "09:51:30", symbol: "XRP/USDT", strategy: "Mean Reversion", signal: "Buy", confidence: 61,
    checks: [
      { rule: "Reversion to mean confirmed", passed: true },
      { rule: "Exchange connectivity OK", passed: true },
      { rule: "Data feed fresh (< 5s)", passed: true },
      { rule: "No duplicate open order", passed: true },
    ],
    verdict: "Allowed", reason: "Execution-safety + risk checks passed — order submitted.",
  },
  {
    id: "dc6", time: "09:33:10", symbol: "BTC/USDT", strategy: "EMA Trend", signal: "Hold", confidence: 40,
    checks: [
      { rule: "Trend strength below threshold", passed: false },
    ],
    verdict: "Rejected", reason: "No trade — trend confidence below the entry threshold.",
  },
];

// PRIORITY 4 — Bot Health (per-bot self-monitoring).
export const botHealth: Record<string, BotHealth> = {
  default: { status: "Running", exchange: "Connected", dataFeed: "Live", heartbeat: "2s ago", uptime: "4h 12m", lastScan: "1s ago", lastTrade: "10:24:15", errors: 0 },
  b1: { status: "Running", exchange: "Connected", dataFeed: "Live", heartbeat: "1s ago", uptime: "6h 02m", lastScan: "0s ago", lastTrade: "10:24:15", errors: 0 },
  b5: { status: "Paused", exchange: "Connected", dataFeed: "Live", heartbeat: "3s ago", uptime: "2h 41m", lastScan: "3s ago", lastTrade: "10:08:19", errors: 1 },
  b6: { status: "Stopped", exchange: "Connected", dataFeed: "Delayed", heartbeat: "—", uptime: "0m", lastScan: "—", lastTrade: "—", errors: 0 },
};

// ---- Phase 1: TradingView webhook -> secret -> dedup -> risk -> paper ----
export const webhookConfig = {
  endpoint: "POST /webhook/tradingview",
  secretHeader: "X-Webhook-Secret",
  secretStatus: "Configured" as const,
  dedupWindowSec: 300,
  exposureLimitPct: 5,
  riskPerTradePct: 1,
};

export const webhookEvents: WebhookEvent[] = [
  { id: "wh1", time: "10:24:15", alertId: "tv-9f3a", symbol: "BTCUSDT", side: "Buy", entry: 67500, stop: 66800, stage: "execution", status: "Accepted", reason: "Paper trade opened — 0.001481 @ 67500" },
  { id: "wh2", time: "10:21:02", alertId: "tv-9f3a", symbol: "BTCUSDT", side: "Buy", entry: 67500, stop: 66800, stage: "dedup", status: "Duplicate", reason: "Duplicate alert_id within 300s window" },
  { id: "wh3", time: "10:18:44", alertId: "tv-8c1b", symbol: "ETHUSDT", side: "Buy", entry: 3120, stop: 3120, stage: "risk", status: "Rejected", reason: "Invalid stop (equal to entry)" },
  { id: "wh4", time: "10:12:31", alertId: "tv-7a90", symbol: "SOLUSDT", side: "Sell", entry: 172.4, stop: 176.0, stage: "execution", status: "Accepted", reason: "Paper trade opened — 6.94 @ 172.4" },
  { id: "wh5", time: "10:05:09", alertId: "tv-6d2e", symbol: "BTCUSDT", side: "Close", entry: 68010, stop: null, stage: "execution", status: "Accepted", reason: "Position closed @ 68010 (PnL +0.76)" },
  { id: "wh6", time: "09:58:22", alertId: "tv-5b14", symbol: "XRPUSDT", side: "Buy", entry: 0.52, stop: 0.515, stage: "controls", status: "Rejected", reason: "Trading paused — entry blocked" },
];
