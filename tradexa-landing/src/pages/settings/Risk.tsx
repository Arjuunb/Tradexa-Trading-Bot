import type { ReactNode } from "react";
import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { EngineSyncBanner, LocalTag } from "@/components/settings/EngineSync";
import { Input } from "@/components/ui/Input";
import { Switch } from "@/components/ui/Switch";
import { useSettings } from "@/settings/store";
import { useEngineSettings, type EngineEditable } from "@/lib/hub";
import { useToast } from "@/lib/toast";
import type { Settings } from "@/settings/schema";

type RiskKey = keyof Settings["risk"];

/** Local % field ↔ engine fraction field (0.03 on the wire = 3% in the UI). */
const ENGINE_PCT: Partial<Record<RiskKey, keyof EngineEditable>> = {
  dailyLossLimit: "max_daily_loss_pct",
  weeklyLoss: "max_weekly_loss_pct",
  maxDrawdown: "max_drawdown_pct",
  riskPerTrade: "risk_per_trade_pct",
  maxExposure: "exposure_limit_pct",
};
const ENGINE_INT: Partial<Record<RiskKey, keyof EngineEditable>> = {
  maxLosingStreak: "max_consecutive_losses",
  tradingCooldownMin: "cooldown_after_loss_min",
};

function Num({
  value,
  onChange,
  suffix,
  step = 1,
  min = 0,
  max,
}: {
  value: number;
  onChange: (n: number) => void;
  suffix?: string;
  step?: number;
  min?: number;
  max?: number;
}) {
  return (
    <div className="flex items-center gap-2 sm:justify-end">
      <div className="relative w-32">
        <Input
          type="number"
          value={String(value)}
          step={step}
          min={min}
          max={max}
          onChange={(e) => onChange(Number(e.target.value))}
          className="pr-8 text-right"
        />
        {suffix && (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-white/40">
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}

export default function Risk() {
  const { settings, update } = useSettings();
  const { toast } = useToast();
  const { signedIn, engine, error, push } = useEngineSettings((ok, msg) =>
    toast(msg, ok ? "success" : "error"),
  );
  const r = settings.risk;
  const live = signedIn && engine !== null;

  const set = (patch: Partial<Settings["risk"]>) => update("risk", patch);

  /** Current display value: the ENGINE's truth when synced, else local. */
  const val = (k: RiskKey): number => {
    if (live) {
      const pct = ENGINE_PCT[k];
      if (pct) return Math.round((engine.editable[pct] as number) * 10000) / 100;
      const int = ENGINE_INT[k];
      if (int) return engine.editable[int] as number;
    }
    return r[k] as number;
  };

  /** Write local always; when synced, also push the mapped engine field. */
  const setNum = (k: RiskKey) => (n: number) => {
    set({ [k]: n } as Partial<Settings["risk"]>);
    if (!live) return;
    const pct = ENGINE_PCT[k];
    if (pct) push({ [pct]: n / 100 } as Partial<EngineEditable>);
    const int = ENGINE_INT[k];
    if (int) push({ [int]: Math.round(n) } as Partial<EngineEditable>);
  };

  const num = (k: RiskKey, suffix?: string, step = 1, max?: number) => (
    <Num value={val(k)} onChange={setNum(k)} suffix={suffix} step={step} max={max} />
  );

  const localMark = (text: string): ReactNode =>
    live ? (
      <>
        {text}
        <LocalTag />
      </>
    ) : (
      text
    );

  return (
    <>
      <SettingsHeader
        title="Risk Management"
        description="Hard limits the engine enforces on every trade. These guards are never bypassed."
      />

      <EngineSyncBanner signedIn={signedIn} error={error} />

      <div className="space-y-5">
        <Section title="Loss limits" description="Trading pauses for the period once a limit is hit.">
          <SettingRow label="Daily loss limit" description="% of equity per UTC day. 0 disables.">{num("dailyLossLimit", "%", 0.5)}</SettingRow>
          <SettingRow label="Weekly loss limit" description="% of equity per week. 0 disables.">{num("weeklyLoss", "%", 0.5)}</SettingRow>
          <SettingRow label="Monthly loss limit" description={localMark("% of equity per month.")}>{num("monthlyLoss", "%", 0.5)}</SettingRow>
          <SettingRow label="Maximum drawdown" description="Circuit-breaker halts new entries beyond this.">{num("maxDrawdown", "%", 0.5)}</SettingRow>
        </Section>

        <Section title="Per-trade sizing">
          <SettingRow label="Risk per trade" description="% of equity risked to the stop.">{num("riskPerTrade", "%", 0.1)}</SettingRow>
          <SettingRow label="Maximum leverage" description={localMark("Cap regardless of strategy.")}>{num("maxLeverage", "×", 1, 125)}</SettingRow>
          <SettingRow label="Maximum position size" description={localMark("% of equity per position.")}>{num("maxPositionSize", "%", 1)}</SettingRow>
          <SettingRow label="Maximum exposure" description="% of equity across all open trades.">{num("maxExposure", "%", 1)}</SettingRow>
        </Section>

        <Section title="Streak & cooldown">
          <SettingRow label="Maximum losing streak" description="Pause after this many consecutive losses. 0 disables.">{num("maxLosingStreak")}</SettingRow>
          <SettingRow label="Trading cooldown" description="Minutes to wait after a loss. 0 disables.">{num("tradingCooldownMin", "min", 5)}</SettingRow>
        </Section>

        <Section title="Automatic protection" description="The drawdown circuit breaker is built into the pipeline and always armed.">
          <SettingRow label="Circuit breaker" description={localMark("Halt trading when drawdown/loss limits trip.")}>
            <Switch label="Circuit breaker" checked={r.circuitBreaker} onChange={(v) => set({ circuitBreaker: v })} />
          </SettingRow>
          <SettingRow label="Emergency stop" description={localMark("Immediately block all new entries.")}>
            <Switch label="Emergency stop" checked={r.emergencyStop} onChange={(v) => set({ emergencyStop: v })} />
          </SettingRow>
          <SettingRow label="Auto-close all positions" description={localMark("Flatten everything when the breaker trips.")}>
            <Switch label="Auto close all" checked={r.autoCloseAll} onChange={(v) => set({ autoCloseAll: v })} />
          </SettingRow>
          <SettingRow label="Auto-pause after drawdown" description={localMark("Stop entries until manually resumed.")}>
            <Switch label="Auto pause after drawdown" checked={r.autoPauseAfterDrawdown} onChange={(v) => set({ autoPauseAfterDrawdown: v })} />
          </SettingRow>
        </Section>
      </div>
    </>
  );
}
