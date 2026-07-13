import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Select } from "@/components/ui/Select";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useSettings } from "@/settings/store";
import type { Settings } from "@/settings/schema";

const LANGS = [["en", "English"], ["es", "Español"], ["de", "Deutsch"], ["fr", "Français"], ["ja", "日本語"], ["zh", "中文"]];
const CURRENCIES = ["USD", "EUR", "GBP", "JPY", "USDT"];
const TIMEZONES = ["UTC", "America/New_York", "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Asia/Singapore", "Asia/Tokyo", "Asia/Dubai"];
const DATE_FORMATS = ["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"] as const;
const NUM_FORMATS = ["1,234.56", "1.234,56", "1 234.56"] as const;

export default function Region() {
  const { settings, update } = useSettings();
  const r = settings.region;
  const set = (patch: Partial<Settings["region"]>) => update("region", patch);

  const sampleNumber =
    r.numberFormat === "1.234,56" ? "1.234.567,89" : r.numberFormat === "1 234.56" ? "1 234 567.89" : "1,234,567.89";
  const sampleDate =
    r.dateFormat === "DD/MM/YYYY" ? "13/07/2026" : r.dateFormat === "MM/DD/YYYY" ? "07/13/2026" : "2026-07-13";
  const sampleTime = r.timeFormat === "12h" ? "2:30 PM" : "14:30";

  return (
    <>
      <SettingsHeader title="Language & Region" description="Localize how Tradexa displays dates, numbers and currency. Autosaves." />

      <div className="space-y-5">
        <Section title="Language">
          <SettingRow label="Display language" description="The language used across the interface.">
            <div className="sm:w-48">
              <Select value={r.language} options={LANGS.map(([v, l]) => ({ value: v, label: l }))} onChange={(e) => set({ language: e.target.value })} />
            </div>
          </SettingRow>
        </Section>

        <Section title="Formats">
          <SettingRow label="Date format">
            <div className="sm:w-48">
              <Select value={r.dateFormat} options={DATE_FORMATS.map((v) => ({ value: v, label: v }))} onChange={(e) => set({ dateFormat: e.target.value as Settings["region"]["dateFormat"] })} />
            </div>
          </SettingRow>
          <SettingRow label="Time format">
            <SegmentedControl value={r.timeFormat} onChange={(v) => set({ timeFormat: v })} options={[{ value: "24h", label: "24-hour" }, { value: "12h", label: "12-hour" }]} />
          </SettingRow>
          <SettingRow label="Currency">
            <div className="sm:w-40">
              <Select value={r.currency} options={CURRENCIES.map((c) => ({ value: c, label: c }))} onChange={(e) => set({ currency: e.target.value })} />
            </div>
          </SettingRow>
          <SettingRow label="Number formatting">
            <div className="sm:w-48">
              <Select value={r.numberFormat} options={NUM_FORMATS.map((v) => ({ value: v, label: v }))} onChange={(e) => set({ numberFormat: e.target.value as Settings["region"]["numberFormat"] })} />
            </div>
          </SettingRow>
          <SettingRow label="Timezone">
            <div className="sm:w-56">
              <Select value={r.timezone} options={TIMEZONES.map((t) => ({ value: t, label: t }))} onChange={(e) => set({ timezone: e.target.value })} />
            </div>
          </SettingRow>
        </Section>

        <Section title="Preview">
          <div className="flex flex-wrap gap-x-8 gap-y-2 py-4 font-mono text-sm text-white/70">
            <span><span className="text-white/40">Date </span>{sampleDate}</span>
            <span><span className="text-white/40">Time </span>{sampleTime}</span>
            <span><span className="text-white/40">Number </span>{sampleNumber}</span>
            <span><span className="text-white/40">Currency </span>{r.currency}</span>
          </div>
        </Section>
      </div>
    </>
  );
}
