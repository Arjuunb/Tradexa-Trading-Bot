import type { ReactNode } from "react";
import Sparkline from "../chart/Sparkline";
import { statusColor } from "../../theme";

type Tone = "green" | "red" | "amber" | "blue" | "purple" | "default";

const TONE_COLOR: Record<string, string> = {
  green: "#22c55e", red: "#ef4444", amber: "#f59e0b",
  blue: "#3b82f6", purple: "#eab54f", default: "#8a93a6",
};

export function PageHeader({ title, subtitle, actions }: {
  title: string; subtitle?: string; actions?: ReactNode;
}) {
  return (
    <header className="pagehead">
      <div>
        <h1 className="pagehead-title">{title}</h1>
        {subtitle && <p className="pagehead-sub">{subtitle}</p>}
      </div>
      {actions && <div className="pagehead-actions">{actions}</div>}
    </header>
  );
}

export function StatCard({ label, value, sub, tone = "default", color, spark }: {
  label: string; value: string; sub?: string; tone?: Tone; color?: string; spark?: number[];
}) {
  const c = color ?? TONE_COLOR[tone];
  return (
    <div className="stat-card">
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${tone === "green" ? "pos" : tone === "red" ? "neg" : ""}`}>{value}</span>
      {sub && <span className="stat-sub dim">{sub}</span>}
      {spark && <div className="stat-spark"><Sparkline data={spark} color={c} height={30} /></div>}
    </div>
  );
}

export function Badge({ text, tone = "default" }: { text: string; tone?: Tone }) {
  const c = TONE_COLOR[tone];
  return <span className="ui-badge" style={{ background: `${c}22`, color: c }}>{text}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const c = statusColor(status);
  return <span className="ui-badge" style={{ background: `${c}22`, color: c }}>{status}</span>;
}

export function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      className={`toggle ${checked ? "on" : ""}`}
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-knob" />
    </button>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint dim">{hint}</span>}
    </label>
  );
}

export function EmptyState({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>;
}
