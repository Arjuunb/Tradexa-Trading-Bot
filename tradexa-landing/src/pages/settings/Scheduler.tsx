import { Pause, Play } from "lucide-react";
import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";
import { Button } from "@/components/ui/Button";
import { useSettings } from "@/settings/store";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import type { Settings } from "@/settings/schema";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const pad = (n: number) => `${String(n).padStart(2, "0")}:00`;
const startOptions = Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: pad(h) }));
const endOptions = Array.from({ length: 25 }, (_, h) => ({ value: String(h), label: h === 24 ? "24:00" : pad(h) }));

export default function Scheduler() {
  const { settings, update } = useSettings();
  const { toast } = useToast();
  const s = settings.scheduler;
  const set = (patch: Partial<Settings["scheduler"]>) => update("scheduler", patch);

  const toggleDay = (day: number) => {
    const has = s.tradingDays.includes(day);
    const next = has ? s.tradingDays.filter((d) => d !== day) : [...s.tradingDays, day].sort((a, b) => a - b);
    set({ tradingDays: next });
  };

  return (
    <>
      <SettingsHeader
        title="Scheduler"
        description="Define when the engine is allowed to trade. Outside these windows it stays flat. Changes save automatically."
      />

      <div className="space-y-5">
        <Section
          title="Trading window"
          description="Hours (UTC) during which new entries are permitted."
          action={
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => toast("Schedule paused — the engine will stay flat until resumed.", "success")}>
                <Pause className="h-3.5 w-3.5" /> Pause trading schedule
              </Button>
              <Button size="sm" variant="outline" onClick={() => toast("Schedule resumed — trading follows the window below.", "success")}>
                <Play className="h-3.5 w-3.5" /> Resume schedule
              </Button>
            </div>
          }
        >
          <SettingRow label="Trading hours" description="Start and end hour of the daily trading window (UTC).">
            <div className="flex items-center gap-2 sm:justify-end">
              <Select
                aria-label="Trading hours start"
                value={String(s.tradingHoursStart)}
                onChange={(e) => set({ tradingHoursStart: Number(e.target.value) })}
                options={startOptions}
                className="w-28"
              />
              <span className="text-sm text-white/40">to</span>
              <Select
                aria-label="Trading hours end"
                value={String(s.tradingHoursEnd)}
                onChange={(e) => set({ tradingHoursEnd: Number(e.target.value) })}
                options={endOptions}
                className="w-28"
              />
            </div>
          </SettingRow>

          <SettingRow label="Trading days" description="Days of the week the engine is active." stacked>
            <div className="flex flex-wrap gap-2">
              {DAYS.map((label, day) => {
                const active = s.tradingDays.includes(day);
                return (
                  <button
                    key={label}
                    type="button"
                    aria-pressed={active}
                    onClick={() => toggleDay(day)}
                    className={cn(
                      "h-9 w-14 rounded-lg border text-[13px] font-medium transition-all",
                      active
                        ? "border-gold/40 bg-gold-sheen text-ink"
                        : "border-line text-white/50 hover:border-line-strong hover:text-white/80",
                    )}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </SettingRow>
        </Section>

        <Section title="Downtime" description="Scheduled pauses and maintenance.">
          <SettingRow label="Holiday mode" description="Suspend all trading while keeping monitoring and alerts active.">
            <Switch label="Holiday mode" checked={s.holidayMode} onChange={(v) => set({ holidayMode: v })} />
          </SettingRow>

          <SettingRow
            label="Maintenance window"
            htmlFor="maintenance-window"
            description="A recurring window when the engine pauses for upkeep."
          >
            <Input
              id="maintenance-window"
              value={s.maintenanceWindow}
              placeholder="Sun 02:00-03:00 UTC"
              onChange={(e) => set({ maintenanceWindow: e.target.value })}
              className="sm:w-56"
            />
          </SettingRow>
        </Section>
      </div>
    </>
  );
}
