import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Input } from "@/components/ui/Input";
import { Switch } from "@/components/ui/Switch";
import { useSettings } from "@/settings/store";
import type { Settings } from "@/settings/schema";

type RiskKey = keyof Settings["risk"];

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
  const r = settings.risk;
  const set = (patch: Partial<Settings["risk"]>) => update("risk", patch);
  const num = (k: RiskKey, suffix?: string, step = 1, max?: number) => (
    <Num value={r[k] as number} onChange={(n) => set({ [k]: n } as Partial<Settings["risk"]>)} suffix={suffix} step={step} max={max} />
  );

  return (
    <>
      <SettingsHeader
        title="Risk Management"
        description="Hard limits the engine enforces on every trade. These guards are never bypassed. Autosaves."
      />

      <div className="space-y-5">
        <Section title="Loss limits" description="Trading pauses for the period once a limit is hit.">
          <SettingRow label="Daily loss limit" description="% of equity per UTC day.">{num("dailyLossLimit", "%", 0.5)}</SettingRow>
          <SettingRow label="Weekly loss limit" description="% of equity per week.">{num("weeklyLoss", "%", 0.5)}</SettingRow>
          <SettingRow label="Monthly loss limit" description="% of equity per month.">{num("monthlyLoss", "%", 0.5)}</SettingRow>
          <SettingRow label="Maximum drawdown" description="Circuit-breaker halts new entries beyond this.">{num("maxDrawdown", "%", 0.5)}</SettingRow>
        </Section>

        <Section title="Per-trade sizing">
          <SettingRow label="Risk per trade" description="% of equity risked to the stop.">{num("riskPerTrade", "%", 0.1)}</SettingRow>
          <SettingRow label="Maximum leverage" description="Cap regardless of strategy.">{num("maxLeverage", "×", 1, 125)}</SettingRow>
          <SettingRow label="Maximum position size" description="% of equity per position.">{num("maxPositionSize", "%", 1)}</SettingRow>
          <SettingRow label="Maximum exposure" description="% of equity across all open trades.">{num("maxExposure", "%", 1)}</SettingRow>
        </Section>

        <Section title="Streak & cooldown">
          <SettingRow label="Maximum losing streak" description="Pause after this many consecutive losses.">{num("maxLosingStreak")}</SettingRow>
          <SettingRow label="Trading cooldown" description="Minutes to wait after a loss.">{num("tradingCooldownMin", "min", 5)}</SettingRow>
        </Section>

        <Section title="Automatic protection">
          <SettingRow label="Circuit breaker" description="Halt trading when drawdown/loss limits trip.">
            <Switch label="Circuit breaker" checked={r.circuitBreaker} onChange={(v) => set({ circuitBreaker: v })} />
          </SettingRow>
          <SettingRow label="Emergency stop" description="Immediately block all new entries.">
            <Switch label="Emergency stop" checked={r.emergencyStop} onChange={(v) => set({ emergencyStop: v })} />
          </SettingRow>
          <SettingRow label="Auto-close all positions" description="Flatten everything when the breaker trips.">
            <Switch label="Auto close all" checked={r.autoCloseAll} onChange={(v) => set({ autoCloseAll: v })} />
          </SettingRow>
          <SettingRow label="Auto-pause after drawdown" description="Stop entries until manually resumed.">
            <Switch label="Auto pause after drawdown" checked={r.autoPauseAfterDrawdown} onChange={(v) => set({ autoPauseAfterDrawdown: v })} />
          </SettingRow>
        </Section>
      </div>
    </>
  );
}
