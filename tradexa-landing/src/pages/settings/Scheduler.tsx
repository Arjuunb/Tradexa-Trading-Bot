import { Pause, Play } from "lucide-react";
import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { EngineSyncBanner, LocalTag } from "@/components/settings/EngineSync";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";
import { Button } from "@/components/ui/Button";
import { useSettings } from "@/settings/store";
import { useEngineSettings, hubFetch } from "@/lib/hub";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import type { Settings } from "@/settings/schema";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
// UI day index (Sun=0..Sat=6) → engine bit (Python weekday: Mon=0..Sun=6).
const bitOf = (uiDay: number) => (uiDay + 6) % 7;

const pad = (n: number) => `${String(n).padStart(2, "0")}:00`;
const startOptions = Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: pad(h) }));
const endOptions = Array.from({ length: 25 }, (_, h) => ({ value: String(h), label: h === 24 ? "24:00" : pad(h) }));

export default function Scheduler() {
  const { settings, update } = useSettings();
  const { toast } = useToast();
  const { signedIn, engine, error, push } = useEngineSettings((ok, msg) =>
    toast(msg, ok ? "success" : "error"),
  );
  const s = settings.scheduler;
  const live = signedIn && engine !== null;
  const set = (patch: Partial<Settings["scheduler"]>) => update("scheduler", patch);

  const hoursStart = live ? engine.editable.session_start : s.tradingHoursStart;
  const hoursEnd = live ? engine.editable.session_end : s.tradingHoursEnd;
  const isDayOn = (uiDay: number): boolean =>
    live ? ((engine.editable.trading_days_mask >> bitOf(uiDay)) & 1) === 1 : s.tradingDays.includes(uiDay);

  const toggleDay = (uiDay: number) => {
    const has = s.tradingDays.includes(uiDay);
    const nextLocal = has ? s.tradingDays.filter((d) => d !== uiDay) : [...s.tradingDays, uiDay].sort((a, b) => a - b);
    set({ tradingDays: nextLocal });
    if (!live) return;
    const mask = engine.editable.trading_days_mask ^ (1 << bitOf(uiDay));
    if (mask === 0) {
      toast("At least one trading day must stay enabled.", "error");
      return;
    }
    push({ trading_days_mask: mask });
  };

  const control = async (action: "pause-all" | "resume", label: string) => {
    if (!signedIn) {
      toast("Sign in to control the live engine.", "info");
      return;
    }
    try {
      await hubFetch(`/controls/${action}`, { method: "POST" });
      toast(label, "success");
    } catch {
      toast("Engine control failed — is the backend reachable?", "error");
    }
  };

  return (
    <>
      <SettingsHeader
        title="Scheduler"
        description="Define when the engine is allowed to trade. Outside these windows it stays flat."
      />

      <EngineSyncBanner signedIn={signedIn} error={error} />

      <div className="space-y-5">
        <Section
          title="Trading window"
          description="Hours (UTC) during which new entries are permitted."
          action={
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => void control("pause-all", "Trading PAUSED — entries blocked until resumed.")}>
                <Pause className="h-3.5 w-3.5" /> Pause trading
              </Button>
              <Button size="sm" variant="outline" onClick={() => void control("resume", "Trading RESUMED — the window below applies.")}>
                <Play className="h-3.5 w-3.5" /> Resume
              </Button>
            </div>
          }
        >
          <SettingRow label="Trading hours" description={live ? "The engine's LIVE session window (UTC)." : "Start and end hour of the daily trading window (UTC)."}>
            <div className="flex items-center gap-2 sm:justify-end">
              <Select
                aria-label="Trading hours start"
                value={String(hoursStart)}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  set({ tradingHoursStart: n });
                  if (live) push({ session_start: n });
                }}
                options={startOptions}
                className="w-28"
              />
              <span className="text-sm text-white/40">to</span>
              <Select
                aria-label="Trading hours end"
                value={String(hoursEnd)}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  set({ tradingHoursEnd: n });
                  if (live) push({ session_end: n });
                }}
                options={endOptions}
                className="w-28"
              />
            </div>
          </SettingRow>

          <SettingRow label="Trading days" description={live ? "The engine's LIVE weekday gate (UTC)." : "Days of the week the engine is active."} stacked>
            <div className="flex flex-wrap gap-2">
              {DAYS.map((label, day) => {
                const active = isDayOn(day);
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
          <SettingRow label="Holiday mode" description={<>Suspend all trading while keeping monitoring active.{live && <LocalTag />}</>}>
            <Switch label="Holiday mode" checked={s.holidayMode} onChange={(v) => set({ holidayMode: v })} />
          </SettingRow>

          <SettingRow
            label="Maintenance window"
            htmlFor="maintenance-window"
            description={<>A recurring window when the engine pauses for upkeep.{live && <LocalTag />}</>}
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
