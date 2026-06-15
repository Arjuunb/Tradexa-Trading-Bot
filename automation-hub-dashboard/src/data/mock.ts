import type {
  Activity,
  AlertItem,
  Bot,
  PerfMetric,
  RiskMetric,
  Ticker,
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
  {
    key: "total",
    label: "Total Bots",
    value: "6",
    sub: "3 Running",
    tone: "default" as const,
    color: "#8b5cf6",
    spark: [4, 5, 5, 6, 6, 6, 6],
  },
  {
    key: "running",
    label: "Running Bots",
    value: "3",
    sub: "50%",
    tone: "green" as const,
    color: "#22c55e",
    spark: [1, 2, 2, 3, 2, 3, 3],
  },
  {
    key: "paper",
    label: "Paper Bots",
    value: "2",
    sub: "33%",
    tone: "blue" as const,
    color: "#3b82f6",
    spark: [1, 1, 2, 2, 2, 1, 2],
  },
  {
    key: "live",
    label: "Live Bots",
    value: "1",
    sub: "17%",
    tone: "purple" as const,
    color: "#8b5cf6",
    spark: [0, 1, 1, 1, 1, 1, 1],
  },
];

export const totalPnl = {
  value: "+$2,340.75",
  pct: "+12.45%",
};

// Equity curve — 7 days, May 16..22.
export const equityDates = [
  "May 16",
  "May 17",
  "May 18",
  "May 19",
  "May 20",
  "May 21",
  "May 22",
];
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
  { id: "b1", name: "EMA Trend Bot", status: "Live", pair: "BTC/USDT", timeframe: "15m", pnl7d: 342.21 },
  { id: "b2", name: "SMC Breakout Bot", status: "Running", pair: "ETH/USDT", timeframe: "1h", pnl7d: 186.75 },
  { id: "b3", name: "RSI Scalper", status: "Running", pair: "SOL/USDT", timeframe: "5m", pnl7d: 167.32 },
  { id: "b4", name: "Swing Master", status: "Paper", pair: "XRP/USDT", timeframe: "4h", pnl7d: 96.12 },
  { id: "b5", name: "Mean Reversion", status: "Paper", pair: "ADA/USDT", timeframe: "1h", pnl7d: -45.32 },
  { id: "b6", name: "AI Momentum Bot", status: "Stopped", pair: "BNB/USDT", timeframe: "1h", pnl7d: 0 },
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
