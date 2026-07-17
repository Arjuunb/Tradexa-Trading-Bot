import { SettingsHeader, Section, SettingRow } from "@/components/settings/primitives";
import { Switch } from "@/components/ui/Switch";
import { useSettings } from "@/settings/store";
import type { Settings } from "@/settings/schema";

type AutomationKey = keyof Settings["automation"];

const LIFECYCLE: { key: AutomationKey; label: string; desc: string }[] = [
  { key: "autoStart", label: "Auto start", desc: "Launch the engine automatically when the platform boots." },
  { key: "autoRestart", label: "Auto restart", desc: "Restart the engine after a crash or unhandled error." },
  { key: "autoReconnect", label: "Auto reconnect", desc: "Re-establish exchange and data feeds when a connection drops." },
  { key: "autoUpdate", label: "Auto update", desc: "Apply strategy and platform updates as they are released." },
];

const MAINTENANCE: { key: AutomationKey; label: string; desc: string }[] = [
  { key: "autoBackups", label: "Auto backups", desc: "Snapshot configuration and trade history on a schedule." },
  { key: "autoSync", label: "Auto sync", desc: "Keep settings and state synced across your devices." },
  { key: "autoJournalExport", label: "Auto journal export", desc: "Export the trade journal to storage after each session." },
  { key: "autoReportGeneration", label: "Auto report generation", desc: "Compile performance reports automatically at period close." },
];

export default function Automation() {
  const { settings, update } = useSettings();
  const a = settings.automation;
  const set = (patch: Partial<Settings["automation"]>) => update("automation", patch);

  const rows = (items: { key: AutomationKey; label: string; desc: string }[]) =>
    items.map((item) => (
      <SettingRow key={item.key} label={item.label} description={item.desc}>
        <Switch label={item.label} checked={a[item.key]} onChange={(v) => set({ [item.key]: v })} />
      </SettingRow>
    ));

  return (
    <>
      <SettingsHeader
        title="Automation"
        description="Let TradeLogX Nexus manage its own lifecycle and housekeeping so it keeps running unattended. Changes save automatically."
      />

      <div className="space-y-5">
        <Section title="Engine lifecycle" description="How the trading engine starts, recovers and stays connected.">
          {rows(LIFECYCLE)}
        </Section>

        <Section title="Data & maintenance" description="Backups, syncing and scheduled exports.">
          {rows(MAINTENANCE)}
        </Section>
      </div>
    </>
  );
}
