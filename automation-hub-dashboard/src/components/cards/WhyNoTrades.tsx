import Icon from "../common/Icon";
import { useLive, type EngineDiagnostics } from "../../lib/api";

const tone: Record<string, { bg: string; fg: string; icon: string }> = {
  info: { bg: "#3b82f618", fg: "#3b82f6", icon: "info" },
  warning: { bg: "#f59e0b18", fg: "#f59e0b", icon: "warning" },
  critical: { bg: "#ef444418", fg: "#ef4444", icon: "warning" },
};

/** Explains why the bot isn't trading. Hidden when the engine is healthily
 *  trading (status "active") so it only shows up when there's something to say. */
export default function WhyNoTrades() {
  const { data } = useLive<EngineDiagnostics>("/engine/diagnostics", 5000);
  if (!data || data.status === "active") return null;

  const t = tone[data.severity] ?? tone.info;
  return (
    <div className="card" style={{ borderColor: t.fg, background: t.bg, display: "flex", gap: 12, alignItems: "flex-start" }}>
      <Icon name={t.icon} size={18} color={t.fg} />
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, color: t.fg }}>{data.headline}</div>
        <div className="dim" style={{ marginTop: 4, lineHeight: 1.55 }}>{data.detail}</div>
        <div className="dim mono" style={{ marginTop: 6, fontSize: 12 }}>
          {data.mode} · {data.timeframe} · source {data.data_source ?? "—"} · bars {data.bars} ·
          signals {data.signals} · trades {data.trades} · blocked {data.rejections}
        </div>
      </div>
    </div>
  );
}
