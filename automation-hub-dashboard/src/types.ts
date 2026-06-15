export type BotStatus = "Live" | "Running" | "Paper" | "Stopped";

export interface Bot {
  id: string;
  name: string;
  status: BotStatus;
  pair: string;
  timeframe: string;
  pnl7d: number;
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
  pct: number; // 0..100
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
