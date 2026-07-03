interface ProgressBarProps {
  pct: number;
  tone?: "green" | "amber" | "red" | "purple" | "blue";
}

const TONE: Record<string, string> = {
  green: "#22c55e",
  amber: "#f59e0b",
  red: "#ef4444",
  purple: "#eab54f",
  blue: "#3b82f6",
};

export default function ProgressBar({ pct, tone = "purple" }: ProgressBarProps) {
  const w = Math.max(0, Math.min(100, pct));
  return (
    <div className="progress">
      <div className="progress-fill" style={{ width: `${w}%`, background: TONE[tone] }} />
    </div>
  );
}
