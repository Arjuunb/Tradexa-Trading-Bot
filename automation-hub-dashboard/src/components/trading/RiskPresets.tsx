import { useState } from "react";
import Card from "../common/Card";
import { Badge } from "../common/ui";
import { useApp } from "../../app-context";
import { apiPostJson, useLive } from "../../lib/api";

/** Risk Profile presets (§9). Each preset bundles risk-per-trade with matching
 *  drawdown / daily-loss / exposure / max-position guards. "Custom" points the
 *  user at Settings for advanced editing. Applies to the live engine + persists. */

interface Preset {
  risk_per_trade_pct: number; max_open_positions: number;
  max_daily_loss_pct: number; max_drawdown_pct: number; exposure_limit_pct: number;
}
interface PresetsResp { presets: Record<string, Preset>; active: string | null }

const ORDER = ["conservative", "balanced", "aggressive"] as const;
const LABEL: Record<string, string> = {
  conservative: "Conservative", balanced: "Balanced", aggressive: "Aggressive",
};
const pct = (n: number) => `${+(n * 100).toFixed(2)}%`;

export default function RiskPresets({ onApplied }: { onApplied?: () => void }) {
  const app = useApp();
  const data = useLive<PresetsResp>("/risk/presets", 8000);
  const [busy, setBusy] = useState<string | null>(null);
  const active = data.data?.active ?? null;
  const presets = data.data?.presets;

  const apply = async (name: string) => {
    setBusy(name);
    try {
      await apiPostJson("/risk/preset", { name });
      app.toast(`Risk profile → ${LABEL[name]}`, "success");
      data.refetch();
      onApplied?.();
    } catch {
      app.toast("Could not apply preset — backend unreachable.", "error");
    }
    setBusy(null);
  };

  return (
    <Card title="Risk Profile"
          subtitle="preset guardrails applied to the live engine · persists across restarts">
      <div className="preset-grid">
        {ORDER.map((name) => {
          const p = presets?.[name];
          const on = active === name;
          return (
            <button key={name} type="button" disabled={busy !== null}
                    className={`preset-btn ${on ? "active" : ""}`}
                    onClick={() => void apply(name)}>
              <div className="preset-head">
                <b>{LABEL[name]}</b>
                {on && <Badge text="active" tone="green" />}
              </div>
              <div className="preset-risk">{p ? pct(p.risk_per_trade_pct) : "—"}<span className="dim"> / trade</span></div>
              {p && (
                <ul className="preset-list">
                  <li><span className="dim">Max drawdown</span> {pct(p.max_drawdown_pct)}</li>
                  <li><span className="dim">Daily loss</span> {pct(p.max_daily_loss_pct)}</li>
                  <li><span className="dim">Max positions</span> {p.max_open_positions}</li>
                  <li><span className="dim">Exposure cap</span> {pct(p.exposure_limit_pct)}</li>
                </ul>
              )}
            </button>
          );
        })}
        <div className={`preset-btn preset-custom ${active === null ? "active" : ""}`}>
          <div className="preset-head"><b>Custom</b>{active === null && <Badge text="active" tone="gold" />}</div>
          <p className="dim" style={{ fontSize: 12, margin: "4px 0 0", lineHeight: 1.4 }}>
            Your current limits don't match a preset. Fine-tune every guard under
            {" "}<b>Settings → Risk</b>.
          </p>
        </div>
      </div>
    </Card>
  );
}
